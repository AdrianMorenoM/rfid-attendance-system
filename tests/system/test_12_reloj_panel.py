"""Fijar la hora desde el panel: validaciones, buzon y esperas (sin tocar la Pi real)."""
import threading
import time
from functools import wraps

import pytest
from flask import Flask, jsonify, request

import reloj_api as ra

H = {"X-Requested-With": "XMLHttpRequest"}
URL = "/api/hardware/system/set-time"
OK = {"confirm": True, "epoch": 1800000000}


def _xhr(f):
    @wraps(f)
    def w(*a, **k):
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return jsonify(success=False), 403
        return f(*a, **k)
    return w


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "DIR", str(tmp_path))
    monkeypatch.setattr(ra, "SYNC_MARCA", str(tmp_path / "no_sync"))
    monkeypatch.setattr(ra, "MANUAL_MARCA", str(tmp_path / "manual"))
    monkeypatch.setattr(ra, "ESPERA_S", 1.5)
    monkeypatch.setattr(ra, "ENFRIAMIENTO_S", 0.0)
    monkeypatch.setattr(ra, "_ultimo", -1e9)
    app = Flask("t_reloj")
    app.audit = []
    ra.registrar(app, _xhr, lambda f: f, lambda *a: app.audit.append(a))
    return app.test_client()


def _root(tmp_path, codigo, msg):
    def run():
        req = tmp_path / "fijar_hora.req"
        for _ in range(100):
            if req.exists():
                req.unlink()
                (tmp_path / "fijar_hora.res").write_text(f"{codigo} {msg}\n")
                return
            time.sleep(0.05)
    t = threading.Thread(target=run)
    t.start()
    return t


def test_estado_y_confiabilidad(cli, tmp_path):
    r = cli.get("/api/hardware/system/clock-status").get_json()
    assert r["sincronizado"] is False and r["confiable"] is False
    (tmp_path / "manual").write_text("")
    assert cli.get("/api/hardware/system/clock-status").get_json()["confiable"] is True


def test_exige_cabecera_xhr(cli):
    assert cli.post(URL, json=OK).status_code == 403


def test_exige_confirmacion(cli):
    assert cli.post(URL, json={"epoch": 1800000000}, headers=H).status_code == 400


@pytest.mark.parametrize("epoch", [None, "1800000000", True, 1.5, 1000000000, 3000000000])
def test_rechaza_epoch_invalido(cli, epoch):
    r = cli.post(URL, json={"confirm": True, "epoch": epoch}, headers=H)
    assert r.status_code == 400


def test_rechaza_si_ya_hay_ntp(cli, tmp_path):
    (tmp_path / "no_sync").write_text("")
    assert cli.post(URL, json=OK, headers=H).status_code == 409


def test_exito_consume_la_peticion_y_audita(cli, tmp_path):
    t = _root(tmp_path, 0, "OK")
    r = cli.post(URL, json=OK, headers=H)
    t.join()
    assert r.status_code == 200 and r.get_json()["success"] is True
    assert not (tmp_path / "fijar_hora.req").exists()
    assert cli.application.audit[-1][0] == "hardware_system_set_time"


def test_el_servicio_de_root_rechaza(cli, tmp_path):
    t = _root(tmp_path, 2, "El reloj ya esta sincronizado")
    r = cli.post(URL, json=OK, headers=H)
    t.join()
    assert r.status_code == 409


def test_sin_respuesta_da_504_y_limpia(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "ESPERA_S", 0.3)
    r = cli.post(URL, json=OK, headers=H)
    assert r.status_code == 504
    assert not (tmp_path / "fijar_hora.req").exists()


def test_enfriamiento_entre_intentos(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "ENFRIAMIENTO_S", 60.0)
    t = _root(tmp_path, 0, "OK")
    assert cli.post(URL, json=OK, headers=H).status_code == 200
    t.join()
    assert cli.post(URL, json=OK, headers=H).status_code == 429
