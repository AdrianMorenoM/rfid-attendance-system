"""
test_smoke.py — smoke tests contra los servicios reales.

IMPORTANTE: este archivo requiere que los servicios estén activos:
    systemctl is-active rfid-crud.service
    systemctl is-active rfid-dashboard.service

Si los servicios están caídos, todos los tests se marcan como SKIP.

Ejecutar solo los smoke tests:
    cd ~/rfid-system
    source venv/bin/activate
    pytest shared/tests/test_smoke.py -v

Ejecutar toda la suite incluyendo smoke:
    pytest shared/tests/ -v --tb=short
"""
import os, json, base64, pytest
import urllib.request, urllib.error

# ── Configuración ────────────────────────────────────────────────────────────
CRUD_BASE      = os.environ.get("RFID_CRUD_URL",      "http://localhost:5001")
DASH_BASE      = os.environ.get("RFID_DASH_URL",      "http://localhost:5000")
ADMIN_USER     = os.environ.get("ADMIN_USER",          "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD",      "changeme")
TIMEOUT        = int(os.environ.get("RFID_SMOKE_TIMEOUT", "5"))


def _b64(user, pwd):
    return base64.b64encode(f"{user}:{pwd}".encode()).decode()

_AUTH_HEADER = {
    "Authorization":    f"Basic {_b64(ADMIN_USER, ADMIN_PASSWORD)}",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type":     "application/json",
}


def _get(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)


def _post(url, body=None, headers=None, timeout=TIMEOUT):
    data = json.dumps(body or {}).encode()
    h    = {**(headers or {}), "Content-Type": "application/json"}
    req  = urllib.request.Request(url, data=data, headers=h, method="POST")
    return urllib.request.urlopen(req, timeout=timeout)


def _is_up(base_url) -> bool:
    try:
        urllib.request.urlopen(base_url, timeout=2)
        return True
    except Exception:
        return False


# ── Marcadores de skip si el servicio está caído ─────────────────────────────
crud_up  = pytest.mark.skipif(not _is_up(CRUD_BASE),  reason="rfid-crud no disponible")
dash_up  = pytest.mark.skipif(not _is_up(DASH_BASE),  reason="rfid-dashboard no disponible")


# ────────────────────────────────────────────────────────────────────────────
# Smoke: CRUD service
# ────────────────────────────────────────────────────────────────────────────

class TestSmokeCRUD:

    @crud_up
    def test_salud_db(self):
        resp = _get(f"{CRUD_BASE}/api/health/db", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        assert data["healthy"] is True

    @crud_up
    def test_estadisticas_responde(self):
        resp = _get(f"{CRUD_BASE}/api/estadisticas", _AUTH_HEADER)
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["success"]
        assert "stats" in data

    @crud_up
    def test_listado_estudiantes(self):
        resp = _get(f"{CRUD_BASE}/api/estudiantes", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        assert isinstance(data["estudiantes"], list)

    @crud_up
    def test_listado_tarjetas(self):
        resp = _get(f"{CRUD_BASE}/api/tarjetas", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]

    @crud_up
    def test_sin_credenciales_retorna_401(self):
        try:
            _get(f"{CRUD_BASE}/api/estadisticas")
            pytest.fail("Debería haber lanzado HTTPError 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401

    @crud_up
    def test_crear_y_eliminar_estudiante(self):
        """Flujo completo: crear → verificar → eliminar."""
        payload = {
            "nombre":           "Test",
            "apellido_paterno": "Smoke",
            "matricula":        f"SMOKE{os.getpid()}",
            "semestre":         1,
            "grupo":            "Z",
        }
        # Crear
        resp = _post(f"{CRUD_BASE}/api/estudiantes", payload, _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        est_id = data["id"]

        # Verificar
        resp2 = _get(f"{CRUD_BASE}/api/estudiantes/{est_id}", _AUTH_HEADER)
        data2 = json.loads(resp2.read())
        assert data2["estudiante"]["nombre"] == "Test"

        # Eliminar
        req = urllib.request.Request(
            f"{CRUD_BASE}/api/estudiantes/{est_id}",
            headers=_AUTH_HEADER,
            method="DELETE"
        )
        resp3 = urllib.request.urlopen(req, timeout=TIMEOUT)
        data3 = json.loads(resp3.read())
        assert data3["success"]

    @crud_up
    def test_backup_y_listado(self):
        resp = _post(f"{CRUD_BASE}/api/software/database/backup",
                     {}, _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        fname = data["filename"]

        resp2 = _get(f"{CRUD_BASE}/api/software/database/backups", _AUTH_HEADER)
        data2 = json.loads(resp2.read())
        nombres = [b["filename"] for b in data2["backups"]]
        assert fname in nombres

    @crud_up
    def test_analytics_7_dias(self):
        resp = _get(f"{CRUD_BASE}/api/analytics", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        assert len(data["analytics"]["asistencia_7dias"]) == 7

    @crud_up
    def test_hardware_status(self):
        resp = _get(f"{CRUD_BASE}/api/hardware/status", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        hw = data["hardware"]
        assert "cpu_usage"  in hw
        assert "ram_pct"    in hw
        assert "disk_pct"   in hw
        assert "uptime_s"   in hw

    @crud_up
    def test_network_status(self):
        resp = _get(f"{CRUD_BASE}/api/hardware/network/status", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        assert "network" in data

    @crud_up
    def test_export_csv_estudiantes_encoding(self):
        """El CSV debe comenzar con BOM UTF-8 y tener cabecera."""
        req  = urllib.request.Request(
            f"{CRUD_BASE}/api/export/estudiantes", headers=_AUTH_HEADER
        )
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        raw  = resp.read()
        # BOM UTF-8: EF BB BF
        assert raw[:3] == b"\xef\xbb\xbf", "Falta BOM UTF-8"
        text = raw.decode("utf-8-sig")
        primera_linea = text.splitlines()[0]
        assert "Nombre" in primera_linea or "nombre" in primera_linea.lower()

    @crud_up
    def test_audit_log_accesible(self):
        resp = _get(f"{CRUD_BASE}/api/audit-log", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]

    @crud_up
    def test_servicios_listados(self):
        resp = _get(f"{CRUD_BASE}/api/hardware/services", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        nombres = [s["name"] for s in data["services"]]
        assert "rfid-reader.service"    in nombres
        assert "rfid-crud.service"      in nombres
        assert "rfid-dashboard.service" in nombres

    @crud_up
    def test_rfid_desconocidos(self):
        resp = _get(f"{CRUD_BASE}/api/rfid/desconocidos", _AUTH_HEADER)
        data = json.loads(resp.read())
        assert data["success"]
        assert isinstance(data["desconocidos"], list)


# ────────────────────────────────────────────────────────────────────────────
# Smoke: Dashboard service
# ────────────────────────────────────────────────────────────────────────────

class TestSmokeDashboard:

    @dash_up
    def test_pagina_principal_responde(self):
        resp = _get(DASH_BASE)
        assert resp.status == 200

    @dash_up
    def test_api_estado_responde(self):
        resp = _get(f"{DASH_BASE}/api/estado")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["success"]

    @dash_up
    def test_api_estado_tiene_hourly_24(self):
        resp = _get(f"{DASH_BASE}/api/estado")
        data = json.loads(resp.read())
        assert len(data["hourly"]) == 24

    @dash_up
    def test_api_ultimo_evento_responde(self):
        resp = _get(f"{DASH_BASE}/api/ultimo-evento")
        data = json.loads(resp.read())
        assert data["success"]
        # evento puede ser None si no hay registros hoy

    @dash_up
    def test_dashboard_ruta_alternativa(self):
        resp = _get(f"{DASH_BASE}/dashboard")
        assert resp.status == 200


# ────────────────────────────────────────────────────────────────────────────
# Prueba de concurrencia mínima (opcional, ~2s)
# ────────────────────────────────────────────────────────────────────────────

@crud_up
def test_concurrencia_estadisticas():
    """10 peticiones concurrentes a /api/estadisticas deben responder todas."""
    import threading

    resultados = []

    def pedir():
        try:
            resp = _get(f"{CRUD_BASE}/api/estadisticas", _AUTH_HEADER, timeout=10)
            data = json.loads(resp.read())
            resultados.append(data["success"])
        except Exception as e:
            resultados.append(False)

    hilos = [threading.Thread(target=pedir) for _ in range(10)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=15)

    assert len(resultados) == 10
    assert all(resultados), f"Fallos: {resultados.count(False)}/10"