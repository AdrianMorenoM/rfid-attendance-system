"""
test_reader.py — pruebas unitarias de rfid_reader.py

Cubre:
  - procesar(): los 5 tipos de evento
  - debounce lógico
  - modo admin (archivos de señal)
  - _escribir_estado()
  - cleanup() elimina archivos de señal

Ejecutar:
    cd ~/rfid-system
    source venv/bin/activate
    pytest shared/tests/test_reader.py -v
"""
import os, sys, sqlite3, time, importlib, pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

# El conftest ya ajusta sys.path.
# Si ejecutas este archivo solo, añadir el shared al path:
_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.dirname(_HERE)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)


# ────────────────────────────────────────────────────────────────────────────
# Fixture: módulo reader con hardware simulado
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def reader_mod(tmp_db, tmp_path, monkeypatch):
    """
    Importa rfid_reader con mocks de GPIO y mfrc522,
    apuntando la BD al archivo temporal.
    """
    # Simular que no hay hardware (modo simulación automático)
    mfrc522_mock = MagicMock()
    gpio_mock    = MagicMock()

    monkeypatch.setitem(sys.modules, "mfrc522",       mfrc522_mock)
    monkeypatch.setitem(sys.modules, "RPi",           gpio_mock)
    monkeypatch.setitem(sys.modules, "RPi.GPIO",      gpio_mock)

    import rfid_reader as mod
    importlib.reload(mod)

    # Redirigir BD y archivos de señal a tmp
    mod.DB              = tmp_db
    mod.ADMIN_FLAG      = str(tmp_path / "rfid_admin_mode")
    mod.ADMIN_UID_FILE  = str(tmp_path / "rfid_admin_uid")
    mod.STATUS_FILE     = str(tmp_path / "rfid_reader_status")
    mod.RFID_OK         = False   # modo simulación

    yield mod


# ────────────────────────────────────────────────────────────────────────────
# procesar() — lógica de negocio central
# ────────────────────────────────────────────────────────────────────────────

class TestProcesar:

    def test_uid_desconocido_genera_rebote(self, reader_mod):
        """Un UID que no existe en tarjetas → rebote."""
        tipo, nombre, msg = reader_mod.procesar("FFFFFFFF")
        assert tipo   == "rebote"
        assert nombre == "DESCONOCIDO"
        assert "no registrado" in msg.lower()

    def test_uid_registrado_primera_vez_aceptado(self, reader_mod):
        """UID válido y activo, primera pasada del día → aceptado."""
        tipo, nombre, msg = reader_mod.procesar("AABBCCDD")
        assert tipo   == "aceptado"
        assert "Juan" in nombre
        assert "permitido" in msg.lower()

    def test_uid_segunda_pasada_ya_escaneado(self, reader_mod):
        """Mismo UID dos veces en el mismo día → ya_escaneado la segunda."""
        reader_mod.procesar("AABBCCDD")
        tipo, nombre, msg = reader_mod.procesar("AABBCCDD")
        assert tipo == "ya_escaneado"
        assert "ya registrado" in msg.lower()

    def test_tarjeta_inactiva_genera_rebote(self, reader_mod):
        """Tarjeta CAFEBABE está activa=0 → rebote."""
        tipo, nombre, msg = reader_mod.procesar("CAFEBABE")
        assert tipo == "rebote"
        assert "inactiva" in msg.lower()

    def test_estudiante_inactivo_genera_rebote(self, reader_mod):
        """
        DEADBEEF pertenece a Pedro Gómez (estado='inactivo') → rebote.
        """
        tipo, nombre, msg = reader_mod.procesar("DEADBEEF")
        assert tipo == "rebote"
        assert "inactivo" in msg.lower()

    def test_registro_queda_guardado_en_db(self, reader_mod):
        """Después de procesar, el registro debe aparecer en la BD."""
        reader_mod.procesar("AABBCCDD")
        conn = sqlite3.connect(reader_mod.DB)
        row  = conn.execute(
            "SELECT tipo_evento FROM registros_asistencia WHERE uid=?",
            ("AABBCCDD",)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "aceptado"

    def test_rebote_desconocido_queda_en_db(self, reader_mod):
        """Los rebotes de UIDs desconocidos también se guardan."""
        reader_mod.procesar("FFFFFFFF")
        conn = sqlite3.connect(reader_mod.DB)
        row  = conn.execute(
            "SELECT tipo_evento FROM registros_asistencia WHERE uid=?",
            ("FFFFFFFF",)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "rebote"

    def test_nombre_compuesto_correcto(self, reader_mod):
        """El nombre devuelto combina nombre + apellido_paterno."""
        _, nombre, _ = reader_mod.procesar("11223344")
        assert "María" in nombre
        assert "López" in nombre

    def test_multiples_uids_independientes(self, reader_mod):
        """Dos alumnos distintos en el mismo día → ambos aceptados."""
        t1, _, _ = reader_mod.procesar("AABBCCDD")
        t2, _, _ = reader_mod.procesar("11223344")
        assert t1 == "aceptado"
        assert t2 == "aceptado"


# ────────────────────────────────────────────────────────────────────────────
# Modo admin
# ────────────────────────────────────────────────────────────────────────────

class TestModoAdmin:

    def test_modo_admin_inactivo_por_defecto(self, reader_mod):
        assert reader_mod._modo_admin_activo() is False

    def test_modo_admin_activo_con_archivo(self, reader_mod):
        open(reader_mod.ADMIN_FLAG, "w").close()
        assert reader_mod._modo_admin_activo() is True

    def test_notificar_admin_escribe_uid(self, reader_mod, tmp_path):
        reader_mod._notificar_admin_scan("TESTUID1")
        assert os.path.exists(reader_mod.ADMIN_UID_FILE)
        contenido = open(reader_mod.ADMIN_UID_FILE).read()
        assert "TESTUID1" in contenido

    def test_notificar_admin_tiene_timestamp(self, reader_mod):
        reader_mod._notificar_admin_scan("TESTUID2")
        linea = open(reader_mod.ADMIN_UID_FILE).read().strip()
        partes = linea.split("\t")
        assert len(partes) == 2
        # El primer campo debe ser parseable como datetime ISO
        datetime.fromisoformat(partes[0])


# ────────────────────────────────────────────────────────────────────────────
# _escribir_estado()
# ────────────────────────────────────────────────────────────────────────────

class TestEscribirEstado:

    def test_escribe_ok(self, reader_mod):
        reader_mod._escribir_estado("ok")
        contenido = open(reader_mod.STATUS_FILE).read()
        assert "ok" in contenido

    def test_escribe_error(self, reader_mod):
        reader_mod._escribir_estado("error")
        contenido = open(reader_mod.STATUS_FILE).read()
        assert "error" in contenido

    def test_contiene_timestamp(self, reader_mod):
        reader_mod._escribir_estado("reiniciando")
        linea  = open(reader_mod.STATUS_FILE).read().strip()
        partes = linea.split("\t")
        assert len(partes) == 2
        # El segundo campo debe ser un ISO datetime válido
        datetime.fromisoformat(partes[1])


# ────────────────────────────────────────────────────────────────────────────
# cleanup()
# ────────────────────────────────────────────────────────────────────────────

class TestCleanup:

    def test_cleanup_elimina_archivos_de_senal(self, reader_mod):
        # Crear archivos de señal
        for f in (reader_mod.ADMIN_FLAG, reader_mod.ADMIN_UID_FILE,
                  reader_mod.STATUS_FILE):
            open(f, "w").close()

        with pytest.raises(SystemExit):
            reader_mod.cleanup()

        for f in (reader_mod.ADMIN_FLAG, reader_mod.ADMIN_UID_FILE,
                  reader_mod.STATUS_FILE):
            assert not os.path.exists(f), f"Archivo no eliminado: {f}"

    def test_cleanup_no_falla_sin_archivos(self, reader_mod):
        """cleanup() no debe lanzar excepciones si los archivos no existen."""
        with pytest.raises(SystemExit):
            reader_mod.cleanup()


# ────────────────────────────────────────────────────────────────────────────
# leer_uid() con hardware simulado
# ────────────────────────────────────────────────────────────────────────────

class TestLeerUID:

    def test_leer_uid_retorna_none_si_request_falla(self, reader_mod):
        """Si MFRC522_Request no responde MI_OK → None."""
        mock_reader        = MagicMock()
        mock_reader.MI_OK  = 0
        mock_reader.PICC_REQIDL = 0x26
        mock_reader.MFRC522_Request.return_value = (1, None)  # status != MI_OK

        resultado = reader_mod.leer_uid(mock_reader)
        assert resultado is None

    def test_leer_uid_retorna_string_cuando_ok(self, reader_mod):
        """Con bytes de UID válidos → string numérico."""
        mock_reader                            = MagicMock()
        mock_reader.MI_OK                      = 0
        mock_reader.PICC_REQIDL                = 0x26
        mock_reader.MFRC522_Request.return_value = (0, [])
        mock_reader.MFRC522_Anticoll.return_value = (0, [0xAA, 0xBB, 0xCC, 0xDD])

        resultado = reader_mod.leer_uid(mock_reader)
        assert resultado is not None
        assert resultado.isdigit() or resultado.lstrip("-").isdigit()

    def test_leer_uid_retorna_none_si_anticoll_falla(self, reader_mod):
        mock_reader                            = MagicMock()
        mock_reader.MI_OK                      = 0
        mock_reader.PICC_REQIDL                = 0x26
        mock_reader.MFRC522_Request.return_value = (0, [])
        mock_reader.MFRC522_Anticoll.return_value = (1, None)  # falla

        resultado = reader_mod.leer_uid(mock_reader)
        assert resultado is None