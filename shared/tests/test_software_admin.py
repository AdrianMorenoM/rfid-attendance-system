#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_software_admin.py
Pruebas unitarias para crud/rfid_software_admin.py.

Cubre las líneas 54–86 (funciones de shell/SSH) y las clases
ServiceManager y DatabaseManager.

Corre con:
    ./venv/bin/python -m pytest shared/tests/test_software_admin.py -v
"""

import os
import re
import sqlite3
import tempfile
import shutil
import sys
import pytest
from unittest.mock import patch, MagicMock, call

# ---------------------------------------------------------------------------
# Asegurar que el módulo se importa en modo LOCAL (sin SSH)
# ---------------------------------------------------------------------------
os.environ.setdefault('RFID_USE_SSH',      'false')
os.environ.setdefault('RFID_SSH_HOST',     '127.0.0.1')
os.environ.setdefault('RFID_SSH_PASSWORD', '')   # no necesaria en modo local

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import crud.rfid_software_admin as adm


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture()
def tmp_db(tmp_path):
    """Base de datos SQLite temporal con el esquema mínimo."""
    db = tmp_path / 'rfid.db'
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE estudiantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT, apellido_paterno TEXT, matricula TEXT UNIQUE,
            carrera TEXT DEFAULT "ITIC's", semestre INTEGER DEFAULT 1,
            grupo TEXT DEFAULT '', estado TEXT DEFAULT 'activo'
        );
        CREATE TABLE tarjetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE, id_estudiante INTEGER, activa INTEGER DEFAULT 1,
            asignada_en TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE registros_asistencia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT, id_estudiante INTEGER,
            timestamp TEXT DEFAULT (datetime('now')),
            fecha_dia TEXT, tipo_evento TEXT DEFAULT 'aceptado',
            mensaje TEXT
        );
    """)
    conn.execute("INSERT INTO estudiantes (nombre, matricula, carrera) VALUES ('Ana', 'M001', \"ITIC's\")")
    conn.execute("INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES ('AABBCCDD', 1, 1)")
    conn.execute("INSERT INTO registros_asistencia (uid, id_estudiante, fecha_dia, tipo_evento) VALUES ('AABBCCDD', 1, date('now'), 'aceptado')")
    conn.commit()
    conn.close()
    return str(db)


@pytest.fixture()
def backup_dir(tmp_path):
    d = tmp_path / 'backups'
    d.mkdir()
    return str(d)


@pytest.fixture()
def db_manager(tmp_db, backup_dir):
    return adm.DatabaseManager(tmp_db, backup_dir)


# ===========================================================================
# _run_local  (líneas 54–65)
# ===========================================================================

class TestRunLocal:

    def test_comando_exitoso(self):
        r = adm._run_local('echo hola')
        assert r['success'] is True
        assert r['stdout'] == 'hola'
        assert r['mode'] == 'local'

    def test_comando_fallido_retorna_success_false(self):
        r = adm._run_local('false')
        assert r['success'] is False
        assert r['returncode'] != 0

    def test_comando_inexistente_retorna_success_false(self):
        r = adm._run_local('comando_que_no_existe_xyzxyz')
        assert r['success'] is False

    def test_stdout_strip(self):
        r = adm._run_local('printf "  texto  "')
        assert r['stdout'] == 'texto'

    def test_timeout_retorna_error(self):
        r = adm._run_local('sleep 10', timeout=1)
        assert r['success'] is False

    def test_returncode_presente(self):
        r = adm._run_local('exit 42', timeout=5)
        assert 'returncode' in r


# ===========================================================================
# run_shell  (línea 83 — delega a _run_local en modo local)
# ===========================================================================

class TestRunShell:

    def test_delega_a_run_local_en_modo_local(self):
        with patch.object(adm, '_should_use_ssh', return_value=False), \
             patch.object(adm, '_run_local', return_value={'success': True, 'stdout': 'ok'}) as mock_local:
            result = adm.run_shell('echo ok')
        mock_local.assert_called_once_with('echo ok', timeout=30)
        assert result['success'] is True

    def test_delega_a_run_ssh_cuando_ssh_activo(self):
        with patch.object(adm, '_should_use_ssh', return_value=True), \
             patch.object(adm, '_run_ssh', return_value={'success': True, 'stdout': 'remoto'}) as mock_ssh:
            result = adm.run_shell('ls', timeout=10)
        mock_ssh.assert_called_once_with('ls', timeout=10)
        assert result['stdout'] == 'remoto'


# ===========================================================================
# run_systemctl  (líneas 87–97)
# ===========================================================================

class TestRunSystemctl:

    def test_llama_a_run_shell_con_accion_y_servicio(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': ''}) as mock_shell:
            adm.run_systemctl('restart', 'rfid-crud.service')
        # Debe haber llamado con la acción y el servicio correctamente citados
        first_call = mock_shell.call_args_list[0]
        cmd = first_call[0][0]
        assert 'systemctl' in cmd
        assert 'restart' in cmd
        assert 'rfid-crud.service' in cmd

    def test_intenta_sudo_si_falla_primer_intento(self):
        respuestas = [
            {'success': False, 'stdout': '', 'stderr': 'permission denied'},
            {'success': True,  'stdout': '', 'stderr': ''},
        ]
        with patch.object(adm, 'run_shell', side_effect=respuestas) as mock_shell:
            result = adm.run_systemctl('start', 'rfid-reader.service')
        assert mock_shell.call_count == 2
        second_cmd = mock_shell.call_args_list[1][0][0]
        assert 'sudo' in second_cmd

    def test_retorna_resultado_exitoso_directo(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': 'active'}):
            result = adm.run_systemctl('is-active', 'rfid-crud.service')
        assert result['success'] is True


# ===========================================================================
# service_active / service_enabled / service_logs  (líneas 99–111)
# ===========================================================================

class TestServiceHelpers:

    def test_service_active_true_cuando_stdout_es_active(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': 'active'}):
            assert adm.service_active('rfid-crud.service') is True

    def test_service_active_false_cuando_stdout_es_inactive(self):
        with patch.object(adm, 'run_shell', return_value={'success': False, 'stdout': 'inactive'}):
            assert adm.service_active('rfid-crud.service') is False

    def test_service_enabled_true_para_enabled(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': 'enabled'}):
            assert adm.service_enabled('rfid-crud.service') is True

    def test_service_enabled_true_para_static(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': 'static'}):
            assert adm.service_enabled('rfid-crud.service') is True

    def test_service_enabled_false_para_disabled(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': 'disabled'}):
            assert adm.service_enabled('rfid-crud.service') is False

    def test_service_logs_llama_journalctl(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': 'log output'}) as mock_shell:
            result = adm.service_logs('rfid-crud.service', lines=20)
        cmd = mock_shell.call_args[0][0]
        assert 'journalctl' in cmd
        assert 'rfid-crud.service' in cmd
        assert result['stdout'] == 'log output'

    def test_service_logs_clampea_minimo_10(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': ''}) as mock_shell:
            adm.service_logs('rfid-crud.service', lines=1)
        cmd = mock_shell.call_args[0][0]
        # El número en el comando debe ser al menos 10
        numeros = re.findall(r'\b(\d+)\b', cmd)
        assert any(int(n) >= 10 for n in numeros)

    def test_service_logs_clampea_maximo_500(self):
        with patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': ''}) as mock_shell:
            adm.service_logs('rfid-crud.service', lines=9999)
        cmd = mock_shell.call_args[0][0]
        numeros = re.findall(r'\b(\d+)\b', cmd)
        assert all(int(n) <= 500 for n in numeros)


# ===========================================================================
# ServiceManager  (líneas 155–217)
# ===========================================================================

class TestServiceManager:

    @pytest.fixture()
    def manager(self):
        return adm.ServiceManager()

    def _mock_shell(self, stdout='active'):
        return patch.object(adm, 'run_shell', return_value={'success': True, 'stdout': stdout, 'stderr': ''})

    def test_list_services_devuelve_tres_servicios(self, manager):
        with self._mock_shell('active'):
            servicios = manager.list_services()
        assert len(servicios) == 3
        nombres = {s['name'] for s in servicios}
        assert nombres == set(adm.RFID_SERVICES)

    def test_list_services_activo_true_cuando_active(self, manager):
        with self._mock_shell('active'):
            servicios = manager.list_services()
        assert all(s['active'] for s in servicios)

    def test_list_services_activo_false_cuando_inactive(self, manager):
        with self._mock_shell('inactive'):
            servicios = manager.list_services()
        assert all(not s['active'] for s in servicios)

    def test_action_servicio_no_permitido(self, manager):
        result = manager.action('otro.service', 'restart')
        assert result['success'] is False
        assert 'no permitido' in result['error'].lower()

    def test_action_accion_no_permitida(self, manager):
        result = manager.action('rfid-crud.service', 'borrar')
        assert result['success'] is False
        assert 'no permitida' in result['error'].lower()

    def test_action_restart_exitoso(self, manager):
        with self._mock_shell('active'):
            result = manager.action('rfid-crud.service', 'restart')
        assert result['success'] is True

    def test_action_permiso_denegado_retorna_error(self, manager):
        with patch.object(adm, 'run_shell', return_value={
            'success': False, 'stdout': '', 'stderr': 'permission denied'
        }):
            result = manager.action('rfid-crud.service', 'restart')
        assert result['success'] is False
        assert 'permiso' in result['error'].lower()

    def test_action_enable_con_symlink_en_stderr_retorna_ok(self, manager):
        """enable puede fallar el returncode pero crear el symlink → debe ser success."""
        with patch.object(adm, 'run_shell', return_value={
            'success': False, 'stdout': '', 'stderr': 'Created symlink /etc/systemd/...'
        }):
            result = manager.action('rfid-crud.service', 'enable')
        assert result['success'] is True

    def test_logs_servicio_no_permitido(self, manager):
        result = manager.logs('otro.service')
        assert result['success'] is False

    def test_logs_retorna_estructura_correcta(self, manager):
        with self._mock_shell('log line 1\nlog line 2'):
            result = manager.logs('rfid-crud.service', lines=10)
        assert result['success'] is True
        assert result['service'] == 'rfid-crud.service'
        assert result['lines'] == 10
        assert 'log' in result


# ===========================================================================
# DatabaseManager.status  (líneas ~220–238)
# ===========================================================================

class TestDatabaseManagerStatus:

    def test_status_retorna_claves_esperadas(self, db_manager):
        s = db_manager.status()
        assert 'db_path'      in s
        assert 'db_size_mb'   in s
        assert 'counts'       in s
        assert 'backups_count' in s

    def test_status_counts_son_enteros_no_negativos(self, db_manager):
        counts = db_manager.status()['counts']
        assert counts['estudiantes'] >= 0
        assert counts['tarjetas']    >= 0
        assert counts['registros']   >= 0

    def test_status_con_datos_fixture(self, db_manager):
        counts = db_manager.status()['counts']
        assert counts['estudiantes'] == 1
        assert counts['tarjetas']    == 1
        assert counts['registros']   == 1


# ===========================================================================
# DatabaseManager.create_backup / list_backups / delete_backup  (líneas ~264–305)
# ===========================================================================

class TestDatabaseManagerBackup:

    def test_create_backup_retorna_success(self, db_manager):
        result = db_manager.create_backup()
        assert result['success'] is True

    def test_create_backup_genera_archivo(self, db_manager, backup_dir):
        result = db_manager.create_backup()
        assert os.path.isfile(os.path.join(backup_dir, result['filename']))

    def test_create_backup_nombre_formato_correcto(self, db_manager):
        result = db_manager.create_backup()
        assert adm.SAFE_BACKUP_RE.match(result['filename'])

    def test_create_backup_size_mb_presente(self, db_manager):
        result = db_manager.create_backup()
        assert isinstance(result['size_mb'], float)

    def test_list_backups_vacio_al_inicio(self, backup_dir, tmp_db):
        mgr = adm.DatabaseManager(tmp_db, backup_dir)
        # backup_dir vacío
        for f in os.listdir(backup_dir):
            os.remove(os.path.join(backup_dir, f))
        assert mgr.list_backups() == []

    def test_list_backups_detecta_backup_creado(self, db_manager):
        db_manager.create_backup()
        backups = db_manager.list_backups()
        assert len(backups) >= 1
        assert 'filename' in backups[0]
        assert 'size_mb'  in backups[0]
        assert 'created_at' in backups[0]

    def test_list_backups_ignora_archivos_sin_patron(self, db_manager, backup_dir):
        # Crear archivo con nombre inválido
        open(os.path.join(backup_dir, 'no_es_backup.db'), 'w').close()
        backups = db_manager.list_backups()
        nombres = [b['filename'] for b in backups]
        assert 'no_es_backup.db' not in nombres

    def test_delete_backup_elimina_archivo(self, db_manager, backup_dir):
        r = db_manager.create_backup()
        filename = r['filename']
        result = db_manager.delete_backup(filename)
        assert result['success'] is True
        assert not os.path.isfile(os.path.join(backup_dir, filename))

    def test_delete_backup_inexistente_retorna_error(self, db_manager):
        result = db_manager.delete_backup('rfid_backup_20000101_000000.db')
        assert result['success'] is False
        assert 'no encontrado' in result['error'].lower()

    def test_backup_path_nombre_invalido_lanza_valueerror(self, db_manager):
        with pytest.raises(ValueError):
            db_manager._backup_path('../../etc/passwd')

    def test_backup_path_nombre_valido_retorna_ruta(self, db_manager, backup_dir):
        path = db_manager._backup_path('rfid_backup_20240101_120000.db')
        assert path.startswith(backup_dir)


# ===========================================================================
# DatabaseManager.restore  (líneas ~307–325)
# ===========================================================================

class TestDatabaseManagerRestore:

    def test_restore_desde_backup_valido(self, db_manager):
        backup = db_manager.create_backup()
        result = db_manager.restore(backup['filename'])
        assert result['success'] is True
        assert 'safety_backup' in result

    def test_restore_crea_safety_backup(self, db_manager, backup_dir):
        backup = db_manager.create_backup()
        result = db_manager.restore(backup['filename'])
        # El safety_backup debe existir físicamente en disco
        safety = result.get('safety_backup')
        assert safety is not None
        assert os.path.isfile(os.path.join(backup_dir, safety))

    def test_restore_archivo_inexistente_retorna_error(self, db_manager):
        result = db_manager.restore('rfid_backup_20000101_000000.db')
        assert result['success'] is False
        assert 'no encontrado' in result['error'].lower()


# ===========================================================================
# DatabaseManager.purge_preview / purge  (líneas ~326–416)
# ===========================================================================

class TestDatabaseManagerPurge:

    def test_purge_preview_registros_sin_filtros(self, db_manager):
        result = db_manager.purge_preview({})
        assert result['success'] is True
        assert result['count'] >= 1

    def test_purge_preview_target_invalido(self, db_manager):
        result = db_manager.purge_preview({'target': 'otro'})
        assert result['success'] is False
        assert 'target' in result['error'].lower()

    def test_purge_preview_estudiantes(self, db_manager):
        result = db_manager.purge_preview({'target': 'estudiantes'})
        assert result['success'] is True
        assert result['count'] >= 1

    def test_purge_preview_tarjetas(self, db_manager):
        result = db_manager.purge_preview({'target': 'tarjetas'})
        assert result['success'] is True
        assert result['count'] >= 1

    def test_purge_sin_confirmar_retorna_error(self, db_manager):
        result = db_manager.purge({'target': 'registros'})
        assert result['success'] is False
        assert 'confirmacion' in result['error'].lower()

    def test_purge_registros_con_confirmar(self, db_manager):
        result = db_manager.purge({'confirm': True, 'target': 'registros'})
        assert result['success'] is True
        assert result['deleted'] >= 1

    def test_purge_sin_resultados_devuelve_deleted_0(self, db_manager):
        """Filtro que no coincide con nada → deleted=0, success=True."""
        result = db_manager.purge({
            'confirm': True,
            'target': 'registros',
            'matricula': 'MATRICULA_QUE_NO_EXISTE_XYZXYZ',
        })
        assert result['success'] is True
        assert result['deleted'] == 0

    def test_purge_filtro_fecha_desde(self, db_manager):
        result = db_manager.purge_preview({'fecha_desde': '2000-01-01'})
        assert result['success'] is True
        assert result['count'] >= 1

    def test_purge_filtro_fecha_hasta_pasado(self, db_manager):
        """Registros antes del año 2000 → debe ser 0."""
        result = db_manager.purge_preview({'fecha_hasta': '1999-12-31'})
        assert result['success'] is True
        assert result['count'] == 0

    def test_purge_estudiantes_con_cascade(self, db_manager, tmp_db):
        """Purgar estudiantes debe eliminar sus registros y tarjetas en cascada."""
        conn = sqlite3.connect(tmp_db)
        before_reg = conn.execute("SELECT COUNT(*) FROM registros_asistencia").fetchone()[0]
        before_tar = conn.execute("SELECT COUNT(*) FROM tarjetas").fetchone()[0]
        conn.close()
        assert before_reg >= 1
        assert before_tar >= 1

        result = db_manager.purge({'confirm': True, 'target': 'estudiantes'})
        assert result['success'] is True

        conn = sqlite3.connect(tmp_db)
        after_reg = conn.execute("SELECT COUNT(*) FROM registros_asistencia").fetchone()[0]
        after_tar = conn.execute("SELECT COUNT(*) FROM tarjetas").fetchone()[0]
        conn.close()
        assert after_reg < before_reg
        assert after_tar < before_tar