"""04 · Rendimiento — concurrencia, tiempos de respuesta, conexiones SQLite y carga.

Umbrales ajustables con variables RFID_P50_MS, RFID_P95_MS, RFID_MAX_MS (ver syslib.CFG).
Los resultados se guardan en reports/perf.json y aparecen en el reporte HTML.
"""
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

import syslib
from syslib import CFG, UID, auth_headers, pct, save_perf

CRUD, DASH = CFG["crud_url"], CFG["dash_url"]
CASOS = [("crud", p) for p in syslib.CRUD_GET_SAFE] + [("dash", p) for p in syslib.DASH_GET_SAFE]
_tl = threading.local()


def _sess():
    if not hasattr(_tl, "s"):
        _tl.s = syslib.live_session()
    return _tl.s


def _base(app):
    return CRUD if app == "crud" else DASH


def _martillar(urls, total, workers):
    """`total` peticiones GET repartidas (round-robin) entre `urls`, con `workers` hilos."""
    def uno(i):
        t = time.perf_counter()
        try:
            code = _sess().get(urls[i % len(urls)], timeout=30).status_code
        except requests.RequestException:
            code = None
        return code, (time.perf_counter() - t) * 1000

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(uno, range(total)))
    dur = time.perf_counter() - t0
    lat = [ms for _, ms in res]
    return {"total": total, "workers": workers, "duracion_s": round(dur, 2), "rps": round(total / dur, 1),
            "errores": sum(1 for c, _ in res if c is None or c >= 500 or c == 429),
            "p50_ms": round(pct(lat, 50), 1), "p95_ms": round(pct(lat, 95), 1), "max_ms": round(max(lat), 1)}


def _verificar(r, nombre):
    save_perf(nombre, r)
    assert r["errores"] == 0, f"{r['errores']}/{r['total']} peticiones fallaron (5xx/429/timeout)"
    assert r["p95_ms"] < CFG["p95_ms"], f"p95={r['p95_ms']} ms (umbral {CFG['p95_ms']})"


@pytest.mark.live
class TestRequestsConcurrentes:
    def test_crud_100_peticiones_10_hilos(self, live):
        _verificar(_martillar([CRUD + "/api/estadisticas"], 100, 10), "concurrencia:crud")

    def test_dashboard_200_peticiones_20_hilos(self, live):
        _verificar(_martillar([DASH + "/api/estado"], 200, 20), "concurrencia:dashboard")

    def test_crud_y_dashboard_al_mismo_tiempo(self, live):
        urls = [CRUD + "/api/estudiantes", DASH + "/api/estado", CRUD + "/api/registros", DASH + "/api/ultimo-evento"]
        _verificar(_martillar(urls, 160, 16), "concurrencia:mixta")


@pytest.mark.live
class TestTiempoDeRespuesta:
    @pytest.mark.parametrize("app,path", CASOS)
    def test_latencia_por_endpoint(self, live, app, path):
        lat = []
        for _ in range(10):
            t = time.perf_counter()
            r = live.get(_base(app) + path, timeout=30)
            lat.append((time.perf_counter() - t) * 1000)
            assert r.status_code == 200, f"{path} → {r.status_code}"
        datos = {"p50_ms": round(pct(lat, 50), 1), "p95_ms": round(pct(lat, 95), 1), "max_ms": round(max(lat), 1)}
        save_perf(f"latencia:{app}{path}", datos)
        assert datos["p50_ms"] < CFG["p50_ms"], f"mediana {datos['p50_ms']} ms (umbral {CFG['p50_ms']})"
        assert datos["max_ms"] < CFG["max_ms"], f"máximo {datos['max_ms']} ms (umbral {CFG['max_ms']})"

    def test_nginx_no_agrega_latencia_excesiva(self, live):
        directo = f"{DASH}/api/estado"
        nginx = f"https://{CFG['nginx_host']}:{CFG['dash_https_port']}/api/estado"

        def mediana(url):
            lat = []
            for _ in range(15):
                t = time.perf_counter()
                live.get(url, timeout=30)
                lat.append((time.perf_counter() - t) * 1000)
            return pct(lat, 50)

        d, n = mediana(directo), mediana(nginx)
        save_perf("nginx:overhead", {"directo_ms": round(d, 1), "nginx_ms": round(n, 1)})
        assert n - d < 500, f"nginx+TLS agrega {n - d:.0f} ms (directo {d:.0f}, nginx {n:.0f})"


class TestConexionesSQLite:
    def test_get_db_usa_wal_foreign_keys_y_busy_timeout(self, reader):
        conn = reader.get_db()
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
        finally:
            conn.close()

    def test_escrituras_concurrentes_sin_database_is_locked(self, reader, tmp_db):
        hilos, escaneos = 8, 25
        uids = [UID["juan"], UID["maria"], UID["nadie"]]
        errores = []

        def worker(i):
            for k in range(escaneos):
                try:
                    reader.procesar(uids[(i + k) % 3])
                except Exception as e:
                    errores.append(repr(e))

        t0 = time.time()
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(hilos)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        dur = time.time() - t0
        save_perf("sqlite:escrituras_concurrentes", {"escaneos": hilos * escaneos, "segundos": round(dur, 2)})
        assert not errores, f"{len(errores)} errores, p. ej. {errores[0]}"
        n = syslib.q(tmp_db).execute("SELECT COUNT(*) FROM registros_asistencia").fetchone()[0]
        assert n == hilos * escaneos, f"se perdieron registros: {n}/{hilos * escaneos}"
        assert dur < 30

    def test_lecturas_no_se_bloquean_mientras_se_escribe(self, reader, tmp_db):
        parar = threading.Event()

        def escritor():
            while not parar.is_set():
                reader.procesar(UID["juan"])

        t = threading.Thread(target=escritor)
        t.start()
        lat = []
        try:
            for _ in range(100):
                t0 = time.perf_counter()
                c = sqlite3.connect(tmp_db, timeout=5)
                c.execute("SELECT COUNT(*) FROM registros_asistencia").fetchone()
                c.close()
                lat.append((time.perf_counter() - t0) * 1000)
        finally:
            parar.set()
            t.join()
        assert max(lat) < 1000, f"una lectura tardó {max(lat):.0f} ms mientras había escrituras"

    @pytest.mark.parametrize("app,path", [("crud", p) for p in syslib.CRUD_DB_GETS] + [("dash", p) for p in
                                                                                      ("/api/estado", "/api/ultimo-evento")])
    def test_endpoint_no_deja_conexiones_abiertas(self, request, app, path):
        if app == "crud":
            client, _ = request.getfixturevalue("crud_app")
            headers = auth_headers()
        else:
            client, _ = request.getfixturevalue("dash_app")
            headers = {}
        fugas = request.getfixturevalue("sqlite_tracker")  # se instala DESPUÉS de crear la app
        for _ in range(3):
            assert client.get(path, headers=headers).status_code < 500
        abiertas = fugas()
        assert not abiertas, f"{path} dejó {len(abiertas)} conexión(es) sqlite3 sin cerrar"

    @pytest.mark.live
    def test_wal_en_vivo_no_crece_sin_control(self, live):
        wal = syslib.LIVE_DB.with_name(syslib.LIVE_DB.name + "-wal")
        mb = wal.stat().st_size / 1e6 if wal.exists() else 0.0
        save_perf("sqlite:wal_mb", {"wal_mb": round(mb, 2)})
        assert mb < CFG["wal_max_mb"], f"el WAL pesa {mb:.1f} MB (umbral {CFG['wal_max_mb']}): ¿checkpoints bloqueados?"

    @pytest.mark.live
    @pytest.mark.parametrize("unit", syslib.UNITS)
    def test_conexiones_abiertas_a_la_bd_por_servicio(self, live, unit):
        pid = syslib.show(unit, "MainPID")["MainPID"]
        _, hijos, _ = syslib.sh(["pgrep", "-P", pid])
        total = 0
        for p in [pid, *hijos.split()]:
            try:
                for fd in os.listdir(f"/proc/{p}/fd"):
                    try:
                        if "rfid.db" in os.readlink(f"/proc/{p}/fd/{fd}"):
                            total += 1
                    except OSError:
                        pass
            except PermissionError:
                pytest.skip("sin permisos para inspeccionar /proc/<pid>/fd (los servicios corren como rfid-svc)")
        assert total <= CFG["max_fds_por_proceso"] * (1 + len(hijos.split())), f"{unit}: {total} descriptores abiertos"


@pytest.mark.live
class TestCargaDeEndpoints:
    def test_carga_sostenida_10s_sin_errores(self, live):
        urls = [CRUD + "/api/estadisticas", CRUD + "/api/estudiantes", CRUD + "/api/registros",
                CRUD + "/api/asistencia/hoy", DASH + "/api/estado", DASH + "/api/ultimo-evento"]
        fin = time.time() + 10
        lat, errs = [], []

        def worker(k):
            i = k
            while time.time() < fin:
                t = time.perf_counter()
                try:
                    c = _sess().get(urls[i % len(urls)], timeout=30).status_code
                except requests.RequestException:
                    c = None
                lat.append((time.perf_counter() - t) * 1000)
                if c is None or c >= 500 or c == 429:
                    errs.append(c)
                i += 1

        ts = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        datos = {"peticiones": len(lat), "errores": len(errs), "rps": round(len(lat) / 10, 1),
                 "p50_ms": round(pct(lat, 50), 1), "p95_ms": round(pct(lat, 95), 1)}
        save_perf("carga:sostenida_10s", datos)
        assert len(lat) > 50
        assert len(errs) / len(lat) < 0.01, f"{len(errs)} errores de {len(lat)} peticiones"
        assert datos["p95_ms"] < CFG["p95_ms"] * 2

    def test_todos_los_endpoints_responden_200_una_pasada(self, live):
        malos = []
        for app, path in CASOS:
            r = live.get(_base(app) + path, timeout=30)
            if r.status_code != 200:
                malos.append(f"{path} → {r.status_code}")
        assert not malos, "\n".join(malos)
