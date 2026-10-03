"""02 · Seguridad — autenticación, CSRF (X-Requested-With), rate limiting, SQLi y path traversal.

En proceso (BD temporal, subprocess bloqueado) salvo las marcadas `live`.
Los intentos de login fallidos en vivo se limitan a 2 (el bloqueo es a partir de 5/min
y comparte IP 127.0.0.1 con cron y health_check).
"""
import ast
import inspect
import io
import os
import re
import shutil
import sqlite3
import stat
from pathlib import Path
from urllib.parse import quote, urlencode

import pytest
import requests

import syslib
from syslib import CFG, ROOT, TEST_PWD, auth_headers, basic_header

MUT = {"POST", "PUT", "DELETE", "PATCH"}
# El dashboard puede ser público por diseño (pantalla de asistencia). Con RFID_DASH_PUBLICO=1
# se omiten las pruebas que exigen login en él.
DASH_PUBLICO = os.environ.get("RFID_DASH_PUBLICO") == "1"
# Interpolaciones en f-strings de SQL ya revisadas a mano: s['col'] es un nombre de columna detectado
# del esquema de la BD (schema(conn)), no una entrada del usuario.
INTERPOLACIONES_SEGURAS = {"s['col']", 's["col"]'}
# Rutas cuyo manejador tiene efectos sobre el sistema real (reinicios, /run, fotos, restore...).
PELIGROSAS = re.compile(
    r"/hardware/|/services/|reboot|shutdown|poweroff|admin-scan|/listen|upload-foto|/migrate|purge|/restore",
    re.I)
SUBS = {"est_id": "1", "tarj_id": "1", "filename": "x.db", "service_name": "rfid-crud.service",
        "action": "status", "uid": "123", "path": "x"}


def iter_rutas(mod, metodos):
    for rule in mod.app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        llena = re.sub(r"<(?:[^:>]+:)?([^>]+)>", lambda m: SUBS.get(m.group(1), "1"), rule.rule)
        for metodo in sorted((rule.methods or set()) & metodos):
            yield metodo, llena, rule


def reset_fallos(mod, db):
    try:
        mod._AUTH_FAIL_STORAGE.reset()
    except Exception:
        pass
    c = sqlite3.connect(db)
    c.execute("DELETE FROM auth_fail_log")
    c.commit()
    c.close()


def tablas_intactas(db, esperado):
    return syslib.table_counts(db) == esperado


# ═════════════════════════════════════════════════════════════════════════════
class TestAutenticacion:
    def test_crud_sin_credenciales_401_con_www_authenticate(self, crud_app, tmp_db):
        client, m = crud_app
        r = client.get("/api/estadisticas")
        assert r.status_code == 401
        assert "Basic" in r.headers.get("WWW-Authenticate", "")

    def test_dashboard_sin_credenciales_401(self, dash_app):
        if DASH_PUBLICO:
            pytest.skip("RFID_DASH_PUBLICO=1: dashboard sin login en la app (público o protegido por Nginx)")
        _, m = dash_app
        r = m.app.test_client().get("/api/estado")
        assert r.status_code == 401

    @pytest.mark.parametrize("user,pwd", [
        ("admin", "incorrecta"), ("otro", TEST_PWD), ("admin", ""), ("", ""),
        ("admin' OR '1'='1", "x"), ("admin", TEST_PWD + "x"), ("ADMIN", TEST_PWD),
    ])
    def test_credenciales_incorrectas_401(self, crud_app, tmp_db, user, pwd):
        client, m = crud_app
        reset_fallos(m, tmp_db)
        r = client.get("/api/estadisticas", headers={"Authorization": basic_header(user, pwd)})
        assert r.status_code == 401

    @pytest.mark.parametrize("valor", ["Basic", "Basic !!!no-base64", "Bearer abc.def.ghi",
                                       "Basic YWRtaW4=", "Digest username=admin", "Basic " + "A" * 5000])
    def test_cabecera_authorization_malformada_no_produce_500(self, crud_app, tmp_db, valor):
        client, m = crud_app
        reset_fallos(m, tmp_db)
        r = client.get("/api/estadisticas", headers={"Authorization": valor})
        assert r.status_code in (400, 401, 431), f"→ {r.status_code}"

    def test_credenciales_correctas_200(self, crud_app, dash_app):
        assert crud_app[0].get("/api/estadisticas", headers=auth_headers()).status_code == 200
        assert dash_app[0].get("/api/estado").status_code == 200

    def test_crud_todas_las_rutas_exigen_autenticacion(self, crud_app, tmp_db, monkeypatch):
        client, m = crud_app
        fallos = self._barrido(m, tmp_db, monkeypatch)
        assert not fallos, "Rutas del CRUD accesibles sin credenciales:\n  " + "\n  ".join(fallos)

    def test_dashboard_todas_las_rutas_exigen_autenticacion(self, dash_app, tmp_db, monkeypatch):
        if DASH_PUBLICO:
            pytest.skip("RFID_DASH_PUBLICO=1: dashboard sin login en la app (público o protegido por Nginx)")
        _, m = dash_app
        fallos = self._barrido(m, tmp_db, monkeypatch)
        assert not fallos, "Rutas del dashboard accesibles sin credenciales:\n  " + "\n  ".join(fallos)

    @staticmethod
    def _barrido(m, db, monkeypatch):
        """Llama cada ruta SIN credenciales. Los manejadores peligrosos se sustituyen por un
        stub: si el stub responde, la ruta estaba abierta."""
        src = Path(m.__file__).read_text()
        stub = "@require_basic_auth" not in src  # con auth global el stub no altera la protección
        if stub:
            for rule in m.app.url_map.iter_rules():
                if rule.endpoint != "static" and PELIGROSAS.search(rule.rule):
                    monkeypatch.setitem(m.app.view_functions, rule.endpoint,
                                        lambda **kw: ("STUB_ALCANZADO", 200))
        client = m.app.test_client()
        fallos = []
        for metodo, ruta, rule in iter_rutas(m, {"GET"} | MUT):
            if not stub and metodo != "GET" and PELIGROSAS.search(rule.rule):
                continue
            if hasattr(m, "_ensure_auth_fail_table"):
                reset_fallos(m, db)  # evita que el bloqueo por intentos fallidos (429) enmascare el 401
            r = client.open(ruta, method=metodo, json={} if metodo != "GET" else None)
            if r.status_code not in (401, 403) or b"STUB_ALCANZADO" in r.data:
                fallos.append(f"{metodo} {ruta} → {r.status_code}")
        return fallos

    @pytest.mark.parametrize("modulo", ["crud/app_crud.py", "dashboard/app_dashboard.py"])
    def test_comparacion_de_credenciales_segura(self, modulo):
        src = (ROOT / modulo).read_text()
        if "request.authorization" not in src and "Authorization" not in src:
            pytest.skip(f"{modulo} no implementa autenticación (no hay credenciales que comparar)")
        assert "compare_digest" in src or "check_password_hash" in src, \
            f"{modulo} no usa hmac.compare_digest/check_password_hash: comparación vulnerable a timing"

    def test_password_admin_no_es_debil(self):
        user, pwd = syslib.admin_creds()
        if not pwd:
            pytest.skip("No se pudo leer .env")
        debiles = {"admin", "password", "123456", "12345678", "admin123", "rfid", "itsoeh", "changeme"}
        assert len(pwd) >= 12, "ADMIN_PASSWORD tiene menos de 12 caracteres"
        assert pwd.lower() not in debiles and pwd.lower() != user.lower()

    @pytest.mark.parametrize("ruta", [".env", "shared/rfid.db", "shared/backups"])
    def test_archivos_sensibles_sin_permisos_para_otros(self, ruta):
        p = ROOT / ruta
        if not p.exists():
            pytest.skip(f"{ruta} no existe")
        modo = stat.S_IMODE(p.stat().st_mode)
        assert modo & 0o007 == 0, f"{ruta} es accesible por 'otros' (modo {oct(modo)})"

    @pytest.mark.live
    def test_en_vivo_sin_credenciales_401(self, live):
        destinos = [(CFG["crud_url"], "/api/estadisticas")]
        if not DASH_PUBLICO:
            destinos.append((CFG["dash_url"], "/api/estado"))
        for base, ruta in destinos:
            r = requests.get(base + ruta, timeout=10)
            assert r.status_code == 401, f"{base}{ruta} → {r.status_code}"

    @pytest.mark.live
    def test_en_vivo_credenciales_incorrectas_401(self, live):
        r = requests.get(CFG["crud_url"] + "/api/estadisticas", auth=("admin", "clave-incorrecta"), timeout=10)
        assert r.status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
class TestCSRF:
    """Defensa CSRF = autenticación Basic + cabecera personalizada X-Requested-With."""

    def test_backup_exige_cabecera_xhr(self, crud_app):
        client, _ = crud_app
        sin = client.post("/api/software/database/backup", headers=auth_headers(xhr=False), json={})
        con = client.post("/api/software/database/backup", headers=auth_headers(), json={})
        assert sin.status_code in (400, 403), f"sin cabecera → {sin.status_code}"
        assert con.status_code == 200, f"con cabecera → {con.status_code}"

    def test_mutaciones_sin_cabecera_xhr_nunca_devuelven_2xx(self, crud_app):
        client, m = crud_app
        fallos = []
        for metodo, ruta, rule in iter_rutas(m, MUT):
            if PELIGROSAS.search(rule.rule):
                continue
            r = client.open(ruta, method=metodo, headers=auth_headers(xhr=False), json={})
            if 200 <= r.status_code < 300:
                fallos.append(f"{metodo} {ruta} → {r.status_code}")
        assert not fallos, "Mutaciones aceptadas sin X-Requested-With:\n  " + "\n  ".join(fallos)

    def test_todas_las_rutas_mutantes_declaran_require_xhr_header(self, crud_app):
        _, m = crud_app
        globales = m.app.before_request_funcs.get(None, [])
        if any(k in getattr(f, "__name__", "").lower() for f in globales for k in ("xhr", "csrf")):
            return  # protección global
        faltan = []
        for metodo, ruta, rule in iter_rutas(m, MUT):
            try:
                src = inspect.getsource(m.app.view_functions[rule.endpoint])
            except (OSError, TypeError):
                continue
            if "require_xhr_header" not in src:
                faltan.append(f"{metodo} {rule.rule}")
        assert not faltan, "Rutas mutantes sin require_xhr_header:\n  " + "\n  ".join(faltan)

    def test_no_hay_cors_abierto(self, crud_app, dash_app):
        for client, ruta, hdr in ((crud_app[0], "/api/estadisticas", auth_headers()),
                                  (dash_app[0], "/api/estado", {})):
            r = client.get(ruta, headers={**hdr, "Origin": "https://evil.example"})
            assert r.headers.get("Access-Control-Allow-Origin") not in ("*", "https://evil.example"), \
                f"{ruta} permite CORS desde orígenes arbitrarios"


# ═════════════════════════════════════════════════════════════════════════════
class TestRateLimiting:
    @staticmethod
    def fallar(client, ip="10.20.30.40"):
        return client.get("/api/estadisticas", headers=auth_headers("admin", "mala"),
                          environ_overrides={"REMOTE_ADDR": ip})

    def test_bloquea_tras_intentos_fallidos(self, crud_app):
        client, m = crud_app
        maxi = getattr(m, "_AUTH_FAIL_SHORT_MAX", 5)
        estados = [self.fallar(client).status_code for _ in range(maxi + 10)]
        assert 429 in estados, f"nunca hubo 429 tras {len(estados)} fallos: {set(estados)}"
        assert estados.index(429) <= maxi + 1, f"bloqueo tardío (primer 429 en intento {estados.index(429) + 1})"
        assert set(estados[:maxi]) == {401}

    def test_el_bloqueo_es_por_ip(self, crud_app):
        client, m = crud_app
        for _ in range(getattr(m, "_AUTH_FAIL_SHORT_MAX", 5) + 3):
            self.fallar(client, "10.0.0.1")
        assert self.fallar(client, "10.0.0.2").status_code == 401

    def test_los_fallos_se_guardan_en_sqlite(self, crud_app, tmp_db):
        client, m = crud_app
        reset_fallos(m, tmp_db)
        for _ in range(3):
            self.fallar(client)
        n = sqlite3.connect(tmp_db).execute("SELECT COUNT(*) FROM auth_fail_log").fetchone()[0]
        assert n >= 3

    def test_fallos_antiguos_no_bloquean(self, crud_app, tmp_db):
        client, m = crud_app
        reset_fallos(m, tmp_db)
        c = sqlite3.connect(tmp_db)
        c.executemany("INSERT INTO auth_fail_log (ip, ts) VALUES (?, datetime('now', '-3 days'))",
                      [("10.9.9.9",)] * 30)
        c.commit()
        c.close()
        assert self.fallar(client, "10.9.9.9").status_code == 401

    def test_admin_autenticado_no_es_limitado(self, crud_app):
        client, _ = crud_app
        estados = {client.get("/api/estadisticas", headers=auth_headers()).status_code for _ in range(80)}
        assert estados == {200}, f"el admin recibió {estados} con 80 peticiones seguidas"


# ═════════════════════════════════════════════════════════════════════════════
PAYLOADS = ["' OR '1'='1", "'; DROP TABLE estudiantes;--", "1; DELETE FROM registros_asistencia",
            "\" OR \"\"=\"", "' UNION SELECT 1,2,3,4,5,6,7,8,9,10,11,12--", "%' AND 1=1--",
            "1 OR 1=1", "admin'--", "'; ATTACH DATABASE '/tmp/x.db' AS x;--"]
PARAMS = ["q", "buscar", "search", "busqueda", "nombre", "matricula", "carrera", "grupo", "estado",
          "uid", "fecha", "desde", "hasta", "tipo", "semestre", "limit", "page", "offset", "orden", "sort"]
LISTAS = ["/api/estudiantes", "/api/tarjetas", "/api/registros", "/api/audit-log"]
ERR_SQL = re.compile(r"sqlite3\.|OperationalError|syntax error|unrecognized token|near \"|"
                     r"no such (table|column)|unterminated|incomplete input", re.I)


def hallazgos_sql(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    altos, info = [], []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("execute", "executemany", "executescript") and n.args):
            continue
        q = n.args[0]
        dinamica = (
            (isinstance(q, ast.JoinedStr) and any(isinstance(v, ast.FormattedValue) for v in q.values))
            or (isinstance(q, ast.BinOp) and isinstance(q.op, (ast.Add, ast.Mod))
                and not (isinstance(q.left, ast.Constant) and isinstance(q.right, ast.Constant)))
            or (isinstance(q, ast.Call) and isinstance(q.func, ast.Attribute) and q.func.attr == "format"))
        if not dinamica:
            continue
        if isinstance(q, ast.JoinedStr):
            exprs = {ast.unparse(v.value) for v in q.values if isinstance(v, ast.FormattedValue)}
            if exprs and exprs <= INTERPOLACIONES_SEGURAS:
                continue
        es_pragma = (isinstance(q, ast.JoinedStr) and q.values and isinstance(q.values[0], ast.Constant)
                     and str(q.values[0].value).lstrip().upper().startswith("PRAGMA"))
        con_params = len(n.args) > 1 or bool(n.keywords)
        (info if (con_params or es_pragma) else altos).append(f"{Path(path).name}:{n.lineno}")
    return altos, info


class TestSQLInjection:
    def test_payloads_en_query_string_no_alteran_ni_filtran_errores_sql(self, crud_app, tmp_db):
        client, _ = crud_app
        antes = syslib.table_counts(tmp_db)
        problemas = []
        for payload in PAYLOADS:
            qs = urlencode({p: payload for p in PARAMS})
            for ruta in syslib.CRUD_DB_GETS + [f"/api/rfid/historial/{quote(payload, safe='')}"]:
                sep = "&" if "?" in ruta else "?"
                url = ruta if "historial" in ruta else f"{ruta}{sep}{qs}"
                r = client.get(url, headers=auth_headers())
                if ERR_SQL.search(r.get_data(as_text=True)):
                    problemas.append(f"{ruta} filtra error SQL con {payload!r}")
        assert not problemas, "\n".join(problemas[:15])
        assert tablas_intactas(tmp_db, {**antes, "audit_log": syslib.table_counts(tmp_db)["audit_log"],
                                        "auth_fail_log": syslib.table_counts(tmp_db)["auth_fail_log"]})

    @pytest.mark.parametrize("payload", ["' OR '1'='1", "1 OR 1=1", "%' OR 1=1--"])
    def test_inyeccion_booleana_no_amplifica_resultados(self, crud_app, payload):
        client, _ = crud_app
        problemas = []
        for ruta in LISTAS:
            for p in PARAMS:
                base = client.get(f"{ruta}?{urlencode({p: 'zzzz_sin_coincidencia'})}", headers=auth_headers())
                ataque = client.get(f"{ruta}?{urlencode({p: payload})}", headers=auth_headers())
                n0, n1 = base.get_data(as_text=True).count('"id"'), ataque.get_data(as_text=True).count('"id"')
                if n1 > n0:
                    problemas.append(f"{ruta}?{p}= devuelve {n1} filas vs {n0} de referencia")
        assert not problemas, "Posible inyección booleana:\n  " + "\n  ".join(problemas)

    def test_payloads_en_cuerpo_json_se_guardan_literales_o_se_rechazan(self, crud_app, tmp_db):
        client, _ = crud_app
        for i, payload in enumerate(PAYLOADS):
            r = client.post("/api/estudiantes", headers=auth_headers(), json={
                "nombre": payload, "apellido_paterno": "Prueba", "matricula": f"SQLI-{i}",
                "carrera": "ITIC's", "semestre": 1, "grupo": "A", "estado": "activo"})
            assert r.status_code < 500, f"{payload!r} → {r.status_code}: {r.get_data(as_text=True)[:120]}"
            if r.status_code < 300:
                n = sqlite3.connect(tmp_db).execute(
                    "SELECT COUNT(*) FROM estudiantes WHERE nombre = ?", (payload,)).fetchone()[0]
                assert n == 1, f"{payload!r} no se guardó literalmente"
        assert "estudiantes" in {t for (t,) in sqlite3.connect(tmp_db).execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

    def test_uid_hostil_en_el_lector_es_un_uid_desconocido(self, reader, tmp_db):
        antes = syslib.table_counts(tmp_db)
        for payload in PAYLOADS:
            tipo, nombre, _ = reader.procesar(payload)
            assert (tipo, nombre) == ("rebote", "DESCONOCIDO")
        despues = syslib.table_counts(tmp_db)
        assert despues["estudiantes"] == antes["estudiantes"] and despues["tarjetas"] == antes["tarjetas"]
        assert despues["registros_asistencia"] == len(PAYLOADS)

    def test_entradas_hostiles_no_producen_500(self, crud_app):
        client, _ = crud_app
        qs = urlencode({p: PAYLOADS[1] for p in PARAMS})
        malos = []
        for ruta in syslib.CRUD_DB_GETS:
            r = client.get(f"{ruta}?{qs}", headers=auth_headers())
            if r.status_code >= 500:
                malos.append(f"{ruta} → {r.status_code}")
        assert not malos, "Errores 5xx con entradas hostiles:\n  " + "\n  ".join(malos)

    def test_lint_sql_dinamico_sin_parametros(self):
        archivos = [ROOT / "crud/app_crud.py", ROOT / "dashboard/app_dashboard.py", ROOT / "shared/rfid_reader.py",
                    ROOT / "shared/init_db.py", ROOT / "shared/run_incremental_vacuum.py"]
        altos = []
        for f in archivos:
            if f.exists():
                a, _ = hallazgos_sql(f)
                altos += a
        assert not altos, ("SQL armado con f-string/concatenación y SIN parámetros enlazados "
                           "(revisar que no venga de entrada del usuario): " + ", ".join(altos))


# ═════════════════════════════════════════════════════════════════════════════
TRAVERSAL = ["../app_dashboard.py", "../../shared/rfid.db", "..%2f..%2fshared%2frfid.db",
             "%2e%2e/%2e%2e/shared/rfid.db", "....//....//etc/passwd", "/etc/passwd",
             "..\\..\\shared\\rfid.db", "%252e%252e/%252e%252e/etc/passwd", "foto.jpg%00.png",
             "../../.env", "../../../../etc/passwd", "../secreto.txt", "..%2fsecreto.txt",
             "%2e%2e/secreto.txt"]
ESTADOS_SEGUROS = (301, 302, 307, 308, 400, 403, 404)


class TestPathTraversal:
    def test_dashboard_fotos_no_sale_del_directorio(self, dash_app, tmp_path, monkeypatch):
        client, m = dash_app
        fotos = tmp_path / "fotos"
        fotos.mkdir()
        (fotos / "ok.jpg").write_bytes(b"\xff\xd8\xff legit")
        (tmp_path / "secreto.txt").write_text("TOP-SECRET-123")
        monkeypatch.setattr(m, "FOTOS_DIR", str(fotos))
        assert client.get("/fotos/ok.jpg").status_code == 200, "control: un archivo legítimo debe servirse"
        for p in TRAVERSAL:
            r = client.get("/fotos/" + p)
            cuerpo = r.get_data()
            assert r.status_code in ESTADOS_SEGUROS, f"/fotos/{p} → {r.status_code}"
            assert b"TOP-SECRET" not in cuerpo and not cuerpo.startswith(b"SQLite format 3")

    def test_crud_backups_descargar_restaurar_y_borrar_no_salen_del_directorio(self, crud_app, tmp_db):
        client, m = crud_app
        h = auth_headers()
        secreto = Path(m.BACKUP_DIR).parent / "secreto.db"
        secreto.write_bytes(b"SQLite format 3\x00 SECRETO")
        shutil.copy(tmp_db, Path(m.BACKUP_DIR) / "rfid_backup_20260101_000000.db")
        antes = syslib.table_counts(tmp_db)
        for p in ["..%2fsecreto.db", "..%2f..%2fsecreto.db", "../secreto.db", "%2e%2e%2fsecreto.db",
                  "..\\secreto.db", "....//secreto.db"]:
            d = client.get(f"/api/software/database/backups/{p}/download", headers=h)
            assert b"SECRETO" not in d.get_data(), f"descarga fuera del directorio con {p!r}"
            rs = client.post("/api/software/database/restore", headers=h,
                             json={"filename": p.replace("%2f", "/").replace("%2e", "."), "confirm": True})
            assert rs.status_code in (400, 404), f"restore con {p!r} → {rs.status_code}"
            dl = client.delete(f"/api/software/database/backups/{p}?confirm=1", headers=h)
            assert secreto.exists(), f"DELETE con {p!r} borró un archivo fuera de backups/"
        assert syslib.integrity_ok(tmp_db) and syslib.table_counts(tmp_db) == antes, \
            "un restore con nombre malicioso alteró la BD"

    def test_crud_static_no_sirve_codigo_fuente(self, crud_app):
        client, _ = crud_app
        for p in ["/static/../app_crud.py", "/static/..%2fapp_crud.py", "/static/%2e%2e/app_crud.py"]:
            r = client.get(p, headers=auth_headers())
            assert b"from flask import" not in r.get_data(), f"{p} expone el código fuente"

    def test_upload_foto_ignora_nombres_con_traversal(self, crud_app, tmp_path, monkeypatch):
        client, m = crud_app
        attrs = [n for n in ("FOTOS", "FOTOS_DIR", "UPLOAD_DIR", "UPLOAD_FOLDER", "FOTO_DIR", "FOTOS_PATH") if hasattr(m, n)]
        if not attrs:
            pytest.skip("No pude localizar la variable del directorio de fotos en app_crud.py")
        destino = tmp_path / "fotos_up"
        destino.mkdir()
        for n in attrs:
            monkeypatch.setattr(m, n, str(destino))
        try:
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (2, 2)).save(buf, "PNG")
            png = buf.getvalue()
        except ImportError:
            png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
        for campo in ("foto", "file", "archivo", "imagen"):
            client.post("/api/upload-foto", headers=auth_headers(), content_type="multipart/form-data",
                        data={campo: (io.BytesIO(png), "../../pwned.png"), "id": "1", "est_id": "1",
                              "matricula": "2023001"})
        fuera = []
        for base in (tmp_path, ROOT):
            for raiz, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in ("venv", ".venv", ".git", "__pycache__", "node_modules")]
                fuera += [os.path.join(raiz, f) for f in files
                          if "pwned" in f and not os.path.join(raiz, f).startswith(str(destino))]
        assert not fuera, f"archivo escrito fuera del directorio de fotos: {fuera}"

    @pytest.mark.live
    @pytest.mark.parametrize("payload", ["..%2f..%2fshared%2frfid.db", "%2e%2e%2f%2e%2e%2fshared%2frfid.db",
                                         "..%252f..%252f.env", "..%2f..%2f..%2f..%2fetc%2fpasswd"])
    def test_en_vivo_via_nginx_no_expone_archivos(self, live, payload):
        h = CFG["nginx_host"]
        for host_port, tls in ((CFG["dash_https_port"], True), (CFG["dash_http_port"], False)):
            status, cuerpo = syslib.raw_get(h, host_port, "/fotos/" + payload, tls=tls)
            assert b"SQLite format 3" not in cuerpo and b"ADMIN_PASSWORD" not in cuerpo \
                and b"root:x:0:0" not in cuerpo, f"puerto {host_port} expone archivos con {payload!r}"
