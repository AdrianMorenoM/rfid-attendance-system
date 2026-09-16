"""
conftest.py — fixtures compartidos para toda la suite RFID.
"""
import os, sys, sqlite3, tempfile, pytest, base64

# ── Ajustar el path para importar los módulos del proyecto ──────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.dirname(_HERE)
_ROOT   = os.path.dirname(_SHARED)
_CRUD   = os.path.join(_ROOT, "crud")
_DASH   = os.path.join(_ROOT, "dashboard")

for p in (_SHARED, _CRUD, _DASH, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Schema SQL ───────────────────────────────────────────────────────────────
_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS estudiantes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT NOT NULL,
    apellido_paterno TEXT NOT NULL,
    apellido_materno TEXT,
    matricula        TEXT UNIQUE NOT NULL,
    carrera          TEXT DEFAULT 'ITIC''s',
    semestre         INTEGER DEFAULT 1,
    grupo            TEXT DEFAULT '',
    correo           TEXT,
    estado           TEXT DEFAULT 'activo' CHECK(estado IN ('activo','inactivo')),
    foto             TEXT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tarjetas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT UNIQUE NOT NULL,
    id_estudiante INTEGER REFERENCES estudiantes(id) ON DELETE SET NULL,
    activa        INTEGER DEFAULT 1 CHECK(activa IN (0,1)),
    asignada_en   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS registros_asistencia (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante INTEGER REFERENCES estudiantes(id) ON DELETE SET NULL,
    uid           TEXT NOT NULL,
    timestamp     DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_dia     TEXT NOT NULL,
    tipo_evento   TEXT NOT NULL CHECK(tipo_evento IN
                      ('aceptado','rebote','ya_escaneado','desconocido','entrada')),
    mensaje       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ip        TEXT,
    accion    TEXT NOT NULL,
    detalle   TEXT,
    resultado TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reg_fecha   ON registros_asistencia(fecha_dia);
CREATE INDEX IF NOT EXISTS idx_reg_uid     ON registros_asistencia(uid);
CREATE INDEX IF NOT EXISTS idx_tarj_uid    ON tarjetas(uid);
CREATE INDEX IF NOT EXISTS idx_est_estado  ON estudiantes(estado);
CREATE INDEX IF NOT EXISTS idx_reg_fecha_evento ON registros_asistencia(fecha_dia, tipo_evento);
"""


def _build_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.execute("""
        INSERT INTO estudiantes
            (nombre, apellido_paterno, matricula, carrera, semestre, grupo, estado)
        VALUES
            ('Juan',  'Pérez',   '2023001', 'ITIC''s', 3, 'A', 'activo'),
            ('María', 'López',   '2023002', 'ITIC''s', 3, 'A', 'activo'),
            ('Pedro', 'Gómez',   '2023003', 'ITIC''s', 5, 'B', 'inactivo'),
            ('Ana',   'Martínez','2023004', 'ITIC''s', 1, 'A', 'activo')
    """)
    conn.execute("""
        INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES
            ('AABBCCDD', 1, 1),
            ('11223344', 2, 1),
            ('DEADBEEF', 3, 1),
            ('CAFEBABE', 4, 0)
    """)
    conn.commit()
    conn.close()


@pytest.fixture(scope="function")
def tmp_db(tmp_path):
    db_path = str(tmp_path / "rfid_test.db")
    _build_db(db_path)
    yield db_path


@pytest.fixture(scope="function")
def crud_app(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin12345")
    monkeypatch.setenv("ALLOWED_SUBNET", "disabled")
    monkeypatch.setenv("ALLOW_HTTP_MIGRATIONS", "true")

    import importlib, sys
    sys.modules.pop("app_crud", None)
    import app_crud as crud_module

    crud_module.BASIC_AUTH_USER = "admin"
    crud_module.BASIC_AUTH_PASSWORD = "admin12345"

    crud_module.DB = tmp_db
    crud_module.BACKUP_DIR = str(tmp_path / "backups")
    os.makedirs(crud_module.BACKUP_DIR, exist_ok=True)
    crud_module._schema_cache.clear()

    crud_module.app.config["TESTING"] = True
    with crud_module.app.test_client() as client:
        yield client, crud_module


@pytest.fixture(scope="function")
def dash_app(tmp_db, monkeypatch):
    import importlib
    import app_dashboard as dash_module
    importlib.reload(dash_module)

    dash_module.DB = tmp_db
    dash_module._schema.clear()

    dash_module.app.config["TESTING"] = True
    with dash_module.app.test_client() as client:
        yield client, dash_module


def basic_auth_headers(user="admin", password="admin12345") -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "X-Requested-With": "XMLHttpRequest",
    }
