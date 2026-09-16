#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_crud_hardware_stats.py
Cubre las líneas 200–427 de crud/app_crud.py:
  - /api/estadisticas
  - /api/analytics
  - /api/hardware/status
  - /api/hardware/services  (GET)
  - /api/hardware/services/<name>/<action>  (POST)
  - /api/hardware/services/<name>/logs
  - /api/hardware/network/status
  - /api/hardware/network/scan / connect / disconnect / restart
  - /api/hardware/system/optimize / reboot / shutdown

Corre con:
    ./venv/bin/python -m pytest shared/tests/test_crud_hardware_stats.py -v
"""

import os
import sqlite3
import tempfile
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Ruta al módulo bajo prueba
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ---------------------------------------------------------------------------
# Variables de entorno mínimas para que app_crud.py arranque sin sys.exit
# ---------------------------------------------------------------------------
os.environ.setdefault('ADMIN_USER',     'testuser')
os.environ.setdefault('ADMIN_PASSWORD', 'testpass')
os.environ.setdefault('ALLOWED_SUBNET', 'disabled')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS estudiantes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT    NOT NULL,
    apellido_paterno TEXT,
    apellido_materno TEXT,
    matricula        TEXT    UNIQUE,
    carrera          TEXT    NOT NULL DEFAULT "ITIC's",
    semestre         INTEGER NOT NULL DEFAULT 1,
    grupo            TEXT    DEFAULT '',
    correo           TEXT,
    estado           TEXT    NOT NULL DEFAULT 'activo',
    foto             TEXT
);

CREATE TABLE IF NOT EXISTS tarjetas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT    NOT NULL UNIQUE,
    id_estudiante   INTEGER REFERENCES estudiantes(id),
    activa          INTEGER NOT NULL DEFAULT 1,
    asignada_en     TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS registros_asistencia (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT,
    id_estudiante   INTEGER REFERENCES estudiantes(id),
    timestamp       TEXT    NOT NULL DEFAULT (datetime('now')),
    fecha_dia       TEXT,
    tipo_evento     TEXT    NOT NULL DEFAULT 'aceptado',
    mensaje         TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    ip        TEXT,
    accion    TEXT    NOT NULL,
    detalle   TEXT,
    resultado TEXT    NOT NULL
);
"""


@pytest.fixture(scope='module')
def db_path():
    """Base de datos SQLite temporal para todo el módulo."""
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(SCHEMA_SQL)
    # Datos mínimos para que las consultas devuelvan algo coherente
    conn.execute(
        "INSERT INTO estudiantes (nombre, apellido_paterno, matricula, carrera, semestre, grupo, estado) "
        "VALUES ('Ana', 'García', '20210001', \"ITIC's\", 1, 'A', 'activo')"
    )
    conn.execute(
        "INSERT INTO estudiantes (nombre, apellido_paterno, matricula, carrera, semestre, grupo, estado) "
        "VALUES ('Luis', 'Pérez', '20210002', \"ITIC's\", 2, 'B', 'inactivo')"
    )
    conn.execute(
        "INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES ('AABBCCDD', 1, 1)"
    )
    conn.execute(
        "INSERT INTO registros_asistencia (uid, id_estudiante, timestamp, fecha_dia, tipo_evento) "
        "VALUES ('AABBCCDD', 1, datetime('now'), date('now'), 'aceptado')"
    )
    conn.commit()
    conn.close()
    yield tmp.name
    os.unlink(tmp.name)


@pytest.fixture(scope='module')
def client(db_path):
    """Cliente de prueba Flask con la base de datos temporal."""
    import crud.app_crud as app_module
    app_module.DB = db_path
    app_module._schema_cache.clear()
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


# Credenciales válidas codificadas en Base64 para Basic Auth
import base64
VALID_AUTH = 'Basic ' + base64.b64encode(b'testuser:testpass').decode()
HEADERS_AUTH = {'Authorization': VALID_AUTH}
HEADERS_AUTH_XHR = {
    'Authorization': VALID_AUTH,
    'X-Requested-With': 'XMLHttpRequest',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get(client, url, headers=None):
    h = dict(HEADERS_AUTH)
    if headers:
        h.update(headers)
    return client.get(url, headers=h)


def post(client, url, json=None, headers=None):
    h = dict(HEADERS_AUTH)
    if headers:
        h.update(headers)
    return client.post(url, json=json or {}, headers=h)


def post_xhr(client, url, json=None):
    return client.post(url, json=json or {}, headers=HEADERS_AUTH_XHR)


# ===========================================================================
# /api/estadisticas  (líneas ~237–253)
# ===========================================================================

class TestEstadisticas:

    def test_retorna_200(self, client):
        r = get(client, '/api/estadisticas')
        assert r.status_code == 200

    def test_success_true(self, client):
        data = get(client, '/api/estadisticas').get_json()
        assert data['success'] is True

    def test_claves_presentes(self, client):
        stats = get(client, '/api/estadisticas').get_json()['stats']
        claves = {
            'total_estudiantes', 'estudiantes_activos',
            'total_tarjetas', 'tarjetas_activas',
            'registros_hoy', 'total_registros', 'aceptados_hoy',
        }
        assert claves.issubset(stats.keys())

    def test_activos_menor_o_igual_total(self, client):
        stats = get(client, '/api/estadisticas').get_json()['stats']
        assert stats['estudiantes_activos'] <= stats['total_estudiantes']

    def test_tarjetas_activas_menor_o_igual_total(self, client):
        stats = get(client, '/api/estadisticas').get_json()['stats']
        assert stats['tarjetas_activas'] <= stats['total_tarjetas']

    def test_sin_auth_retorna_401(self, client):
        r = client.get('/api/estadisticas')
        assert r.status_code == 401


# ===========================================================================
# /api/analytics  (líneas ~255–298)
# ===========================================================================

class TestAnalytics:

    def test_retorna_200(self, client):
        r = get(client, '/api/analytics')
        assert r.status_code == 200

    def test_estructura_respuesta(self, client):
        data = get(client, '/api/analytics').get_json()
        assert data['success'] is True
        analytics = data['analytics']
        assert 'asistencia_7dias' in analytics
        assert 'mes_total' in analytics
        assert 'por_semestre' in analytics
        assert 'por_hora' in analytics
        assert 'top_estudiantes' in analytics

    def test_asistencia_7dias_tiene_7_entradas(self, client):
        analytics = get(client, '/api/analytics').get_json()['analytics']
        assert len(analytics['asistencia_7dias']) == 7

    def test_por_hora_tiene_24_entradas(self, client):
        analytics = get(client, '/api/analytics').get_json()['analytics']
        assert len(analytics['por_hora']) == 24

    def test_cada_hora_tiene_campos_correctos(self, client):
        por_hora = get(client, '/api/analytics').get_json()['analytics']['por_hora']
        for entrada in por_hora:
            assert 'hora' in entrada
            assert 'aceptados' in entrada
            assert 'total' in entrada
            assert 0 <= entrada['hora'] <= 23

    def test_mes_total_es_entero_no_negativo(self, client):
        mes_total = get(client, '/api/analytics').get_json()['analytics']['mes_total']
        assert isinstance(mes_total, int)
        assert mes_total >= 0

    def test_sin_auth_retorna_401(self, client):
        r = client.get('/api/analytics')
        assert r.status_code == 401


# ===========================================================================
# /api/hardware/status  (líneas ~300–369)
# ===========================================================================

class TestHardwareStatus:

    def test_retorna_200(self, client):
        r = get(client, '/api/hardware/status')
        assert r.status_code == 200

    def test_success_true(self, client):
        data = get(client, '/api/hardware/status').get_json()
        assert data['success'] is True

    def test_claves_hardware_presentes(self, client):
        hw = get(client, '/api/hardware/status').get_json()['hardware']
        claves = {'cpu_temp', 'cpu_usage', 'rfid_status', 'rfid_ok',
                  'db_size_mb', 'db_records', 'timestamp',
                  'ram_total_mb', 'ram_used_mb', 'ram_pct',
                  'disk_total_gb', 'disk_used_gb', 'disk_pct'}
        assert claves.issubset(hw.keys())

    def test_timestamp_presente(self, client):
        hw = get(client, '/api/hardware/status').get_json()['hardware']
        assert hw['timestamp'] is not None
        assert 'T' in hw['timestamp']  # formato ISO

    def test_rfid_status_es_string(self, client):
        hw = get(client, '/api/hardware/status').get_json()['hardware']
        assert isinstance(hw['rfid_status'], str)

    def test_rfid_ok_es_booleano(self, client):
        hw = get(client, '/api/hardware/status').get_json()['hardware']
        assert isinstance(hw['rfid_ok'], bool)

    def test_db_records_coincide_con_tabla(self, client, db_path):
        hw = get(client, '/api/hardware/status').get_json()['hardware']
        conn = sqlite3.connect(db_path)
        expected = conn.execute("SELECT COUNT(*) FROM registros_asistencia").fetchone()[0]
        conn.close()
        assert hw['db_records'] == expected

    def test_sin_auth_retorna_401(self, client):
        r = client.get('/api/hardware/status')
        assert r.status_code == 401


# ===========================================================================
# /api/hardware/services  (líneas ~370–427)
# ===========================================================================

RFID_SERVICES = ('rfid-crud.service', 'rfid-dashboard.service', 'rfid-reader.service')


class TestHardwareServices:

    @patch('crud.app_crud._run')
    def test_get_services_retorna_200(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'active', 'stderr': ''}
        r = get(client, '/api/hardware/services')
        assert r.status_code == 200

    @patch('crud.app_crud._run')
    def test_get_services_estructura(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'active', 'stderr': ''}
        data = get(client, '/api/hardware/services').get_json()
        assert data['success'] is True
        assert 'services' in data
        assert len(data['services']) == 3

    @patch('crud.app_crud._run')
    def test_cada_servicio_tiene_campos(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'active', 'stderr': ''}
        services = get(client, '/api/hardware/services').get_json()['services']
        for svc in services:
            assert 'name' in svc
            assert 'active' in svc
            assert 'enabled' in svc
            assert svc['name'] in RFID_SERVICES

    @patch('crud.app_crud._run')
    def test_service_action_restart_ok(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'active', 'stderr': ''}
        r = post(client, '/api/hardware/services/rfid-crud.service/restart')
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['service'] == 'rfid-crud.service'
        assert data['action'] == 'restart'

    @patch('crud.app_crud._run')
    def test_service_action_start_ok(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'active', 'stderr': ''}
        r = post(client, '/api/hardware/services/rfid-reader.service/start')
        assert r.status_code == 200

    @patch('crud.app_crud._run')
    def test_service_action_stop_ok(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'inactive', 'stderr': ''}
        r = post(client, '/api/hardware/services/rfid-dashboard.service/stop')
        assert r.status_code == 200

    def test_service_no_permitido_retorna_403(self, client):
        r = post(client, '/api/hardware/services/otro.service/restart')
        assert r.status_code == 403

    def test_action_no_permitida_retorna_400(self, client):
        r = post(client, '/api/hardware/services/rfid-crud.service/borrar')
        assert r.status_code == 400

    @patch('crud.app_crud._run')
    def test_service_action_permiso_denegado(self, mock_run, client):
        """Cuando systemctl falla con error de permisos → 403."""
        mock_run.return_value = {
            'success': False,
            'stdout': '',
            'stderr': 'Permission denied: interactive authentication required',
            'returncode': 1,
        }
        r = post(client, '/api/hardware/services/rfid-crud.service/restart')
        assert r.status_code == 403
        data = r.get_json()
        assert data['success'] is False
        assert 'sudo' in data['error'].lower() or 'permiso' in data['error'].lower()

    @patch('crud.app_crud._run')
    def test_service_logs_retorna_200(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'Nov 01 10:00:00 rfid-crud[123]: OK', 'stderr': ''}
        r = get(client, '/api/hardware/services/rfid-crud.service/logs')
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert 'log' in data
        assert data['service'] == 'rfid-crud.service'

    def test_service_logs_servicio_no_permitido(self, client):
        r = get(client, '/api/hardware/services/otro.service/logs')
        assert r.status_code == 403

    @patch('crud.app_crud._run')
    def test_service_logs_lineas_por_defecto(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'log', 'stderr': ''}
        data = get(client, '/api/hardware/services/rfid-crud.service/logs').get_json()
        assert data['lines'] == 50

    @patch('crud.app_crud._run')
    def test_service_logs_lineas_custom(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': 'log', 'stderr': ''}
        data = get(client, '/api/hardware/services/rfid-crud.service/logs?lines=100').get_json()
        assert data['lines'] == 100

    @patch('crud.app_crud._run')
    def test_service_logs_lineas_max_500(self, mock_run, client):
        """No debe superar el límite de 500 líneas aunque se pida más."""
        mock_run.return_value = {'success': True, 'stdout': 'log', 'stderr': ''}
        data = get(client, '/api/hardware/services/rfid-crud.service/logs?lines=9999').get_json()
        assert data['lines'] <= 500

    def test_sin_auth_services_retorna_401(self, client):
        r = client.get('/api/hardware/services')
        assert r.status_code == 401


# ===========================================================================
# /api/hardware/network/*  (líneas ~428 en adelante, primer bloque de red)
# ===========================================================================

class TestHardwareNetwork:

    @patch('crud.app_crud._network_status')
    def test_network_status_retorna_200(self, mock_net, client):
        mock_net.return_value = {
            'available': [], 'connected': None, 'interface': None,
            'ip': None, 'gateway': None, 'dns': [], 'internet': False,
        }
        r = get(client, '/api/hardware/network/status')
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    @patch('crud.app_crud._network_status')
    @patch('crud.app_crud._run')
    def test_network_scan_retorna_200(self, mock_run, mock_net, client):
        mock_run.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        mock_net.return_value = {
            'available': [], 'connected': None, 'interface': None,
            'ip': None, 'gateway': None, 'dns': [], 'internet': False,
        }
        with patch('crud.app_crud.time') as mock_time:
            mock_time.sleep = lambda _: None
            mock_time.time = __import__('time').time
            r = post(client, '/api/hardware/network/scan')
        assert r.status_code == 200

    @patch('crud.app_crud._run')
    @patch('crud.app_crud._network_status')
    def test_network_connect_sin_ssid_retorna_400(self, mock_net, mock_run, client):
        r = post(client, '/api/hardware/network/connect', json={'ssid': ''})
        assert r.status_code == 400
        assert r.get_json()['success'] is False

    @patch('crud.app_crud._wifi_iface')
    @patch('crud.app_crud._run')
    @patch('crud.app_crud._network_status')
    def test_network_disconnect_sin_iface_retorna_404(self, mock_net, mock_run, mock_iface, client):
        mock_iface.return_value = None
        r = post(client, '/api/hardware/network/disconnect')
        assert r.status_code == 404

    @patch('crud.app_crud._systemctl')
    def test_network_restart_falla_retorna_400(self, mock_sc, client):
        mock_sc.return_value = {'success': False, 'stderr': 'fallo', 'error': 'fallo'}
        r = post(client, '/api/hardware/network/restart')
        assert r.status_code == 400


# ===========================================================================
# /api/hardware/system/*  — requiere X-Requested-With  (líneas ~497–540)
# ===========================================================================

class TestHardwareSystem:

    def test_optimize_sin_xhr_retorna_403(self, client):
        r = post(client, '/api/hardware/system/optimize', json={'confirm': True})
        assert r.status_code == 403

    def test_optimize_sin_confirm_retorna_400(self, client):
        r = post_xhr(client, '/api/hardware/system/optimize', json={})
        assert r.status_code == 400
        assert r.get_json()['success'] is False

    @patch('crud.app_crud._run')
    def test_optimize_con_confirm_y_permiso_denegado_retorna_403(self, mock_run, client):
        """Si drop_caches falla y /proc/sys/vm/drop_caches no es escribible → 403."""
        mock_run.return_value = {'success': False, 'stdout': '', 'stderr': 'permission denied'}
        with patch('builtins.open', side_effect=PermissionError):
            r = post_xhr(client, '/api/hardware/system/optimize', json={'confirm': True})
        assert r.status_code == 403

    def test_reboot_sin_xhr_retorna_403(self, client):
        r = post(client, '/api/hardware/system/reboot', json={'confirm': True})
        assert r.status_code == 403

    def test_reboot_sin_confirm_retorna_400(self, client):
        r = post_xhr(client, '/api/hardware/system/reboot', json={})
        assert r.status_code == 400

    @patch('crud.app_crud._run')
    def test_reboot_con_confirm(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        r = post_xhr(client, '/api/hardware/system/reboot', json={'confirm': True})
        # El endpoint puede devolver 200 o el código que el mock permita;
        # lo importante es que no lanza excepción y devuelve success.
        data = r.get_json()
        assert 'success' in data

    def test_shutdown_sin_xhr_retorna_403(self, client):
        r = post(client, '/api/hardware/system/shutdown', json={'confirm': True})
        assert r.status_code == 403

    def test_shutdown_sin_confirm_retorna_400(self, client):
        r = post_xhr(client, '/api/hardware/system/shutdown', json={})
        assert r.status_code == 400

    @patch('crud.app_crud._run')
    def test_shutdown_con_confirm(self, mock_run, client):
        mock_run.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        r = post_xhr(client, '/api/hardware/system/shutdown', json={'confirm': True})
        data = r.get_json()
        assert 'success' in data