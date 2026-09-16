#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_reader_extended.py — Pruebas unitarias para shared/rfid_reader.py.

Cubre las líneas 163–224:
  - procesar()       → toda la lógica de acceso
  - leer_uid()       → conversión de bytes a string de UID
  - _escribir_estado(), _modo_admin_activo(), _notificar_admin_scan()

Corre con:
    ./venv/bin/python -m pytest shared/tests/test_reader_extended.py -v
"""

import os
import sqlite3
import sys
from datetime import date
from unittest.mock import patch, MagicMock
import pytest

# ---------------------------------------------------------------------------
# Forzar modo simulación antes de importar el módulo
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

sys.modules.setdefault('mfrc522', MagicMock())
sys.modules.setdefault('RPi',      MagicMock())
sys.modules.setdefault('RPi.GPIO', MagicMock())

import shared.rfid_reader as reader


# ===========================================================================
# Fixtures
# ===========================================================================

SCHEMA_SQL = """
CREATE TABLE estudiantes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT,
    apellido_paterno TEXT,
    matricula        TEXT UNIQUE,
    carrera          TEXT DEFAULT "ITIC's",
    semestre         INTEGER DEFAULT 1,
    estado           TEXT DEFAULT 'activo'
);
CREATE TABLE tarjetas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    id_estudiante INTEGER REFERENCES estudiantes(id),
    activa        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE registros_asistencia (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante INTEGER,
    uid           TEXT,
    timestamp     TEXT,
    fecha_dia     TEXT,
    tipo_evento   TEXT,
    mensaje       TEXT
);
"""


@pytest.fixture()
def db_path(tmp_path):
    """Base de datos SQLite en disco temporal con datos base."""
    path = str(tmp_path / 'rfid_test.db')
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO estudiantes (nombre, apellido_paterno, estado) VALUES ('Ana', 'Garcia', 'activo')")
    conn.execute("INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES ('AABBCCDD', 1, 1)")
    conn.execute("INSERT INTO estudiantes (nombre, apellido_paterno, estado) VALUES ('Luis', 'Perez', 'inactivo')")
    conn.execute("INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES ('11223344', 2, 1)")
    conn.execute("INSERT INTO estudiantes (nombre, apellido_paterno, estado) VALUES ('Rosa', 'Lopez', 'activo')")
    conn.execute("INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES ('DEADBEEF', 3, 0)")
    conn.commit()
    conn.close()
    return path


def _open_conn(path):
    """Abre una conexión nueva a la DB (para verificar resultados post-procesar)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture(autouse=True)
def patch_get_db(db_path):
    """get_db() devuelve una conexión nueva cada vez — igual que en producción."""
    with patch.object(reader, 'get_db', side_effect=lambda: _open_conn(db_path)):
        yield db_path


# ===========================================================================
# procesar() — uid desconocido
# ===========================================================================

class TestProcesarUidDesconocido:

    def test_retorna_rebote(self, db_path):
        tipo, _, _ = reader.procesar('FFFFFFFF')
        assert tipo == 'rebote'

    def test_nombre_es_desconocido(self, db_path):
        _, nombre, _ = reader.procesar('FFFFFFFF')
        assert nombre == 'DESCONOCIDO'

    def test_mensaje_indica_no_registrado(self, db_path):
        _, _, msg = reader.procesar('FFFFFFFF')
        assert 'no registrado' in msg.lower()

    def test_inserta_registro_en_db(self, db_path):
        reader.procesar('FFFFFFFF')
        conn = _open_conn(db_path)
        row = conn.execute("SELECT * FROM registros_asistencia WHERE uid='FFFFFFFF'").fetchone()
        conn.close()
        assert row is not None
        assert row['tipo_evento'] == 'rebote'
        assert row['id_estudiante'] is None


# ===========================================================================
# procesar() — tarjeta inactiva
# ===========================================================================

class TestProcesarTarjetaInactiva:

    def test_retorna_rebote(self, db_path):
        tipo, _, _ = reader.procesar('DEADBEEF')
        assert tipo == 'rebote'

    def test_nombre_del_estudiante_presente(self, db_path):
        _, nombre, _ = reader.procesar('DEADBEEF')
        assert 'Rosa' in nombre

    def test_mensaje_indica_tarjeta_inactiva(self, db_path):
        _, _, msg = reader.procesar('DEADBEEF')
        assert 'inactiva' in msg.lower()

    def test_inserta_registro_rebote(self, db_path):
        reader.procesar('DEADBEEF')
        conn = _open_conn(db_path)
        row = conn.execute("SELECT * FROM registros_asistencia WHERE uid='DEADBEEF'").fetchone()
        conn.close()
        assert row['tipo_evento'] == 'rebote'


# ===========================================================================
# procesar() — estudiante inactivo
# ===========================================================================

class TestProcesarEstudianteInactivo:

    def test_retorna_rebote(self, db_path):
        tipo, _, _ = reader.procesar('11223344')
        assert tipo == 'rebote'

    def test_nombre_del_estudiante_presente(self, db_path):
        _, nombre, _ = reader.procesar('11223344')
        assert 'Luis' in nombre

    def test_mensaje_indica_estudiante_inactivo(self, db_path):
        _, _, msg = reader.procesar('11223344')
        assert 'inactivo' in msg.lower()

    def test_inserta_registro_con_id_estudiante(self, db_path):
        reader.procesar('11223344')
        conn = _open_conn(db_path)
        row = conn.execute("SELECT * FROM registros_asistencia WHERE uid='11223344'").fetchone()
        conn.close()
        assert row['id_estudiante'] == 2
        assert row['tipo_evento'] == 'rebote'


# ===========================================================================
# procesar() — primer escaneo (aceptado)
# ===========================================================================

class TestProcesarAceptado:

    def test_retorna_aceptado(self, db_path):
        tipo, _, _ = reader.procesar('AABBCCDD')
        assert tipo == 'aceptado'

    def test_nombre_correcto(self, db_path):
        _, nombre, _ = reader.procesar('AABBCCDD')
        assert 'Ana' in nombre

    def test_mensaje_acceso_permitido(self, db_path):
        _, _, msg = reader.procesar('AABBCCDD')
        assert 'permitido' in msg.lower()

    def test_inserta_registro_aceptado(self, db_path):
        reader.procesar('AABBCCDD')
        conn = _open_conn(db_path)
        row = conn.execute("SELECT * FROM registros_asistencia WHERE uid='AABBCCDD'").fetchone()
        conn.close()
        assert row['tipo_evento'] == 'aceptado'
        assert row['id_estudiante'] == 1

    def test_fecha_dia_es_hoy(self, db_path):
        reader.procesar('AABBCCDD')
        conn = _open_conn(db_path)
        row = conn.execute("SELECT fecha_dia FROM registros_asistencia WHERE uid='AABBCCDD'").fetchone()
        conn.close()
        assert row['fecha_dia'] == date.today().isoformat()


# ===========================================================================
# procesar() — segundo escaneo (ya_escaneado)
# ===========================================================================

class TestProcesarYaEscaneado:

    def test_segundo_escaneo_es_ya_escaneado(self, db_path):
        reader.procesar('AABBCCDD')
        tipo, _, _ = reader.procesar('AABBCCDD')
        assert tipo == 'ya_escaneado'

    def test_mensaje_incluye_numero_de_vez(self, db_path):
        reader.procesar('AABBCCDD')
        _, _, msg = reader.procesar('AABBCCDD')
        assert '2' in msg

    def test_inserta_dos_registros(self, db_path):
        reader.procesar('AABBCCDD')
        reader.procesar('AABBCCDD')
        conn = _open_conn(db_path)
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM registros_asistencia WHERE uid='AABBCCDD'"
        ).fetchone()['n']
        conn.close()
        assert count == 2

    def test_tercer_escaneo_sigue_diciendo_ya_registrado(self, db_path):
        """veces cuenta solo 'aceptado' — siempre 1 — mensaje siempre dice 2a vez."""
        reader.procesar('AABBCCDD')
        reader.procesar('AABBCCDD')
        tipo, _, msg = reader.procesar('AABBCCDD')
        assert tipo == 'ya_escaneado'
        assert 'ya registrado' in msg.lower()


# ===========================================================================
# leer_uid()
# ===========================================================================

class TestLeerUid:

    def _make_reader(self, req_status, anticoll_status, uid_bytes):
        mock_reader = MagicMock()
        mock_reader.PICC_REQIDL = 0x26
        mock_reader.MI_OK       = 0
        mock_reader.MFRC522_Request.return_value  = (req_status, None)
        mock_reader.MFRC522_Anticoll.return_value = (anticoll_status, uid_bytes)
        return mock_reader

    def test_retorna_none_si_request_falla(self):
        r = self._make_reader(req_status=1, anticoll_status=0, uid_bytes=[0xAA, 0xBB, 0xCC, 0xDD])
        assert reader.leer_uid(r) is None

    def test_retorna_none_si_anticoll_falla(self):
        r = self._make_reader(req_status=0, anticoll_status=1, uid_bytes=[0xAA, 0xBB, 0xCC, 0xDD])
        assert reader.leer_uid(r) is None

    def test_retorna_none_si_uid_vacio(self):
        r = self._make_reader(req_status=0, anticoll_status=0, uid_bytes=[])
        assert reader.leer_uid(r) is None

    def test_retorna_string_cuando_ok(self):
        r = self._make_reader(req_status=0, anticoll_status=0, uid_bytes=[0xAA, 0xBB, 0xCC, 0xDD])
        assert isinstance(reader.leer_uid(r), str)

    def test_uid_bytes_conocidos(self):
        r = self._make_reader(req_status=0, anticoll_status=0, uid_bytes=[0x01, 0x02, 0x03, 0x04])
        assert reader.leer_uid(r) == str((1 << 24) | (2 << 16) | (3 << 8) | 4)

    def test_usa_solo_primeros_4_bytes(self):
        r1 = self._make_reader(req_status=0, anticoll_status=0, uid_bytes=[0x01, 0x02, 0x03, 0x04])
        r2 = self._make_reader(req_status=0, anticoll_status=0, uid_bytes=[0x01, 0x02, 0x03, 0x04, 0xFF])
        assert reader.leer_uid(r1) == reader.leer_uid(r2)


# ===========================================================================
# _escribir_estado()
# ===========================================================================

class TestEscribirEstado:

    def test_escribe_estado_en_archivo(self, tmp_path):
        status_file = str(tmp_path / 'rfid_reader_status')
        with patch.object(reader, 'STATUS_FILE', status_file):
            reader._escribir_estado('ok')
        assert os.path.isfile(status_file)
        assert 'ok' in open(status_file).read()

    def test_estado_incluye_timestamp(self, tmp_path):
        status_file = str(tmp_path / 'rfid_reader_status')
        with patch.object(reader, 'STATUS_FILE', status_file):
            reader._escribir_estado('reiniciando')
        assert 'T' in open(status_file).read()

    def test_crea_directorio_si_no_existe(self, tmp_path):
        status_file = str(tmp_path / 'subdir' / 'status')
        with patch.object(reader, 'STATUS_FILE', status_file):
            reader._escribir_estado('ok')
        assert os.path.isfile(status_file)

    def test_no_lanza_excepcion_si_falla_escritura(self):
        with patch.object(reader, 'STATUS_FILE', '/root/prohibido/status'), \
             patch('builtins.open', side_effect=PermissionError):
            reader._escribir_estado('error')


# ===========================================================================
# _modo_admin_activo()
# ===========================================================================

class TestModoAdminActivo:

    def test_true_si_archivo_existe(self, tmp_path):
        flag = str(tmp_path / 'rfid_admin_mode')
        open(flag, 'w').close()
        with patch.object(reader, 'ADMIN_FLAG', flag):
            assert reader._modo_admin_activo() is True

    def test_false_si_archivo_no_existe(self, tmp_path):
        flag = str(tmp_path / 'rfid_admin_mode')
        with patch.object(reader, 'ADMIN_FLAG', flag):
            assert reader._modo_admin_activo() is False


# ===========================================================================
# _notificar_admin_scan()
# ===========================================================================

class TestNotificarAdminScan:

    def test_escribe_uid_en_archivo(self, tmp_path):
        uid_file = str(tmp_path / 'rfid_admin_uid')
        with patch.object(reader, 'ADMIN_UID_FILE', uid_file):
            reader._notificar_admin_scan('AABBCCDD')
        assert 'AABBCCDD' in open(uid_file).read()

    def test_archivo_incluye_timestamp(self, tmp_path):
        uid_file = str(tmp_path / 'rfid_admin_uid')
        with patch.object(reader, 'ADMIN_UID_FILE', uid_file):
            reader._notificar_admin_scan('AABBCCDD')
        assert 'T' in open(uid_file).read()

    def test_no_lanza_excepcion_si_falla_escritura(self):
        with patch.object(reader, 'ADMIN_UID_FILE', '/root/prohibido/uid'), \
             patch('builtins.open', side_effect=PermissionError):
            reader._notificar_admin_scan('AABBCCDD')