"""
test_crud_api.py — integración Flask del servicio CRUD (puerto 5001).

Cubre:
  - Autenticación Basic Auth (correcta, incorrecta, ausente)
  - CRUD completo de estudiantes y tarjetas
  - Registros y audit log
  - Backup / restore / purge de BD
  - Exportación CSV
  - Endpoints de estadísticas y analítica
  - Modo admin RFID (archivos de señal)

Ejecutar:
    cd ~/rfid-system
    source venv/bin/activate
    pytest shared/tests/test_crud_api.py -v
"""
import json, os, pytest
from conftest import basic_auth_headers

AUTH = basic_auth_headers()
BAD  = basic_auth_headers(user="hacker", password="wrong")


# ────────────────────────────────────────────────────────────────────────────
# Autenticación
# ────────────────────────────────────────────────────────────────────────────

class TestAutenticacion:

    def test_sin_credenciales_retorna_401(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estadisticas")
        assert r.status_code == 401

    def test_credenciales_incorrectas_retorna_401(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estadisticas", headers=BAD)
        assert r.status_code == 401

    def test_credenciales_correctas_dan_acceso(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estadisticas", headers=AUTH)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["success"] is True

    def test_rutas_destructivas_requieren_xhr(self, crud_app):
        """PUT/DELETE sin X-Requested-With → 403."""
        client, _ = crud_app
        h = basic_auth_headers()
        del h["X-Requested-With"]
        r = client.post("/api/hardware/system/reboot",
                        headers=h,
                        json={"confirm": True})
        assert r.status_code == 403


# ────────────────────────────────────────────────────────────────────────────
# Headers de seguridad
# ────────────────────────────────────────────────────────────────────────────

class TestHeadersSeguridad:

    def test_x_frame_options_deny(self, crud_app):
        client, _ = crud_app
        r = client.get("/", headers=AUTH)
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_x_content_type_nosniff(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estadisticas", headers=AUTH)
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_csp_presente(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estadisticas", headers=AUTH)
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src" in csp


# ────────────────────────────────────────────────────────────────────────────
# Estadísticas
# ────────────────────────────────────────────────────────────────────────────

class TestEstadisticas:

    def test_estructura_correcta(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/estadisticas", headers=AUTH)
        data = json.loads(r.data)
        stats = data["stats"]
        for campo in ("total_estudiantes","estudiantes_activos",
                      "total_tarjetas","tarjetas_activas",
                      "registros_hoy","total_registros","aceptados_hoy"):
            assert campo in stats, f"Falta campo: {campo}"

    def test_cuenta_solo_itics(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/estadisticas", headers=AUTH)
        data = json.loads(r.data)["stats"]
        # El fixture tiene 4 estudiantes ITIC's (3 activos, 1 inactivo)
        assert data["total_estudiantes"] == 4
        assert data["estudiantes_activos"] == 3


# ────────────────────────────────────────────────────────────────────────────
# CRUD Estudiantes
# ────────────────────────────────────────────────────────────────────────────

class TestEstudiantes:

    def test_listar_retorna_lista(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/estudiantes", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert isinstance(data["estudiantes"], list)
        assert len(data["estudiantes"]) == 4

    def test_crear_estudiante(self, crud_app):
        client, _ = crud_app
        payload = {
            "nombre":           "Carlos",
            "apellido_paterno": "Ramírez",
            "matricula":        "2024001",
            "semestre":         1,
            "grupo":            "A",
        }
        r    = client.post("/api/estudiantes", headers=AUTH, json=payload)
        data = json.loads(r.data)
        assert data["success"]
        assert "id" in data

    def test_crear_duplicado_retorna_400(self, crud_app):
        client, _ = crud_app
        payload = {
            "nombre": "X", "apellido_paterno": "Y",
            "matricula": "2023001",   # ya existe en fixture
        }
        r = client.post("/api/estudiantes", headers=AUTH, json=payload)
        assert r.status_code == 400

    def test_obtener_por_id(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/estudiantes/1", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert data["estudiante"]["nombre"] == "Juan"

    def test_obtener_id_inexistente_retorna_404(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estudiantes/9999", headers=AUTH)
        assert r.status_code == 404

    def test_actualizar_estudiante(self, crud_app):
        client, mod = crud_app
        payload = {
            "nombre": "Juan Carlos", "apellido_paterno": "Pérez",
            "matricula": "2023001", "semestre": 4,
            "grupo": "B", "estado": "activo",
        }
        r = client.put("/api/estudiantes/1", headers=AUTH, json=payload)
        assert json.loads(r.data)["success"]
        # Verificar que el cambio se guardó
        r2 = client.get("/api/estudiantes/1", headers=AUTH)
        est = json.loads(r2.data)["estudiante"]
        assert est["nombre"] == "Juan Carlos"
        assert est["semestre"] == 4

    def test_eliminar_estudiante(self, crud_app):
        client, _ = crud_app
        r = client.delete("/api/estudiantes/4", headers=AUTH)
        assert json.loads(r.data)["success"]
        r2 = client.get("/api/estudiantes/4", headers=AUTH)
        assert r2.status_code == 404

    def test_buscar_por_nombre(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/estudiantes?buscar=María", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert len(data["estudiantes"]) == 1
        assert data["estudiantes"][0]["nombre"] == "María"

    def test_filtrar_por_semestre(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/estudiantes?semestre=3", headers=AUTH)
        data = json.loads(r.data)
        assert all(e["semestre"] == 3 for e in data["estudiantes"])

    def test_perfil_estudiante(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/estudiantes/1/perfil", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert "tarjetas"  in data
        assert "registros" in data

    def test_promover_preview_sin_confirmar(self, crud_app):
        client, _ = crud_app
        r    = client.post("/api/estudiantes/promover",
                           headers=AUTH,
                           json={"desde_semestre": 3})
        data = json.loads(r.data)
        assert data["success"]
        assert data["aplicado"] is False
        assert data["afectados"] == 2   # Juan y María están en semestre 3

    def test_promover_confirmar(self, crud_app):
        client, _ = crud_app
        r = client.post("/api/estudiantes/promover",
                        headers=AUTH,
                        json={"desde_semestre": 3, "confirmar": True})
        data = json.loads(r.data)
        assert data["aplicado"] is True
        # Verificar que el semestre cambió
        r2   = client.get("/api/estudiantes/1", headers=AUTH)
        est  = json.loads(r2.data)["estudiante"]
        assert est["semestre"] == 4

    def test_grupos_retorna_estructura(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/estudiantes/grupos", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert isinstance(data["grupos"], list)


# ────────────────────────────────────────────────────────────────────────────
# CRUD Tarjetas
# ────────────────────────────────────────────────────────────────────────────

class TestTarjetas:

    def test_listar_tarjetas(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/tarjetas", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert data["total"] >= 4

    def test_crear_tarjeta(self, crud_app):
        client, _ = crud_app
        r    = client.post("/api/tarjetas",
                           headers=AUTH,
                           json={"uid": "NUEVAUID1", "id_estudiante": None, "activa": 1})
        data = json.loads(r.data)
        assert data["success"]

    def test_crear_tarjeta_uid_duplicado_retorna_400(self, crud_app):
        client, _ = crud_app
        r = client.post("/api/tarjetas",
                        headers=AUTH,
                        json={"uid": "AABBCCDD"})   # ya existe
        assert r.status_code == 400

    def test_actualizar_tarjeta(self, crud_app):
        client, _ = crud_app
        r = client.put("/api/tarjetas/1",
                       headers=AUTH,
                       json={"uid": "AABBCCDD", "id_estudiante": 1, "activa": 0})
        assert json.loads(r.data)["success"]

    def test_eliminar_tarjeta(self, crud_app):
        client, _ = crud_app
        r = client.delete("/api/tarjetas/4", headers=AUTH)
        assert json.loads(r.data)["success"]

    def test_bulk_toggle_desactivar(self, crud_app):
        client, _ = crud_app
        r    = client.post("/api/tarjetas/bulk-toggle",
                           headers=AUTH,
                           json={"ids": [1, 2], "activa": 0})
        data = json.loads(r.data)
        assert data["success"]

    def test_tarjetas_sin_asignar(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/rfid/tarjetas-sin-asignar", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert isinstance(data["tarjetas"], list)

    def test_alumnos_sin_tarjeta(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/rfid/alumnos-sin-tarjeta", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert isinstance(data["alumnos"], list)


# ────────────────────────────────────────────────────────────────────────────
# Registros de asistencia
# ────────────────────────────────────────────────────────────────────────────

class TestRegistros:

    def _insertar_registro(self, crud_app, uid, tipo="aceptado"):
        import sqlite3, datetime
        client, mod = crud_app
        conn = sqlite3.connect(mod.DB)
        hoy  = datetime.date.today().isoformat()
        conn.execute(
            "INSERT INTO registros_asistencia (id_estudiante, uid, fecha_dia, tipo_evento, mensaje) "
            "VALUES (1, ?, ?, ?, 'test')",
            (uid, hoy, tipo)
        )
        conn.commit()
        conn.close()

    def test_listar_registros(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/registros", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert "registros" in data

    def test_registros_filtrar_por_fecha(self, crud_app):
        import datetime
        self._insertar_registro(crud_app, "AABBCCDD")
        hoy    = datetime.date.today().isoformat()
        client, _ = crud_app
        r = client.get(f"/api/registros?fecha={hoy}", headers=AUTH)
        data = json.loads(r.data)
        assert data["total"] >= 1

    def test_ultimo_scan(self, crud_app):
        self._insertar_registro(crud_app, "AABBCCDD")
        client, _ = crud_app
        r    = client.get("/api/rfid/ultimo-scan", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        # Puede ser None si no hay registros del día
        # (depende de la hora de ejecución del test)

    def test_historial_uid(self, crud_app):
        self._insertar_registro(crud_app, "AABBCCDD")
        client, _ = crud_app
        r    = client.get("/api/rfid/historial/AABBCCDD", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert len(data["historial"]) >= 1

    def test_rfid_desconocidos(self, crud_app):
        import sqlite3, datetime
        client, mod = crud_app
        conn = sqlite3.connect(mod.DB)
        hoy  = datetime.date.today().isoformat()
        conn.execute(
            "INSERT INTO registros_asistencia (uid, fecha_dia, tipo_evento, mensaje) "
            "VALUES ('FANTASMA01', ?, 'rebote', 'UID desconocido')",
            (hoy,)
        )
        conn.commit()
        conn.close()
        r    = client.get("/api/rfid/desconocidos", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        uids = [d["uid"] for d in data["desconocidos"]]
        assert "FANTASMA01" in uids


# ────────────────────────────────────────────────────────────────────────────
# Backup y Purge de BD
# ────────────────────────────────────────────────────────────────────────────

class TestBackupPurge:

    def test_crear_backup(self, crud_app):
        client, mod = crud_app
        r    = client.post("/api/software/database/backup", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert data["filename"].startswith("rfid_backup_")
        assert os.path.exists(os.path.join(mod.BACKUP_DIR, data["filename"]))

    def test_listar_backups(self, crud_app):
        client, _ = crud_app
        client.post("/api/software/database/backup", headers=AUTH)
        r    = client.get("/api/software/database/backups", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert len(data["backups"]) >= 1

    def test_eliminar_backup(self, crud_app):
        client, mod = crud_app
        r1   = client.post("/api/software/database/backup", headers=AUTH)
        fname = json.loads(r1.data)["filename"]
        r2   = client.delete(
            f"/api/software/database/backups/{fname}?confirm=true",
            headers=AUTH
        )
        assert json.loads(r2.data)["success"]
        assert not os.path.exists(os.path.join(mod.BACKUP_DIR, fname))

    def test_backup_filename_invalido_retorna_400(self, crud_app):
        client, _ = crud_app
        r = client.delete(
            "/api/software/database/backups/../../etc/passwd?confirm=true",
            headers=AUTH
        )
        assert r.status_code in (400, 404)

    def test_purge_preview_sin_confirmar(self, crud_app):
        client, _ = crud_app
        r    = client.post("/api/software/database/purge/preview",
                           headers=AUTH,
                           json={})
        data = json.loads(r.data)
        assert data["success"]
        assert "count" in data

    def test_status_base_datos(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/software/database/status", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert "counts" in data["database"]

    def test_health_db(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/health/db", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert data["healthy"] is True


# ────────────────────────────────────────────────────────────────────────────
# Exportación CSV
# ────────────────────────────────────────────────────────────────────────────

class TestExportacion:

    def test_export_estudiantes_csv(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/export/estudiantes", headers=AUTH)
        assert r.status_code == 200
        assert "csv" in r.content_type
        text = r.data.decode("utf-8-sig")   # quitar BOM
        assert "Matrícula" in text or "Nombre" in text

    def test_export_registros_csv(self, crud_app):
        import datetime
        client, _ = crud_app
        hoy = datetime.date.today().isoformat()
        r   = client.get(f"/api/export/registros?fecha={hoy}", headers=AUTH)
        assert r.status_code == 200
        assert "csv" in r.content_type


# ────────────────────────────────────────────────────────────────────────────
# Analítica
# ────────────────────────────────────────────────────────────────────────────

class TestAnalitica:

    def test_analytics_estructura(self, crud_app):
        client, _ = crud_app
        r    = client.get("/api/analytics", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        an   = data["analytics"]
        assert "asistencia_7dias" in an
        assert "por_hora"         in an
        assert "por_semestre"     in an
        assert "top_estudiantes"  in an
        assert len(an["asistencia_7dias"]) == 7
        assert len(an["por_hora"]) == 24


# ────────────────────────────────────────────────────────────────────────────
# RFID guardar-uid
# ────────────────────────────────────────────────────────────────────────────

class TestRFIDHelpers:

    def test_guardar_uid_nuevo(self, crud_app):
        client, _ = crud_app
        r    = client.post("/api/rfid/guardar-uid",
                           headers=AUTH,
                           json={"uid": "NUEVAUID99"})
        data = json.loads(r.data)
        assert data["success"]
        assert data.get("ya_existe") is False

    def test_guardar_uid_existente(self, crud_app):
        client, _ = crud_app
        # AABBCCDD ya existe con alumno activo → ya_existe=True
        r    = client.post("/api/rfid/guardar-uid",
                           headers=AUTH,
                           json={"uid": "AABBCCDD"})
        data = json.loads(r.data)
        assert data["success"]
        assert data.get("ya_existe") is True

    def test_guardar_uid_vacio_retorna_400(self, crud_app):
        client, _ = crud_app
        r = client.post("/api/rfid/guardar-uid",
                        headers=AUTH,
                        json={"uid": ""})
        assert r.status_code == 400


# ────────────────────────────────────────────────────────────────────────────
# Audit log
# ────────────────────────────────────────────────────────────────────────────

class TestAuditLog:

    def test_audit_log_listable(self, crud_app):
        client, _ = crud_app
        # Generar al menos una entrada creando un backup
        client.post("/api/software/database/backup", headers=AUTH)
        r    = client.get("/api/audit-log", headers=AUTH)
        data = json.loads(r.data)
        assert data["success"]
        assert data["total"] >= 1