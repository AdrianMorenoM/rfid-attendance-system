"""
test_xhr_protection.py — Blindaje CSRF: todas las rutas mutadoras
deben devolver 403 cuando falta el header X-Requested-With.

Si alguien agrega una ruta POST/PUT/DELETE nueva sin @require_xhr_header,
este test lo detecta en CI antes de que llegue a producción.

Corre con:
    cd ~/rfid-system
    ./venv/bin/python -m pytest shared/tests/test_xhr_protection.py -v
"""

import base64
import pytest
from conftest import basic_auth_headers


# ---------------------------------------------------------------------------
# Headers: con autenticación correcta pero SIN X-Requested-With
# ---------------------------------------------------------------------------

def _auth_sin_xhr(user="admin", password="test-admin-password") -> dict:
    """Basic Auth válido, sin el header que activa la protección CSRF."""
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# ---------------------------------------------------------------------------
# Lista canónica de rutas mutadoras con un ejemplo de URL concreta.
# Cuando la ruta tiene parámetros de path se usan valores que existen en
# el fixture (estudiante id=1, tarjeta id=1) o valores genéricos que
# hacen llegar la petición al decorador antes de que Flask rechace el path.
# ---------------------------------------------------------------------------

RUTAS_MUTADORAS = [
    # método, url concreta
    ("POST",   "/api/hardware/services/rfid-reader.service/restart"),
    ("POST",   "/api/hardware/network/scan"),
    ("POST",   "/api/hardware/network/connect"),
    ("POST",   "/api/hardware/network/disconnect"),
    ("POST",   "/api/hardware/network/restart"),
    ("POST",   "/api/hardware/system/optimize"),
    ("POST",   "/api/hardware/system/reboot"),
    ("POST",   "/api/hardware/system/shutdown"),
    ("POST",   "/api/software/services/rfid-reader.service/restart"),
    ("POST",   "/api/software/database/backup"),
    ("POST",   "/api/software/database/restore"),
    ("DELETE", "/api/software/database/backups/rfid_backup_20200101_000000.db"),
    ("POST",   "/api/software/database/purge/preview"),
    ("POST",   "/api/software/database/purge"),
    ("POST",   "/api/rfid/listen/start"),
    ("POST",   "/api/rfid/listen/stop"),
    ("POST",   "/api/rfid/listen/capture"),
    ("POST",   "/api/rfid/admin-scan/start"),
    ("POST",   "/api/rfid/admin-scan/stop"),
    ("POST",   "/api/rfid/admin-scan/guardar"),
    ("POST",   "/api/rfid/admin-scan/eliminar"),
    ("POST",   "/api/rfid/guardar-uid"),
    ("POST",   "/api/estudiantes"),
    ("PUT",    "/api/estudiantes/1"),
    ("DELETE", "/api/estudiantes/1"),
    ("POST",   "/api/estudiantes/promover"),
    ("POST",   "/api/estudiantes/baja-masiva"),
    ("POST",   "/api/estudiantes/alta-masiva"),
    ("POST",   "/api/tarjetas"),
    ("PUT",    "/api/tarjetas/1"),
    ("DELETE", "/api/tarjetas/1"),
    ("POST",   "/api/tarjetas/bulk-toggle"),
    ("POST",   "/api/upload-foto"),
    ("POST",   "/api/migrate"),
]


# ---------------------------------------------------------------------------
# Test parametrizado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,url", RUTAS_MUTADORAS)
def test_ruta_mutadora_requiere_xhr(crud_app, method, url):
    """
    Cada ruta POST/PUT/DELETE debe devolver 403 cuando la petición no
    lleva el header X-Requested-With: XMLHttpRequest, independientemente
    de que las credenciales Basic Auth sean correctas.
    """
    client, _ = crud_app
    headers = _auth_sin_xhr()

    response = getattr(client, method.lower())(url, headers=headers, json={})

    assert response.status_code == 403, (
        f"{method} {url} devolvió {response.status_code} en lugar de 403. "
        f"¿Falta el decorador @require_xhr_header?"
    )