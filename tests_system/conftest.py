"""conftest.py — fixtures de la suite de SISTEMA (tests_system/).

Dos mundos:
  · En proceso: apps Flask + lector importados con una BD temporal y subprocess/os.system
    bloqueados (nada toca la Pi real). Es lo que corre siempre.
  · En vivo ("live"): pruebas contra los servicios reales, de solo lectura salvo las
    marcadas "destructive" (requieren --destructive).
"""
import gc
import importlib
import logging
import os
import sqlite3
import subprocess
import sys
import types
import weakref
from unittest import mock

import pytest
import requests

import syslib

for _p in (syslib.SHARED, syslib.CRUD_DIR, syslib.DASH_DIR, syslib.ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ── Opciones de línea de comandos ────────────────────────────────────────────
def pytest_addoption(parser):
    g = parser.getgroup("rfid-system")
    g.addoption("--no-live", action="store_true", help="omite pruebas contra servicios reales")
    g.addoption("--destructive", action="store_true",
                help="permite reinicios, kill -9 y bloqueos de BD en el sistema real")
    g.addoption("--hardware", action="store_true", help="permite pruebas con el lector RC522 real")


def pytest_collection_modifyitems(config, items):
    reglas = [("live", config.getoption("--no-live"), "omitido por --no-live", True),
              ("destructive", not config.getoption("--destructive"), "requiere --destructive", False),
              ("hardware", not config.getoption("--hardware"), "requiere --hardware", False)]
    for item in items:
        for marca, condicion, motivo, _ in reglas:
            if item.get_closest_marker(marca) and condicion:
                item.add_marker(pytest.mark.skip(reason=motivo))


# ── En proceso ───────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_db(tmp_path):
    path = str(tmp_path / "rfid_sys.db")
    syslib.build_db(path)
    return path


@pytest.fixture
def guard(monkeypatch):
    """Bloquea subprocess/os.system: ningún test en proceso puede reiniciar, apagar ni ejecutar nada."""
    calls = []

    def out(kw):
        return "" if (kw.get("text") or kw.get("universal_newlines") or kw.get("encoding")) else b""

    def fake_run(cmd, *a, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, out(kw), out(kw))

    def fake_out(cmd, *a, **kw):
        calls.append(cmd)
        return out(kw)

    def fake_code(cmd, *a, **kw):
        calls.append(cmd)
        return 0

    def fake_popen(cmd, *a, **kw):
        calls.append(cmd)
        m = mock.MagicMock()
        m.returncode, m.pid = 0, 1
        m.poll.return_value = m.wait.return_value = 0
        m.communicate.return_value = (out(kw), out(kw))
        return m

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "check_output", fake_out)
    monkeypatch.setattr(subprocess, "getoutput", lambda *a, **k: "")
    monkeypatch.setattr(subprocess, "check_call", fake_code)
    monkeypatch.setattr(subprocess, "call", fake_code)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(os, "system", lambda c: (calls.append(c), 0)[1])
    monkeypatch.setattr(os, "popen", lambda c, *a, **k: (calls.append(c), mock.MagicMock())[1])
    return types.SimpleNamespace(calls=calls)


def _importar(nombre):
    for n in (nombre, f"{'crud' if nombre == 'app_crud' else 'dashboard'}.{nombre}"):
        sys.modules.pop(n, None)
    return importlib.import_module(nombre)


@pytest.fixture
def crud_app(guard, tmp_db, monkeypatch, tmp_path):
    for k, v in dict(ADMIN_USER="admin", ADMIN_PASSWORD=syslib.TEST_PWD,
                     ALLOWED_SUBNET="disabled", ALLOW_HTTP_MIGRATIONS="true").items():
        monkeypatch.setenv(k, v)
    m = _importar("app_crud")
    m.BASIC_AUTH_USER, m.BASIC_AUTH_PASSWORD = "admin", syslib.TEST_PWD
    m.DB = tmp_db
    m.BACKUP_DIR = str(tmp_path / "backups")
    os.makedirs(m.BACKUP_DIR, exist_ok=True)
    m._schema_cache.clear()
    m._ensure_auth_fail_table()
    try:
        m._AUTH_FAIL_STORAGE.reset()
    except Exception:
        pass
    m.app.config["TESTING"] = True
    m.app.config["PROPAGATE_EXCEPTIONS"] = False  # como en producción: un error no controlado es un 500, no una excepción
    with m.app.test_client() as client:
        yield client, m


@pytest.fixture
def dash_app(guard, tmp_db, monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", syslib.TEST_PWD)
    m = _importar("app_dashboard")
    m.DB = tmp_db
    m._schema.clear()
    m.BASIC_AUTH_USER, m.BASIC_AUTH_PASSWORD = "admin", syslib.TEST_PWD
    m.app.config["TESTING"] = True
    m.app.config["PROPAGATE_EXCEPTIONS"] = False
    with m.app.test_client() as client:
        client.environ_base["HTTP_AUTHORIZATION"] = syslib.basic_header("admin", syslib.TEST_PWD)
        yield client, m


@pytest.fixture
def reader(tmp_db, tmp_path, monkeypatch):
    """Módulo shared/rfid_reader.py apuntando a la BD temporal (sin hardware, sin /run)."""
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())
    sys.modules.pop("rfid_reader", None)
    rr = importlib.import_module("rfid_reader")
    monkeypatch.setattr(rr, "DB", tmp_db)
    for nombre in ("STATUS_FILE", "ADMIN_FLAG", "ADMIN_UID_FILE"):
        if hasattr(rr, nombre):
            monkeypatch.setattr(rr, nombre, str(tmp_path / nombre.lower()))
    return rr


@pytest.fixture
def sqlite_tracker(monkeypatch):
    """Detecta conexiones sqlite3 creadas y nunca cerradas (tras gc)."""
    real_connect = sqlite3.connect
    vivas = weakref.WeakSet()

    class Tracked(sqlite3.Connection):
        cerrada = False

        def close(self):
            self.cerrada = True
            return super().close()

    def conectar(*a, **kw):
        kw.setdefault("factory", Tracked)
        c = real_connect(*a, **kw)
        if isinstance(c, Tracked):
            vivas.add(c)
        return c

    monkeypatch.setattr(sqlite3, "connect", conectar)

    def fugas():
        gc.collect()
        return [c for c in list(vivas) if not c.cerrada]

    return fugas


# ── En vivo ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def live():
    """Sesión autenticada contra los servicios reales (salta si no están disponibles)."""
    if not syslib.admin_creds()[1]:
        pytest.skip("No se pudo leer ADMIN_PASSWORD de .env")
    s = syslib.live_session()
    try:
        s.get(syslib.CFG["crud_url"] + "/api/health/db", timeout=5)
        s.get(syslib.CFG["dash_url"] + "/api/estado", timeout=5)
    except requests.RequestException as e:
        pytest.skip(f"Servicios reales no accesibles: {e}")
    return s
