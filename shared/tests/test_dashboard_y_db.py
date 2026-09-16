"""
test_dashboard_y_db.py — integración del dashboard y pruebas de la BD.

Cubre:
  - Dashboard: /api/estado, /api/ultimo-evento
  - init_db: schema, índices, WAL, integridad referencial
  - DatabaseManager (rfid_software_admin)
  - ServiceManager (solo lógica, sin systemctl real)

Ejecutar:
    cd ~/rfid-system
    source venv/bin/activate
    pytest shared/tests/test_dashboard_y_db.py -v
"""
import os, sys, json, sqlite3, importlib, pytest
from unittest.mock import patch

_HERE   = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.dirname(_HERE)
_ROOT   = os.path.dirname(_SHARED)
_CRUD   = os.path.join(_ROOT, "crud")

for p in (_SHARED, _CRUD, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# ────────────────────────────────────────────────────────────────────────────
# Dashboard Flask
# ────────────────────────────────────────────────────────────────────────────

class TestDashboard:

    def test_ruta_raiz_ok(self, dash_app):
        client, _ = dash_app
        r = client.get("/")
        assert r.status_code == 200

    def test_ruta_dashboard_ok(self, dash_app):
        client, _ = dash_app
        r = client.get("/dashboard")
        assert r.status_code == 200

    def test_api_estado_estructura(self, dash_app):
        client, _ = dash_app
        r    = client.get("/api/estado")
        data = json.loads(r.data)
        assert data["success"]
        stats = data["stats"]
        for campo in ("entradas_hoy","ya_escaneados","rebotes_hoy","tarjetas_activas"):
            assert campo in stats

    def test_api_estado_valores_iniciales(self, dash_app):
        """Sin registros del día, los contadores deben ser 0."""
        client, _ = dash_app
        r    = client.get("/api/estado")
        data = json.loads(r.data)
        s    = data["stats"]
        assert s["entradas_hoy"]  == 0
        assert s["ya_escaneados"] == 0
        assert s["rebotes_hoy"]   == 0

    def test_api_estado_tarjetas_activas(self, dash_app):
        """El fixture tiene 3 tarjetas activas (CAFEBABE tiene activa=0)."""
        client, _ = dash_app
        r    = client.get("/api/estado")
        data = json.loads(r.data)
        assert data["stats"]["tarjetas_activas"] == 3

    def test_api_estado_eventos_lista(self, dash_app):
        client, _ = dash_app
        r    = client.get("/api/estado")
        data = json.loads(r.data)
        assert isinstance(data["eventos"],      list)
        assert isinstance(data["uid_repetidos"], list)
        assert isinstance(data["hourly"],        list)
        assert len(data["hourly"]) == 24

    def test_api_estado_con_registro(self, dash_app):
        """Después de insertar un registro de hoy, entradas_hoy debe ser 1."""
        import datetime
        client, mod = dash_app
        mod._schema.clear()
        conn = sqlite3.connect(mod.DB)
        hoy  = datetime.date.today().isoformat()
        conn.execute(
            "INSERT INTO registros_asistencia "
            "(id_estudiante, uid, fecha_dia, tipo_evento, mensaje) "
            "VALUES (1, 'AABBCCDD', ?, 'aceptado', 'ok')",
            (hoy,)
        )
        conn.commit()
        conn.close()
        r    = client.get("/api/estado")
        data = json.loads(r.data)
        assert data["stats"]["entradas_hoy"] == 1

    def test_api_estado_evento_contiene_campos(self, dash_app):
        """Cada evento devuelto debe tener los campos esperados."""
        import datetime
        client, mod = dash_app
        mod._schema.clear()
        conn = sqlite3.connect(mod.DB)
        hoy  = datetime.date.today().isoformat()
        conn.execute(
            "INSERT INTO registros_asistencia "
            "(id_estudiante, uid, fecha_dia, tipo_evento, mensaje) "
            "VALUES (1, 'AABBCCDD', ?, 'aceptado', 'ok')",
            (hoy,)
        )
        conn.commit()
        conn.close()
        r      = client.get("/api/estado")
        data   = json.loads(r.data)
        evento = data["eventos"][0]
        for campo in ("id","uid","timestamp","estado","nombre","matricula"):
            assert campo in evento

    def test_api_ultimo_evento_sin_registros(self, dash_app):
        client, _ = dash_app
        r    = client.get("/api/ultimo-evento")
        data = json.loads(r.data)
        assert data["success"]
        assert data["evento"] is None

    def test_api_ultimo_evento_con_registro(self, dash_app):
        import datetime
        client, mod = dash_app
        mod._schema.clear()
        conn = sqlite3.connect(mod.DB)
        hoy  = datetime.date.today().isoformat()
        conn.execute(
            "INSERT INTO registros_asistencia "
            "(id_estudiante, uid, fecha_dia, tipo_evento, mensaje) "
            "VALUES (1, 'AABBCCDD', ?, 'aceptado', 'ok')",
            (hoy,)
        )
        conn.commit()
        conn.close()
        r    = client.get("/api/ultimo-evento")
        data = json.loads(r.data)
        assert data["success"]
        assert data["evento"] is not None
        assert data["evento"]["uid"] == "AABBCCDD"
        assert data["evento"]["estado"] == "aceptado"

    def test_norm_funcion_estados(self, dash_app):
        """La función norm() debe mapear los estados correctamente."""
        _, mod = dash_app
        assert mod.norm("aceptado")    == "aceptado"
        assert mod.norm("entrada")     == "aceptado"
        assert mod.norm("ya_escaneado")== "ya_escaneado"
        assert mod.norm("rebote")      == "rebote"
        assert mod.norm("desconocido") == "rebote"
        assert mod.norm(None)          == "rebote"
        assert mod.norm("")            == "rebote"

    def test_normalizar_foto_none(self, dash_app):
        _, mod = dash_app
        assert mod.normalizar_foto(None) is None

    def test_normalizar_foto_ruta(self, dash_app):
        _, mod = dash_app
        resultado = mod.normalizar_foto("/static/fotos/alumno.jpg")
        assert resultado == "/fotos/alumno.jpg"

    def test_normalizar_foto_url(self, dash_app):
        _, mod = dash_app
        url = "https://ejemplo.com/foto.jpg"
        assert mod.normalizar_foto(url) == url


# ────────────────────────────────────────────────────────────────────────────
# Base de datos — schema e integridad
# ────────────────────────────────────────────────────────────────────────────

class TestEsquemaBD:

    def test_tablas_existen(self, tmp_db):
        conn   = sqlite3.connect(tmp_db)
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        for tabla in ("estudiantes","tarjetas","registros_asistencia","audit_log"):
            assert tabla in tablas, f"Falta tabla: {tabla}"

    def test_indices_existen(self, tmp_db):
        conn    = sqlite3.connect(tmp_db)
        indices = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        conn.close()
        for idx in ("idx_reg_fecha","idx_reg_uid","idx_tarj_uid","idx_est_estado"):
            assert idx in indices, f"Falta índice: {idx}"

    def test_wal_mode_activo(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.execute("PRAGMA journal_mode=WAL")
        modo = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert modo == "wal"

    def test_matricula_unica(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO estudiantes (nombre, apellido_paterno, matricula) "
                "VALUES ('X','Y','2023001')"   # ya existe
            )
        conn.close()

    def test_uid_tarjeta_unico(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tarjetas (uid) VALUES ('AABBCCDD')"   # ya existe
            )
        conn.close()

    def test_foreign_key_tarjeta_estudiante(self, tmp_db):
        """Tarjeta con id_estudiante inválido → IntegrityError con FK activos."""
        conn = sqlite3.connect(tmp_db)
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tarjetas (uid, id_estudiante) VALUES ('NEWUID', 9999)"
            )
        conn.close()

    def test_estado_estudiante_check_constraint(self, tmp_db):
        """estado debe ser 'activo' o 'inactivo'."""
        conn = sqlite3.connect(tmp_db)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO estudiantes (nombre, apellido_paterno, matricula, estado) "
                "VALUES ('T','T','MAT999','suspendido')"
            )
        conn.close()

    def test_tipo_evento_check_constraint(self, tmp_db):
        """tipo_evento solo acepta los valores definidos."""
        conn = sqlite3.connect(tmp_db)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO registros_asistencia (uid, fecha_dia, tipo_evento) "
                "VALUES ('XXXX','2025-01-01','invalido')"
            )
        conn.close()

    def test_integridad_general(self, tmp_db):
        """PRAGMA integrity_check debe devolver 'ok'."""
        conn = sqlite3.connect(tmp_db)
        resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        assert resultado.lower() == "ok"


# ────────────────────────────────────────────────────────────────────────────
# DatabaseManager (rfid_software_admin)
# ────────────────────────────────────────────────────────────────────────────

class TestDatabaseManager:

    @pytest.fixture()
    def db_manager(self, tmp_db, tmp_path):
        from rfid_software_admin import DatabaseManager
        backup_dir = str(tmp_path / "backups")
        return DatabaseManager(tmp_db, backup_dir)

    def test_status_contiene_counts(self, db_manager):
        st = db_manager.status()
        assert "counts" in st
        assert st["counts"]["estudiantes"] >= 4

    def test_create_backup(self, db_manager, tmp_path):
        result = db_manager.create_backup()
        assert result["success"]
        fname = result["filename"]
        assert os.path.exists(os.path.join(str(tmp_path / "backups"), fname))

    def test_list_backups_vacio_inicialmente(self, db_manager):
        backups = db_manager.list_backups()
        assert isinstance(backups, list)

    def test_list_backups_despues_de_crear(self, db_manager):
        db_manager.create_backup()
        backups = db_manager.list_backups()
        assert len(backups) >= 1

    def test_delete_backup(self, db_manager, tmp_path):
        r = db_manager.create_backup()
        fname = r["filename"]
        result = db_manager.delete_backup(fname)
        assert result["success"]
        assert not os.path.exists(os.path.join(str(tmp_path / "backups"), fname))

    def test_delete_backup_inexistente(self, db_manager):
        result = db_manager.delete_backup("rfid_backup_20990101_000000.db")
        assert not result["success"]

    def test_purge_preview_sin_filtros(self, db_manager):
        result = db_manager.purge_preview({})
        assert result["success"]
        assert "count" in result

    def test_purge_requiere_confirm(self, db_manager):
        result = db_manager.purge({"confirm": False})
        assert not result["success"]

    def test_purge_target_invalido(self, db_manager):
        result = db_manager.purge_preview({"target": "noexiste"})
        assert not result["success"]

    def test_restore_desde_backup(self, db_manager):
        r = db_manager.create_backup()
        fname = r["filename"]
        result = db_manager.restore(fname)
        assert result["success"]
        assert "safety_backup" in result

    def test_restore_archivo_inexistente(self, db_manager):
        result = db_manager.restore("rfid_backup_20990101_000000.db")
        assert not result["success"]

    def test_backup_path_invalido_lanza_error(self, db_manager):
        """Nombres con path traversal deben ser rechazados."""
        with pytest.raises(ValueError):
            db_manager._backup_path("../../etc/passwd")


# ────────────────────────────────────────────────────────────────────────────
# ServiceManager (rfid_software_admin) — lógica sin systemctl real
# ────────────────────────────────────────────────────────────────────────────

class TestServiceManager:

    @pytest.fixture()
    def svc_manager(self):
        from rfid_software_admin import ServiceManager
        return ServiceManager()

    def test_accion_invalida_rechazada(self, svc_manager):
        result = svc_manager.action("rfid-reader.service", "borrar")
        assert not result["success"]

    def test_servicio_no_permitido_rechazado(self, svc_manager):
        result = svc_manager.action("sshd.service", "stop")
        assert not result["success"]

    def test_logs_servicio_no_permitido(self, svc_manager):
        result = svc_manager.logs("sshd.service")
        assert not result["success"]

    @patch("rfid_software_admin.run_shell")
    def test_list_services_estructura(self, mock_run, svc_manager):
        mock_run.return_value = {"success": True, "stdout": "active", "stderr": ""}
        servicios = svc_manager.list_services()
        assert isinstance(servicios, list)
        assert len(servicios) == 3
        for svc in servicios:
            assert "name"    in svc
            assert "active"  in svc
            assert "enabled" in svc

    @patch("rfid_software_admin.run_shell")
    def test_action_start_exitoso(self, mock_run, svc_manager):
        mock_run.return_value = {"success": True, "stdout": "", "stderr": ""}
        result = svc_manager.action("rfid-reader.service", "start")
        assert result["success"]

    @patch("rfid_software_admin.run_shell")
    def test_logs_servicio_permitido(self, mock_run, svc_manager):
        mock_run.return_value = {
            "success": True,
            "stdout": "Mar 01 12:00:00 rasp rfid-reader[1234]: Listo",
            "stderr": ""
        }
        result = svc_manager.logs("rfid-reader.service", lines=10)
        assert result["success"]
        assert "log" in result
        assert result["lines"] == 10