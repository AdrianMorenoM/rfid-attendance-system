"""syslib.py — utilidades compartidas por conftest.py y los tests de sistema."""
import base64
import http.client
import json
import os
import re
import sqlite3
import ssl
import subprocess
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHARED, CRUD_DIR, DASH_DIR = ROOT / "shared", ROOT / "crud", ROOT / "dashboard"
REPORTS = HERE / "reports"
LIVE_DB = SHARED / "rfid.db"
LIVE_BACKUPS = SHARED / "backups"
ENV_FILE = ROOT / ".env"
TEST_PWD = "test-admin-password"

UNITS = ["rfid-crud.service", "rfid-dashboard.service", "rfid-reader.service"]
TIMERS = ["rfid-incremental-vacuum.timer", "rfid-cert-renew.timer"]
TABLES = ["estudiantes", "tarjetas", "registros_asistencia", "audit_log", "auth_fail_log"]


# ── Configuración (todo sobreescribible con variables RFID_*) ────────────────
def _c(name, default):
    v = os.environ.get(name)
    return default if v is None else type(default)(v)


CFG = {
    "crud_url": _c("RFID_CRUD_URL", "http://127.0.0.1:5001"),
    "dash_url": _c("RFID_DASH_URL", "http://127.0.0.1:5000"),
    "nginx_host": _c("RFID_NGINX_HOST", "127.0.0.1"),
    "dash_http_port": _c("RFID_DASH_HTTP_PORT", 80),
    "dash_https_port": _c("RFID_DASH_HTTPS_PORT", 443),
    "crud_http_port": _c("RFID_CRUD_HTTP_PORT", 8001),
    "crud_https_port": _c("RFID_CRUD_HTTPS_PORT", 8443),
    "p50_ms": _c("RFID_P50_MS", 1000.0),
    "p95_ms": _c("RFID_P95_MS", 3000.0),
    "max_ms": _c("RFID_MAX_MS", 8000.0),
    "backup_max_age_h": _c("RFID_BACKUP_MAX_AGE_H", 72.0),  # cubre el fin de semana
    "cert_min_days": _c("RFID_CERT_MIN_DAYS", 14),
    "wal_max_mb": _c("RFID_WAL_MAX_MB", 32.0),
    "restart_timeout": _c("RFID_RESTART_TIMEOUT", 45),
    "max_backups": _c("RFID_MAX_BACKUPS", 500),
    "max_fds_por_proceso": _c("RFID_MAX_FDS_DB", 10),
}

# Endpoints de solo lectura y sin parámetros (seguros para pruebas en vivo)
CRUD_GET_SAFE = [
    "/api/estadisticas", "/api/analytics", "/api/hardware/status", "/api/hardware/services",
    "/api/hardware/network/status", "/api/software/services", "/api/software/database/status",
    "/api/health/db", "/api/software/database/backups", "/api/rfid/listen/status",
    "/api/rfid/admin-scan/status", "/api/rfid/desconocidos", "/api/rfid/tarjetas-sin-asignar",
    "/api/rfid/alumnos-sin-tarjeta", "/api/rfid/ultimo-scan", "/api/estudiantes",
    "/api/estudiantes/grupos", "/api/tarjetas", "/api/registros", "/api/audit-log",
    "/api/asistencia/hoy", "/api/export/estudiantes", "/api/export/registros",
]
DASH_GET_SAFE = ["/", "/api/estado", "/api/ultimo-evento"]
# Subconjunto que solo depende de la BD (seguro para ejecutar en proceso con subprocess bloqueado)
CRUD_DB_GETS = [
    "/api/estadisticas", "/api/analytics", "/api/estudiantes", "/api/estudiantes/grupos",
    "/api/tarjetas", "/api/registros", "/api/audit-log", "/api/asistencia/hoy",
    "/api/rfid/desconocidos", "/api/rfid/tarjetas-sin-asignar", "/api/rfid/alumnos-sin-tarjeta",
    "/api/rfid/ultimo-scan",
]


# ── .env y credenciales ──────────────────────────────────────────────────────
def load_env(path=ENV_FILE):
    env = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            env[k] = v
    except OSError:
        pass
    return env


ENV = load_env()


def admin_creds():
    return ENV.get("ADMIN_USER", "admin"), ENV.get("ADMIN_PASSWORD", "")


def basic_header(user, pwd):
    return "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()


def auth_headers(user="admin", pwd=TEST_PWD, xhr=True):
    h = {"Authorization": basic_header(user, pwd)}
    if xhr:
        h["X-Requested-With"] = "XMLHttpRequest"
    return h


def live_session():
    u, p = admin_creds()
    s = requests.Session()
    s.auth = (u, p)
    s.verify = False
    s.headers["X-Requested-With"] = "XMLHttpRequest"
    return s


def raw_get(host, port, path, tls=False, auth=True, timeout=10):
    """GET con el path tal cual (sin que `requests` normalice ../ ni %2e)."""
    if tls:
        conn = http.client.HTTPSConnection(host, port, timeout=timeout,
                                           context=ssl._create_unverified_context())
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    headers = {"Accept": "*/*"}
    if auth:
        headers["Authorization"] = basic_header(*admin_creds())
    try:
        conn.request("GET", path, headers=headers)
        r = conn.getresponse()
        return r.status, r.read(8192)
    finally:
        conn.close()


# ── Shell / systemd ──────────────────────────────────────────────────────────
def sh(cmd, timeout=30, input_=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_)
    except FileNotFoundError:
        return 127, "", f"comando no encontrado: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def show(unit, *props):
    _, out, _ = sh(["systemctl", "show", unit, "--no-pager", *[f"--property={p}" for p in props]])
    d = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def is_active(unit):
    return sh(["systemctl", "is-active", unit])[1] == "active"


def can_sudo(*cmd):
    return sh(["sudo", "-n", "-l", *cmd])[0] == 0


def sudo_systemctl(action, unit):
    return sh(["sudo", "-n", "systemctl", action, unit], timeout=90)


_UN = {"us": 1e-6, "ms": 1e-3, "s": 1, "min": 60, "h": 3600}


def to_seconds(txt):
    """'5s' → 5.0, '100ms' → 0.1, '1min 30s' → 90.0, '0' → 0.0"""
    found = re.findall(r"([\d.]+)\s*(us|ms|min|s|h)", txt or "")
    if found:
        return sum(float(n) * _UN[u] for n, u in found)
    return float(txt) if re.fullmatch(r"[\d.]+", txt or "") else None


def wait_until(pred, timeout=30.0, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def pct(values, p):
    s = sorted(values)
    if not s:
        return 0.0
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def save_perf(key, data):
    REPORTS.mkdir(exist_ok=True)
    f = REPORTS / "perf.json"
    try:
        cur = json.loads(f.read_text())
    except Exception:
        cur = {}
    cur[key] = data
    f.write_text(json.dumps(cur, indent=2))


def listeners():
    """[(direccion, puerto)] de sockets TCP en escucha."""
    _, out, _ = sh(["ss", "-ltnH"])
    res = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and ":" in parts[3]:
            addr, port = parts[3].rsplit(":", 1)
            if port.isdigit():
                res.append((addr, int(port)))
    return res


# ── BD de prueba (esquema idéntico al real, obtenido con `.schema`) ──────────
SCHEMA = """
CREATE TABLE estudiantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
    apellido_paterno TEXT NOT NULL, apellido_materno TEXT,
    matricula TEXT UNIQUE NOT NULL, carrera TEXT DEFAULT 'ITIC''s', semestre INTEGER,
    grupo TEXT DEFAULT '', correo TEXT, estado TEXT DEFAULT 'activo', foto TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE tarjetas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL,
    id_estudiante INTEGER REFERENCES estudiantes(id) ON DELETE SET NULL,
    activa INTEGER DEFAULT 1, asignada_en DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE registros_asistencia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante INTEGER REFERENCES estudiantes(id) ON DELETE SET NULL,
    uid TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_dia TEXT NOT NULL, tipo_evento TEXT NOT NULL, mensaje TEXT DEFAULT '');
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, ip TEXT,
    accion TEXT NOT NULL, detalle TEXT, resultado TEXT NOT NULL);
CREATE TABLE auth_fail_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX idx_reg_fecha ON registros_asistencia(fecha_dia);
CREATE INDEX idx_reg_uid ON registros_asistencia(uid);
CREATE INDEX idx_reg_evento ON registros_asistencia(tipo_evento);
CREATE INDEX idx_reg_timestamp ON registros_asistencia(timestamp);
CREATE INDEX idx_reg_estudiante ON registros_asistencia(id_estudiante);
CREATE INDEX idx_reg_est_fecha ON registros_asistencia(id_estudiante, fecha_dia);
CREATE INDEX idx_tarj_uid ON tarjetas(uid);
CREATE INDEX idx_tarjetas_est ON tarjetas(id_estudiante);
CREATE INDEX idx_est_carrera_sem ON estudiantes(carrera, semestre);
CREATE UNIQUE INDEX idx_tarjeta_activa_unica ON tarjetas(id_estudiante)
    WHERE activa = 1 AND id_estudiante IS NOT NULL;
CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX idx_auth_fail_ip_ts ON auth_fail_log(ip, ts);
"""

# Bytes crudos que devolvería el MFRC522 (4 de UID + 1 de checksum)
CARDS = {
    "juan": [0xAA, 0xBB, 0xCC, 0xDD, 0x00],
    "maria": [0x11, 0x22, 0x33, 0x44, 0x00],
    "pedro": [0xDE, 0xAD, 0xBE, 0xEF, 0x00],
    "ana": [0xCA, 0xFE, 0xBA, 0xBE, 0x00],
    "nadie": [0x01, 0x02, 0x03, 0x04, 0x00],
}


def uid_from_bytes(b):
    return str(int.from_bytes(bytes(b[:4]), "big"))  # igual que rfid_reader.leer_uid


UID = {k: uid_from_bytes(v) for k, v in CARDS.items()}


def build_db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO estudiantes (nombre, apellido_paterno, matricula, semestre, grupo, estado)"
        " VALUES (?,?,?,?,?,?)",
        [("Juan", "Pérez", "2023001", 3, "A", "activo"),
         ("María", "López", "2023002", 3, "A", "activo"),
         ("Pedro", "Gómez", "2023003", 5, "B", "inactivo"),
         ("Ana", "Martínez", "2023004", 1, "A", "activo")])
    conn.executemany(
        "INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES (?,?,?)",
        [(UID["juan"], 1, 1), (UID["maria"], 2, 1), (UID["pedro"], 3, 1), (UID["ana"], 4, 0)])
    conn.commit()
    conn.close()


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def table_counts(path):
    c = ro(path)
    try:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        c.close()


def dump_table(path, table):
    c = ro(path)
    try:
        return c.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    finally:
        c.close()


def integrity_ok(path):
    c = ro(path)
    try:
        return c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        c.close()


class FakeMFRC522:
    """Lector RC522 simulado: mismo contrato que usa rfid_reader.leer_uid()."""
    PICC_REQIDL = 0x26
    MI_OK, MI_NOTAGERR, MI_ERR = 0, 1, 2

    def __init__(self, card=None, anticoll_status=0):
        self.card, self.anticoll_status = card, anticoll_status

    def MFRC522_Request(self, mode):
        return (self.MI_OK if self.card is not None else self.MI_NOTAGERR), None

    def MFRC522_Anticoll(self):
        if self.card is None:
            return self.MI_NOTAGERR, None
        return self.anticoll_status, self.card
