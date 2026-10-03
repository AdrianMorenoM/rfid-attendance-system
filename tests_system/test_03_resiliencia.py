"""03 · Resiliencia — reinicios, recuperación systemd y BD no disponible.

· Las pruebas en vivo que reinician o matan servicios llevan @destructive (--destructive).
· Las de "BD no disponible" corren en proceso sobre una BD temporal.
"""
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest
import requests

import syslib
from syslib import CARDS, CFG, UID, UNITS, FakeMFRC522, auth_headers, is_active, show, sh, \
    sudo_systemctl, to_seconds, wait_until

CRUD, DASH = CFG["crud_url"], CFG["dash_url"]


def _crud_ok(live):
    try:
        return live.get(CRUD + "/api/health/db", timeout=5).status_code == 200
    except requests.RequestException:
        return False


def _dash_ok(live):
    try:
        return live.get(DASH + "/api/estado", timeout=5).status_code == 200
    except requests.RequestException:
        return False


def _snapshot(live):
    return live.get(CRUD + "/api/estudiantes", timeout=10).text.count('"matricula"')


def _ciclo_reinicio(unit, health):
    if not syslib.can_sudo("systemctl", "restart", unit):
        pytest.skip(f"sudo -n no permite reiniciar {unit}")
    antes = show(unit, "MainPID")["MainPID"]
    rc, _, err = sudo_systemctl("restart", unit)
    assert rc == 0, f"systemctl restart falló: {err}"
    ok = wait_until(lambda: is_active(unit) and health(), timeout=CFG["restart_timeout"])
    return ok, antes, show(unit, "MainPID")["MainPID"]


@pytest.mark.live
@pytest.mark.destructive
class TestReinicioCRUD:
    def test_reinicia_y_vuelve_a_responder_sin_perder_datos(self, live):
        antes = _snapshot(live)
        ok, pid0, pid1 = _ciclo_reinicio("rfid-crud.service", lambda: _crud_ok(live))
        assert ok, "rfid-crud no volvió a responder a tiempo"
        assert pid1 not in ("", "0") and pid0 != pid1, "el PID no cambió: ¿se reinició de verdad?"
        assert _snapshot(live) == antes, "cambió el número de estudiantes tras el reinicio"


@pytest.mark.live
@pytest.mark.destructive
class TestReinicioDashboard:
    def test_reinicia_y_vuelve_a_responder(self, live):
        ok, pid0, pid1 = _ciclo_reinicio("rfid-dashboard.service", lambda: _dash_ok(live))
        assert ok, "rfid-dashboard no volvió a responder a tiempo"
        assert pid1 not in ("", "0") and pid0 != pid1

    def test_no_quedan_workers_huerfanos(self, live):
        """KillMode=control-group: tras reiniciar solo deben existir los procesos de la unidad actual."""
        _ciclo_reinicio("rfid-dashboard.service", lambda: _dash_ok(live))
        main = show("rfid-dashboard.service", "MainPID")["MainPID"]
        _, hijos, _ = sh(["pgrep", "-P", main])
        _, todos, _ = sh(["pgrep", "-f", "gunicorn.*app_dashboard"])
        assert set(todos.split()) <= set(hijos.split()) | {main}, "hay procesos gunicorn huérfanos"


@pytest.mark.live
@pytest.mark.destructive
class TestReinicioReader:
    def test_reinicia_y_se_mantiene_activo(self, live):
        ok, pid0, pid1 = _ciclo_reinicio("rfid-reader.service", lambda: True)
        assert ok and pid0 != pid1
        time.sleep(8)  # RestartSec=5: si se cae al arrancar, ya habría reiniciado
        assert is_active("rfid-reader.service")
        assert show("rfid-reader.service", "MainPID")["MainPID"] == pid1, "el lector está en bucle de reinicios"


@pytest.mark.live
class TestRecuperacionSystemd:
    @pytest.mark.parametrize("unit", UNITS)
    def test_politica_restart_always_con_espera_corta(self, live, unit):
        p = show(unit, "Restart", "RestartUSec")
        assert p["Restart"] == "always", f"{unit}: Restart={p['Restart']}"
        espera = to_seconds(p["RestartUSec"])
        assert espera is not None and espera <= 10, f"{unit}: RestartUSec={p['RestartUSec']}"

    @pytest.mark.parametrize("unit", UNITS)
    def test_habilitada_para_arrancar_con_el_sistema(self, live, unit):
        assert sh(["systemctl", "is-enabled", unit])[1] == "enabled"

    @pytest.mark.destructive
    @pytest.mark.parametrize("unit", UNITS)
    def test_se_recupera_tras_kill_9(self, live, unit):
        pid = show(unit, "MainPID")["MainPID"]
        assert pid not in ("", "0"), f"{unit} no está corriendo"
        rc, _, err = sh(["sudo", "-n", "kill", "-9", pid])
        if rc != 0:
            pytest.skip(f"sudo -n no permite 'kill -9' ({err[:80]}); se valida la política con el test anterior")
        espera = to_seconds(show(unit, "RestartUSec")["RestartUSec"]) or 5
        ok = wait_until(lambda: is_active(unit) and show(unit, "MainPID")["MainPID"] not in (pid, "0"),
                        timeout=espera + CFG["restart_timeout"])
        assert ok, f"{unit} no se recuperó tras kill -9 del PID {pid}"


class TestRecuperacionBDNoDisponible:
    @staticmethod
    def _corromper(db):
        for ext in ("-wal", "-shm"):
            if os.path.exists(db + ext):
                os.remove(db + ext)
        Path(db).write_bytes(b"esto no es una base de datos sqlite " * 50)

    @staticmethod
    def _respaldar(db):
        dst = db + ".copia"
        src, out = sqlite3.connect(db), sqlite3.connect(dst)
        src.backup(out)
        src.close()
        out.close()
        return dst

    def test_bd_corrupta_el_health_falla_y_la_app_sigue_viva(self, crud_app, tmp_db):
        client, m = crud_app
        h = auth_headers()
        assert client.get("/api/health/db", headers=h).status_code == 200
        copia = self._respaldar(tmp_db)
        self._corromper(tmp_db)
        t0 = time.time()
        r = client.get("/api/health/db", headers=h)
        assert r.status_code != 200, "health/db responde 200 con la BD corrupta"
        r2 = client.get("/api/estadisticas", headers=h)
        assert "Traceback" not in r2.get_data(as_text=True), "la app expone un traceback al usuario"
        assert time.time() - t0 < 10, "la app se colgó con la BD corrupta"
        # recuperación sin reiniciar la app
        shutil.copy(copia, tmp_db)
        assert client.get("/api/health/db", headers=h).status_code == 200, \
            "la app no se recuperó al volver la BD (requiere reinicio)"

    def test_health_detecta_una_bd_vacia(self, crud_app, tmp_db):
        """sqlite3.connect() crea un archivo vacío si falta la BD: el health debe notarlo."""
        client, _ = crud_app
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(tmp_db + ext):
                os.remove(tmp_db + ext)
        r = client.get("/api/health/db", headers=auth_headers())
        assert r.status_code != 200, "health/db dice OK con una BD vacía (sin tablas)"

    def test_lector_con_bd_corrupta_falla_rapido_y_sin_colgarse(self, reader, tmp_db):
        self._corromper(tmp_db)
        t0 = time.time()
        with pytest.raises(sqlite3.Error):
            reader.procesar(UID["juan"])
        assert time.time() - t0 < 5

    def test_lector_se_recupera_cuando_vuelve_la_bd(self, reader, tmp_db):
        copia = self._respaldar(tmp_db)
        self._corromper(tmp_db)
        with pytest.raises(sqlite3.Error):
            reader.procesar(UID["juan"])
        shutil.copy(copia, tmp_db)
        assert reader.procesar(UID["juan"])[0] == "aceptado"

    def test_lector_espera_un_bloqueo_y_no_pierde_el_registro(self, reader, tmp_db):
        lock = sqlite3.connect(tmp_db, timeout=1, isolation_level=None, check_same_thread=False)
        lock.execute("BEGIN IMMEDIATE")

        def liberar():
            lock.execute("ROLLBACK")
            lock.close()

        threading.Timer(2.0, liberar).start()
        t0 = time.time()
        tipo, _, _ = reader.procesar(UID["juan"])
        dt = time.time() - t0
        assert tipo == "aceptado"
        assert 1.5 <= dt < 10, f"tardó {dt:.1f}s: ¿esperó el bloqueo?"
        n = sqlite3.connect(tmp_db).execute("SELECT COUNT(*) FROM registros_asistencia").fetchone()[0]
        assert n == 1

    @pytest.mark.live
    @pytest.mark.destructive
    def test_en_vivo_bd_bloqueada_3s_las_lecturas_siguen_respondiendo(self, live):
        if not os.access(syslib.LIVE_DB, os.W_OK):
            pytest.skip("sin permiso de escritura sobre shared/rfid.db")
        lock = sqlite3.connect(str(syslib.LIVE_DB), timeout=5, isolation_level=None, check_same_thread=False)
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as e:
            lock.close()
            pytest.skip(f"no se pudo bloquear la BD: {e}")
        try:
            estados = []
            for _ in range(6):
                estados.append(live.get(CRUD + "/api/estadisticas", timeout=5).status_code)
                time.sleep(0.5)
            dash = live.get(DASH + "/api/estado", timeout=5).status_code
        finally:
            lock.execute("ROLLBACK")
            lock.close()
        assert set(estados) == {200}, f"el CRUD respondió {estados} con la BD bloqueada"
        assert dash == 200
        assert is_active("rfid-reader.service")
        assert wait_until(lambda: _crud_ok(live), timeout=10)
