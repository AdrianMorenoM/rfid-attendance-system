import sqlite3
"""
test_crud_api.py — integración Flask del servicio CRUD (puerto 5001).

Cubre:
  - Autenticación Basic Auth
  - CRUD completo de estudiantes y tarjetas
  - Registros y audit log
  - Backup / restore / purge de BD
  - Exportación CSV
  - Endpoints de estadísticas y analítica
  - Modo admin RFID
"""

import io
import json
import os
import sqlite3

import pytest

from unittest.mock import MagicMock, patch

from conftest import basic_auth_headers

AUTH = basic_auth_headers()
BAD  = basic_auth_headers(user="hacker", password="wrong")

RFID_SERVICES = (
    "rfid-crud.service",
    "rfid-dashboard.service",
    "rfid-reader.service",
)


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

    def test_claves_presentes(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estadisticas", headers=AUTH)
        data = r.get_json()
        stats = data["stats"]
        esperadas = {
            "total_estudiantes",
            "estudiantes_activos",
            "total_tarjetas",
            "tarjetas_activas",
            "registros_hoy",
            "total_registros",
            "aceptados_hoy",
        }
        assert esperadas.issubset(stats.keys())

    def test_activos_menor_o_igual_total(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estadisticas", headers=AUTH)
        stats = r.get_json()["stats"]
        assert stats["estudiantes_activos"] <= stats["total_estudiantes"]

    def test_tarjetas_activas_menor_o_igual_total(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estadisticas", headers=AUTH)
        stats = r.get_json()["stats"]
        assert stats["tarjetas_activas"] <= stats["total_tarjetas"]

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
    def test_asistencia_7dias_tiene_7_entradas(self, client):
        r = client.get('/api/analytics', headers=AUTH)
        analytics = r.get_json()['analytics']
        assert len(analytics['asistencia_7dias']) == 7

    def test_por_hora_tiene_24_entradas(self, client):
        r = client.get('/api/analytics', headers=AUTH)
        analytics = r.get_json()['analytics']
        assert len(analytics['por_hora']) == 24

    def test_cada_hora_tiene_campos_correctos(self, client):
        r = client.get('/api/analytics', headers=AUTH)
        por_hora = r.get_json()['analytics']['por_hora']
        for entrada in por_hora:
            assert 'hora' in entrada
            assert 'aceptados' in entrada
            assert 'total' in entrada
            assert 0 <= entrada['hora'] <= 23

    def test_mes_total_es_entero_no_negativo(self, client):
        r = client.get('/api/analytics', headers=AUTH)
        mes_total = r.get_json()['analytics']['mes_total']
        assert isinstance(mes_total, int)
        assert mes_total >= 0


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

# ────────────────────────────────────────────────────────────────────────────
# /api/migrate
# ────────────────────────────────────────────────────────────────────────────

class TestMigrate:

    def test_migrate_ok(self, crud_app):
        client, mod = crud_app
        mod.ALLOW_HTTP_MIGRATIONS = True
        r = client.post('/api/migrate',
                        headers=basic_auth_headers('admin', 'test-admin-password'))
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert isinstance(data['results'], list)

    def test_migrate_deshabilitado_devuelve_404(self, crud_app, monkeypatch):
        client, mod = crud_app
        # Parchear tanto el módulo como el entorno
        monkeypatch.setattr(mod, 'ALLOW_HTTP_MIGRATIONS', False)
        # Forzar que la función lea la variable en runtime
        import app_crud
        monkeypatch.setattr(app_crud, 'ALLOW_HTTP_MIGRATIONS', False)
        r = client.post('/api/migrate',
                        headers=basic_auth_headers('admin', 'test-admin-password'))
        assert r.status_code == 404

    def test_migrate_idempotente(self, crud_app):
        """Llamar dos veces no explota — las sentencias fallan silenciosamente."""
        client, mod = crud_app
        mod.ALLOW_HTTP_MIGRATIONS = True
        client.post('/api/migrate',
                    headers=basic_auth_headers('admin', 'test-admin-password'))
        r = client.post('/api/migrate',
                        headers=basic_auth_headers('admin', 'test-admin-password'))
        assert r.status_code == 200
        assert r.get_json()['success'] is True


# ────────────────────────────────────────────────────────────────────────────
# /api/estudiantes/promover
# ────────────────────────────────────────────────────────────────────────────

class TestPromoverEstudiantes:

    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def test_promover_por_semestre_sin_confirmar(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/promover',
                        json={'desde_semestre': 3},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['aplicado'] is False
        assert data['afectados'] >= 1

    def test_promover_por_semestre_confirmado(self, crud_app):
        client, mod = crud_app
        # Juan y María están en semestre 3
        r = client.post('/api/estudiantes/promover',
                        json={'desde_semestre': 3, 'confirmar': True},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['aplicado'] is True
        # Verificar en BD
        import sqlite3
        conn = sqlite3.connect(mod.DB)
        sem = conn.execute(
            "SELECT semestre FROM estudiantes WHERE matricula='2023001'"
        ).fetchone()[0]
        conn.close()
        assert sem == 4

    def test_promover_por_ids(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/promover',
                        json={'ids': [1], 'confirmar': True},
                        headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['afectados'] == 1

    def test_promover_sin_parametros_error(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/promover',
                        json={},
                        headers=self._headers())
        assert r.status_code == 400

    def test_promover_semestre_invalido(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/promover',
                        json={'desde_semestre': 'abc'},
                        headers=self._headers())
        assert r.status_code == 400

    def test_promover_semestre_9_rechazado(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/promover',
                        json={'desde_semestre': 9},
                        headers=self._headers())
        assert r.status_code == 400

    def test_promover_por_semestre_y_grupo(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/promover',
                        json={'desde_semestre': 3, 'grupo': 'A'},
                        headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['success'] is True


# ────────────────────────────────────────────────────────────────────────────
# /api/estudiantes/baja-masiva
# ────────────────────────────────────────────────────────────────────────────

class TestBajaMasiva:

    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def test_baja_por_semestre_sin_confirmar(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/baja-masiva',
                        json={'semestre': 3},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['aplicado'] is False

    def test_baja_por_semestre_confirmada(self, crud_app):
        client, mod = crud_app
        r = client.post('/api/estudiantes/baja-masiva',
                        json={'semestre': 3, 'confirmar': True},
                        headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['aplicado'] is True
        import sqlite3
        conn = sqlite3.connect(mod.DB)
        estado = conn.execute(
            "SELECT estado FROM estudiantes WHERE matricula='2023001'"
        ).fetchone()[0]
        conn.close()
        assert estado == 'inactivo'

    def test_baja_por_ids(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/baja-masiva',
                        json={'ids': [1], 'confirmar': True},
                        headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['afectados'] == 1

    def test_baja_sin_parametros_error(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/baja-masiva',
                        json={},
                        headers=self._headers())
        assert r.status_code == 400

    def test_baja_falta_xhr_header(self, crud_app):
        client, _ = crud_app
        import base64
        token = base64.b64encode(b'admin:test-admin-password').decode()
        headers = {'Authorization': f'Basic {token}'}  # sin X-Requested-With
        r = client.post('/api/estudiantes/baja-masiva',
                        json={'semestre': 3},
                        headers=headers)
        assert r.status_code == 403

    def test_baja_por_semestre_y_grupo(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/baja-masiva',
                        json={'semestre': 3, 'grupo': 'A'},
                        headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['success'] is True


# ────────────────────────────────────────────────────────────────────────────
# /api/upload-foto
# ────────────────────────────────────────────────────────────────────────────

class TestUploadFoto:

    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def _jpeg_bytes(self):
        """Genera un JPEG mínimo válido en memoria."""
        from PIL import Image
        import io
        img = Image.new('RGB', (100, 100), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        buf.seek(0)
        return buf

    def test_upload_sin_archivo_error(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/upload-foto',
                        headers=self._headers())
        assert r.status_code == 400
        assert r.get_json()['success'] is False

    def test_upload_extension_no_permitida(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/upload-foto',
                        data={'foto': (io.BytesIO(b'data'), 'archivo.exe')},
                        content_type='multipart/form-data',
                        headers=self._headers())
        assert r.status_code == 400
        assert 'no permitido' in r.get_json()['error'].lower()

    def test_upload_archivo_no_es_imagen(self, crud_app):
        client, _ = crud_app
        import io
        r = client.post('/api/upload-foto',
                        data={'foto': (io.BytesIO(b'esto no es imagen'), 'foto.jpg')},
                        content_type='multipart/form-data',
                        headers=self._headers())
        assert r.status_code == 400
        assert r.get_json()['success'] is False

    def test_upload_jpeg_valido(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        # Redirigir FOTOS a tmp para no ensuciar el proyecto
        monkeypatch.setattr(mod, 'FOTOS', str(tmp_path))
        r = client.post('/api/upload-foto',
                        data={'foto': (self._jpeg_bytes(), 'foto.jpg')},
                        content_type='multipart/form-data',
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['foto_url'].endswith('.jpg')

    def test_upload_archivo_vacio(self, crud_app):
        client, _ = crud_app
        import io
        r = client.post('/api/upload-foto',
                        data={'foto': (io.BytesIO(b''), '')},
                        content_type='multipart/form-data',
                        headers=self._headers())
        assert r.status_code == 400


# ────────────────────────────────────────────────────────────────────────────
# /api/hardware/status
# ────────────────────────────────────────────────────────────────────────────

class TestHardwareStatus:
    def test_timestamp_presente(self, client):
        r = client.get('/api/hardware/status', headers=AUTH)
        hw = r.get_json()['hardware']
        assert hw['timestamp'] is not None
        assert 'T' in hw['timestamp']

    def test_rfid_status_es_string(self, client):
        r = client.get('/api/hardware/status', headers=AUTH)
        hw = r.get_json()['hardware']
        assert isinstance(hw['rfid_status'], str)

    def test_rfid_ok_es_booleano(self, client):
        r = client.get('/api/hardware/status', headers=AUTH)
        hw = r.get_json()['hardware']
        assert isinstance(hw['rfid_ok'], bool)

    def test_db_records_coincide_con_tabla(self, client, db):
        r = client.get('/api/hardware/status', headers=AUTH)
        hw = r.get_json()['hardware']

        import sqlite3
        conn = sqlite3.connect(db)
        expected = conn.execute(
            "SELECT COUNT(*) FROM registros_asistencia"
        ).fetchone()[0]
        conn.close()

        assert hw['db_records'] == expected


    def test_hardware_status_responde(self, crud_app):
        client, _ = crud_app
        r = client.get('/api/hardware/status',
                       headers=basic_auth_headers('admin', 'test-admin-password'))
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert 'hardware' in data

    def test_hardware_status_contiene_campos_esperados(self, crud_app):
        client, _ = crud_app
        r = client.get('/api/hardware/status',
                       headers=basic_auth_headers('admin', 'test-admin-password'))
        hw = r.get_json()['hardware']
        for campo in ('cpu_temp', 'cpu_usage', 'rfid_status', 'db_records'):
            assert campo in hw

# ────────────────────────────────────────────────────────────────────────────
# Hardware — servicios, network, system (mockeando _run y _systemctl)
# ────────────────────────────────────────────────────────────────────────────

class TestHardwareEndpoints:
    @patch('crud.app_crud._run')
    def test_cada_servicio_tiene_campos(self, mock_run, client):
        mock_run.return_value = {
            'success': True,
            'stdout': 'active',
            'stderr': ''
        }

        r = client.get('/api/hardware/services', headers=AUTH)
        services = r.get_json()['services']

        for svc in services:
            assert 'name' in svc
            assert 'active' in svc
            assert 'enabled' in svc
            assert svc['name'] in RFID_SERVICES

    def test_service_action_restart_ok(self, crud_app, monkeypatch):
        client, mod = crud_app

        monkeypatch.setattr(
            mod,
            '_run',
            lambda cmd, **kw: {
                'success': True,
                'stdout': 'active',
                'stderr': '',
                'returncode': 0,
            }
        )

        monkeypatch.setattr(
            mod,
            '_systemctl',
            lambda action, service: {
                'success': True,
                'stdout': '',
                'stderr': '',
                'returncode': 0,
            }
        )

        r = client.post(
            '/api/hardware/services/rfid-crud.service/restart',
            headers=AUTH
        )
        data = r.get_json()

        assert r.status_code == 200
        assert data['success'] is True
        assert data['service'] == 'rfid-crud.service'
        assert data['action'] == 'restart'

    def test_service_action_start_ok(self, crud_app, monkeypatch):
        client, mod = crud_app

        monkeypatch.setattr(
            mod,
            '_run',
            lambda cmd, **kw: {
                'success': True,
                'stdout': 'active',
                'stderr': '',
                'returncode': 0,
            }
        )

        monkeypatch.setattr(
            mod,
            '_systemctl',
            lambda action, service: {
                'success': True,
                'stdout': '',
                'stderr': '',
                'returncode': 0,
            }
        )

        r = client.post(
            '/api/hardware/services/rfid-reader.service/start',
            headers=AUTH
        )

        assert r.status_code == 200

    def test_service_action_stop_ok(self, crud_app, monkeypatch):
        client, mod = crud_app

        monkeypatch.setattr(
            mod,
            '_run',
            lambda cmd, **kw: {
                'success': True,
                'stdout': 'inactive',
                'stderr': '',
                'returncode': 0,
            }
        )

        monkeypatch.setattr(
            mod,
            '_systemctl',
            lambda action, service: {
                'success': True,
                'stdout': '',
                'stderr': '',
                'returncode': 0,
            }
        )

        r = client.post(
            '/api/hardware/services/rfid-dashboard.service/stop',
            headers=AUTH
        )

        assert r.status_code == 200

    @patch('crud.app_crud._run')
    def test_service_logs_lineas_por_defecto(self, mock_run, client):
        mock_run.return_value = {
            'success': True,
            'stdout': 'log',
            'stderr': ''
        }

        r = client.get(
            '/api/hardware/services/rfid-crud.service/logs',
            headers=AUTH
        )
        data = r.get_json()

        assert data['lines'] == 50

    @patch('crud.app_crud._run')
    def test_service_logs_lineas_custom(self, mock_run, client):
        mock_run.return_value = {
            'success': True,
            'stdout': 'log',
            'stderr': ''
        }

        r = client.get(
            '/api/hardware/services/rfid-crud.service/logs?lines=100',
            headers=AUTH
        )
        data = r.get_json()

        assert data['lines'] == 100

    @patch('crud.app_crud._run')
    def test_service_logs_lineas_max_500(self, mock_run, client):
        mock_run.return_value = {
            'success': True,
            'stdout': 'log',
            'stderr': ''
        }

        r = client.get(
            '/api/hardware/services/rfid-crud.service/logs?lines=9999',
            headers=AUTH
        )
        data = r.get_json()

        assert data['lines'] <= 500


    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def _run_ok(self, stdout='', stderr=''):
        return {'success': True, 'stdout': stdout, 'stderr': stderr, 'returncode': 0}

    def _run_fail(self, stderr='error'):
        return {'success': False, 'stdout': '', 'stderr': stderr, 'returncode': 1}

    # ── /api/hardware/services ──────────────────────────────────────────────

    def test_hardware_services_lista(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok('active'))
        r = client.get('/api/hardware/services', headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert isinstance(data['services'], list)

    def test_hardware_service_action_valida(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok('active'))
        monkeypatch.setattr(mod, '_systemctl', lambda action, svc: self._run_ok())
        svc = 'rfid-reader.service'
        r = client.post(f'/api/hardware/services/{svc}/restart',
                        headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['service'] == svc

    def test_hardware_service_no_permitido(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/hardware/services/sshd.service/restart',
                        headers=self._headers())
        assert r.status_code == 403

    def test_hardware_service_accion_no_permitida(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/hardware/services/rfid-reader.service/kill',
                        headers=self._headers())
        assert r.status_code == 400

    def test_hardware_service_permiso_denegado(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok('inactive'))
        monkeypatch.setattr(mod, '_systemctl',
                            lambda action, svc: self._run_fail('Permission denied'))
        r = client.post('/api/hardware/services/rfid-reader.service/restart',
                        headers=self._headers())
        assert r.status_code == 403

    def test_hardware_service_logs(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run',
                            lambda cmd, **kw: self._run_ok('línea 1\nlínea 2'))
        svc = 'rfid-reader.service'
        r = client.get(f'/api/hardware/services/{svc}/logs',
                       headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_hardware_service_logs_no_permitido(self, crud_app):
        client, _ = crud_app
        r = client.get('/api/hardware/services/sshd.service/logs',
                       headers=self._headers())
        assert r.status_code == 403

    # ── /api/hardware/network ───────────────────────────────────────────────
    def test_hardware_network_status(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run',
                            lambda cmd, **kw: self._run_ok('yes:MiRed:75:WPA2'))
        monkeypatch.setattr(mod, '_wifi_iface', lambda: 'wlan0')
        r = client.get('/api/hardware/network/status', headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert 'network' in data

    def test_hardware_network_scan(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run',
                            lambda cmd, **kw: self._run_ok('yes:MiRed:80:WPA2'))
        monkeypatch.setattr(mod, '_wifi_iface', lambda: 'wlan0')
        r = client.post('/api/hardware/network/scan', headers=self._headers())
        assert r.status_code == 200

    def test_hardware_network_connect(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok())
        r = client.post('/api/hardware/network/connect',
                        json={'ssid': 'MiRed', 'password': 'test-network-password'},
                        headers=self._headers())
        assert r.status_code == 200

    def test_hardware_network_connect_sin_ssid(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/hardware/network/connect',
                        json={},
                        headers=self._headers())
        assert r.status_code == 400

    def test_hardware_network_disconnect(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok())
        monkeypatch.setattr(mod, '_wifi_iface', lambda: 'wlan0')
        r = client.post('/api/hardware/network/disconnect',
                        headers=self._headers())
        assert r.status_code == 200

    def test_hardware_network_restart(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok())
        r = client.post('/api/hardware/network/restart',
                        headers=self._headers())
        assert r.status_code == 200

    # ── /api/hardware/system ────────────────────────────────────────────────

    def test_hardware_system_optimize_sin_confirm(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/hardware/system/optimize',
                        json={},
                        headers=self._headers())
        assert r.status_code == 400

    def test_hardware_system_optimize_con_confirm(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok())
        r = client.post('/api/hardware/system/optimize',
                        json={'confirm': True},
                        headers=self._headers())
        assert r.status_code == 200

    def test_optimize_con_confirm_y_permiso_denegado_retorna_403(
        self, crud_app, monkeypatch
    ):
        """Si drop_caches falla y no se puede escribir drop_caches → 403."""
        client, mod = crud_app

        monkeypatch.setattr(
            mod,
            '_run',
            lambda cmd, **kw: self._run_fail('permission denied')
        )

        def fake_open(*args, **kwargs):
            raise PermissionError

        monkeypatch.setattr('builtins.open', fake_open)

        r = client.post(
            '/api/hardware/system/optimize',
            json={'confirm': True},
            headers=AUTH
        )

        assert r.status_code == 403

    def test_hardware_system_reboot_sin_confirm(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/hardware/system/reboot',
                        json={},
                        headers=self._headers())
        assert r.status_code == 400

    def test_hardware_system_reboot_con_confirm(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok())
        r = client.post('/api/hardware/system/reboot',
                        json={'confirm': True},
                        headers=self._headers())
        assert r.status_code == 200

        audit = client.get('/api/audit-log', headers=self._headers())
        assert audit.status_code == 200
        audit_data = audit.get_json()
        assert audit_data['success'] is True

        reboots = [
            row for row in audit_data.get('registros', [])
            if row.get('accion') == 'hardware_system_reboot'
        ]
        assert reboots
        assert reboots[-1]['resultado'] == 'éxito'

    def test_hardware_system_shutdown_sin_confirm(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/hardware/system/shutdown',
                        json={},
                        headers=self._headers())
        assert r.status_code == 400

    def test_hardware_system_shutdown_con_confirm(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok())
        r = client.post('/api/hardware/system/shutdown',
                        json={'confirm': True},
                        headers=self._headers())
        assert r.status_code == 200

    # ── /api/software/services ──────────────────────────────────────────────

    def test_software_services_lista(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok('active'))
        r = client.get('/api/software/services', headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_software_service_action_valida(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok('active'))
        monkeypatch.setattr(mod, '_systemctl', lambda action, svc: self._run_ok())
        r = client.post('/api/software/services/rfid-reader.service/restart',
                        headers=self._headers())
        assert r.status_code == 200

    def test_software_service_no_permitido(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/software/services/sshd.service/restart',
                        headers=self._headers())
        assert r.status_code == 403

    def test_software_service_permiso_denegado(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok('inactive'))
        monkeypatch.setattr(mod, '_systemctl',
                            lambda action, svc: self._run_fail('interactive authentication required'))
        r = client.post('/api/software/services/rfid-reader.service/restart',
                        headers=self._headers())
        assert r.status_code == 403

        # ────────────────────────────────────────────────────────────────────────────
# /api/software/database/restore
# ────────────────────────────────────────────────────────────────────────────

class TestRestore:

    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def _crear_backup(self, crud_app):
        client, mod = crud_app
        r = client.post('/api/software/database/backup', headers=self._headers())
        return r.get_json()['filename']

    def test_restore_sin_confirm_error(self, crud_app):
        fname = self._crear_backup(crud_app)
        client, _ = crud_app
        r = client.post('/api/software/database/restore',
                        json={'filename': fname},
                        headers=self._headers())
        assert r.status_code == 400

    def test_restore_sin_filename_error(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/software/database/restore',
                        json={'confirm': True},
                        headers=self._headers())
        assert r.status_code == 400

    def test_restore_filename_invalido(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/software/database/restore',
                        json={'confirm': True, 'filename': '../../etc/passwd'},
                        headers=self._headers())
        assert r.status_code == 400

    def test_restore_archivo_no_existe(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/software/database/restore',
                        json={'confirm': True, 'filename': 'rfid_backup_20200101_000000.db'},
                        headers=self._headers())
        assert r.status_code == 404

    def test_restore_ok(self, crud_app):
        fname = self._crear_backup(crud_app)
        client, _ = crud_app
        r = client.post('/api/software/database/restore',
                        json={'confirm': True, 'filename': fname},
                        headers=self._headers())
        assert r.status_code == 200
        assert r.get_json()['success'] is True


# ────────────────────────────────────────────────────────────────────────────
# /api/software/database/purge
# ────────────────────────────────────────────────────────────────────────────

class TestPurge:

    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def _insertar_registro(self, mod, fecha='2020-01-01'):
        import sqlite3
        conn = sqlite3.connect(mod.DB)
        conn.execute(
            "INSERT INTO registros_asistencia (uid, fecha_dia, tipo_evento, mensaje, timestamp) "
            "VALUES ('AAAA', ?, 'rebote', 'test', ?)", (fecha, fecha + ' 12:00:00')
        )
        conn.commit()
        conn.close()

    def test_purge_sin_confirm_error(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/software/database/purge',
                        json={},
                        headers=self._headers())
        assert r.status_code == 400

    def test_purge_ok(self, crud_app):
        client, mod = crud_app
        self._insertar_registro(mod)
        r = client.post('/api/software/database/purge',
                        json={'confirm': True, 'fecha_hasta': '2021-01-01'},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['deleted'] >= 1

        audit = client.get('/api/audit-log', headers=self._headers())
        assert audit.status_code == 200
        audit_data = audit.get_json()
        assert audit_data['success'] is True

        purges = [
            row for row in audit_data.get('registros', [])
            if row.get('accion') == 'software_database_purge'
        ]
        assert purges
        assert purges[-1]['resultado'] == 'éxito'

    def test_purge_sin_filtros_elimina_todo(self, crud_app):
        client, mod = crud_app
        self._insertar_registro(mod)
        r = client.post('/api/software/database/purge',
                        json={'confirm': True},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['deleted'] >= 1

# ────────────────────────────────────────────────────────────────────────────
# /api/estudiantes/alta-masiva
# ────────────────────────────────────────────────────────────────────────────

class TestAltaMasiva:

    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def test_alta_masiva_ok(self, crud_app):
        client, _ = crud_app
        filas = [
            {'nombre': 'Luis', 'apellido_paterno': 'Torres', 'matricula': '2025001',
             'semestre': 1, 'grupo': 'A'},
            {'nombre': 'Eva',  'apellido_paterno': 'Ruiz',   'matricula': '2025002',
             'semestre': 2, 'grupo': 'B'},
        ]
        r = client.post('/api/estudiantes/alta-masiva',
                        json={'estudiantes': filas},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['creados'] == 2
        assert data['errores'] == []

    def test_alta_masiva_sin_estudiantes_error(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/estudiantes/alta-masiva',
                        json={'estudiantes': []},
                        headers=self._headers())
        assert r.status_code == 400

    def test_alta_masiva_fila_incompleta(self, crud_app):
        client, _ = crud_app
        filas = [
            {'nombre': 'Luis', 'matricula': '2025010'},  # falta apellido_paterno
        ]
        r = client.post('/api/estudiantes/alta-masiva',
                        json={'estudiantes': filas},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['creados'] == 0
        assert len(data['errores']) == 1

    def test_alta_masiva_matricula_duplicada(self, crud_app):
        client, _ = crud_app
        filas = [
            {'nombre': 'X', 'apellido_paterno': 'Y', 'matricula': '2023001'},  # ya existe
        ]
        r = client.post('/api/estudiantes/alta-masiva',
                        json={'estudiantes': filas},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['creados'] == 0
        assert len(data['errores']) == 1

    def test_alta_masiva_mixta(self, crud_app):
        """Una fila válida y una duplicada → creados=1, errores=1."""
        client, _ = crud_app
        filas = [
            {'nombre': 'Nuevo', 'apellido_paterno': 'Alumno', 'matricula': '2025099'},
            {'nombre': 'X',     'apellido_paterno': 'Y',      'matricula': '2023001'},
        ]
        r = client.post('/api/estudiantes/alta-masiva',
                        json={'estudiantes': filas},
                        headers=self._headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data['creados'] == 1
        assert len(data['errores']) == 1

        # ────────────────────────────────────────────────────────────────────────────
# /api/rfid/listen/* y /api/rfid/admin-scan/*
# ────────────────────────────────────────────────────────────────────────────

class TestRFIDListen:

    def test_listen_start(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/rfid/listen/start',
                        json={'timeout': 10},
                        headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_listen_status_inactivo(self, crud_app):
        client, _ = crud_app
        r = client.get('/api/rfid/listen/status', headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_listen_status_activo(self, crud_app):
        client, _ = crud_app
        client.post('/api/rfid/listen/start', json={'timeout': 30}, headers=AUTH)
        r = client.get('/api/rfid/listen/status', headers=AUTH)
        data = r.get_json()
        assert data['active'] is True

    def test_listen_stop(self, crud_app):
        client, _ = crud_app
        client.post('/api/rfid/listen/start', json={'timeout': 30}, headers=AUTH)
        r = client.post('/api/rfid/listen/stop', headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_listen_capture_ok(self, crud_app):
        client, _ = crud_app
        client.post('/api/rfid/listen/start', json={'timeout': 30}, headers=AUTH)
        r = client.post('/api/rfid/listen/capture',
                        json={'uid': 'TESTUID99'},
                        headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['uid'] == 'TESTUID99'

    def test_listen_capture_sin_uid(self, crud_app):
        client, _ = crud_app
        client.post('/api/rfid/listen/start', json={'timeout': 30}, headers=AUTH)
        r = client.post('/api/rfid/listen/capture',
                        json={'uid': ''},
                        headers=AUTH)
        assert r.status_code == 400

    def test_listen_capture_sin_modo_activo(self, crud_app):
        client, _ = crud_app
        # Asegurar que no está activo
        client.post('/api/rfid/listen/stop', headers=AUTH)
        r = client.post('/api/rfid/listen/capture',
                        json={'uid': 'TESTUID99'},
                        headers=AUTH)
        assert r.status_code == 409


class TestAdminScan:

    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def test_admin_scan_start(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(tmp_path / 'rfid_admin_uid'))
        r = client.post('/api/rfid/admin-scan/start',
                        json={'timeout': 60},
                        headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_admin_scan_stop(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(tmp_path / 'rfid_admin_uid'))
        client.post('/api/rfid/admin-scan/start', json={}, headers=AUTH)
        r = client.post('/api/rfid/admin-scan/stop', headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_admin_scan_status(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(tmp_path / 'rfid_admin_uid'))
        client.post('/api/rfid/admin-scan/start', json={'timeout': 60}, headers=AUTH)
        r = client.get('/api/rfid/admin-scan/status', headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert isinstance(data['uids'], list)

    def test_admin_scan_guardar_uids(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(tmp_path / 'rfid_admin_uid'))
        r = client.post('/api/rfid/admin-scan/guardar',
                        json={'uids': ['NUEVAUID01', 'NUEVAUID02']},
                        headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data['success'] is True
        assert data['guardadas'] == 2

    def test_admin_scan_guardar_uid_existente(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(tmp_path / 'rfid_admin_uid'))
        r = client.post('/api/rfid/admin-scan/guardar',
                        json={'uids': ['AABBCCDD']},  # ya existe en fixture
                        headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data['guardadas'] == 0
        assert data['resultados'][0]['ok'] is False

    def test_admin_scan_guardar_sin_uids(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/rfid/admin-scan/guardar',
                        json={'uids': []},
                        headers=AUTH)
        assert r.status_code == 400

    def test_admin_scan_eliminar_ok(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(tmp_path / 'rfid_admin_uid'))
        # Primero crear una tarjeta sin estudiante
        client.post('/api/tarjetas', json={'uid': 'TMPUID001'}, headers=AUTH)
        r = client.post('/api/rfid/admin-scan/eliminar',
                        json={'uids': ['TMPUID001']},
                        headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['eliminadas'] == 1

    def test_admin_scan_eliminar_con_estudiante_sin_forzar(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/rfid/admin-scan/eliminar',
                        json={'uids': ['AABBCCDD']},  # tiene estudiante asignado
                        headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data['eliminadas'] == 0
        assert 'forzar' in data['resultados'][0]['msg'].lower()

    def test_admin_scan_eliminar_con_forzar(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/rfid/admin-scan/eliminar',
                        json={'uids': ['AABBCCDD'], 'forzar': True},
                        headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['eliminadas'] == 1

    def test_admin_scan_eliminar_uid_no_existe(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/rfid/admin-scan/eliminar',
                        json={'uids': ['NOEXISTE99']},
                        headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()['eliminadas'] == 0

    def test_admin_scan_eliminar_sin_uids(self, crud_app):
        client, _ = crud_app
        r = client.post('/api/rfid/admin-scan/eliminar',
                        json={'uids': []},
                        headers=AUTH)
        assert r.status_code == 400
    # ────────────────────────────────────────────────────────────────────────────
# Ramas de error en _run, hardware_status, network y _leer_uid_admin
# ────────────────────────────────────────────────────────────────────────────

class TestRunErrorBranches:
    """Cubre las ramas de excepción de _run (286-299)."""

    def test_run_comando_no_encontrado(self, crud_app, monkeypatch):
        client, mod = crud_app
        import subprocess
        def fake_run(*a, **kw):
            raise FileNotFoundError("no such file")
        monkeypatch.setattr(subprocess, "run", fake_run)
        result = mod._run(['comando_inexistente'])
        assert result['success'] is False
        assert 'no encontrado' in result['error'].lower()

    def test_run_timeout(self, crud_app, monkeypatch):
        client, mod = crud_app
        import subprocess
        def fake_run(*a, **kw):
            raise subprocess.TimeoutExpired(cmd='cmd', timeout=1)
        monkeypatch.setattr(subprocess, "run", fake_run)
        result = mod._run(['cmd'], timeout=1)
        assert result['success'] is False
        assert 'timeout' in result['error'].lower()

    def test_run_excepcion_generica(self, crud_app, monkeypatch):
        client, mod = crud_app
        import subprocess
        def fake_run(*a, **kw):
            raise RuntimeError("error genérico")
        monkeypatch.setattr(subprocess, "run", fake_run)
        result = mod._run(['cmd'])
        assert result['success'] is False
        assert 'error' in result


class TestHardwareStatusBranches:
    """Cubre ramas de hardware_status (565-600): vcgencmd, SPI, mfrc522."""

    def _headers(self):
        return basic_auth_headers('admin', 'test-admin-password')

    def test_hardware_status_con_spi_detectado(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod.os, 'listdir',
                            lambda path: ['spidev0.0'] if path == '/dev' else [])
        monkeypatch.setattr(mod.os.path, 'exists', lambda p: True)
        r = client.get('/api/hardware/status', headers=self._headers())
        assert r.status_code == 200
        hw = r.get_json()['hardware']
        assert hw['rfid_status'] == 'conectado'
        assert hw['rfid_ok'] is True

    def test_hardware_status_sin_spi_con_mfrc522(self, crud_app, monkeypatch):
        import sys
        client, mod = crud_app
        monkeypatch.setattr(mod.os, 'listdir', lambda path: [])
        # mfrc522 importable
        monkeypatch.setitem(sys.modules, 'mfrc522', MagicMock())
        r = client.get('/api/hardware/status', headers=self._headers())
        assert r.status_code == 200

    def test_hardware_status_vcgencmd(self, crud_app, monkeypatch):
        import subprocess
        client, mod = crud_app
        # No existe /sys/class/thermal → intenta vcgencmd
        monkeypatch.setattr(mod.os.path, 'exists',
                            lambda p: False if 'thermal' in p else True)
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "temp=45.0'C"
        monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: fake_result)
        r = client.get('/api/hardware/status', headers=self._headers())
        assert r.status_code == 200
        hw = r.get_json()['hardware']
        assert hw['cpu_temp'] == 45.0


class TestNetworkErrorBranches:
    """Cubre ramas de fallo en network/connect, disconnect sin iface, restart fallido."""

    def _headers(self):
        return {**basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'}

    def _run_fail(self, stderr='error'):
        return {'success': False, 'stdout': '', 'stderr': stderr, 'returncode': 1}

    def _run_ok(self):
        return {'success': True, 'stdout': '', 'stderr': '', 'returncode': 0}

    def test_network_connect_falla(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_fail('Authentication failed'))
        r = client.post('/api/hardware/network/connect',
                        json={'ssid': 'MiRed', 'password': 'wrong'},
                        headers=self._headers())
        assert r.status_code == 400

    def test_network_connect_ssid_existente(self, crud_app, monkeypatch):
        """SSID ya está en las conexiones guardadas → usa 'connection up'."""
        client, mod = crud_app
        llamadas = []
        def fake_run(cmd, **kw):
            llamadas.append(cmd)
            if 'show' in cmd:
                return {'success': True, 'stdout': 'MiRed\nOtraRed', 'stderr': '', 'returncode': 0}
            return self._run_ok()
        monkeypatch.setattr(mod, '_run', fake_run)
        r = client.post('/api/hardware/network/connect',
                        json={'ssid': 'MiRed', 'password': 'test-network-password'},
                        headers=self._headers())
        assert r.status_code == 200
        # Verificar que usó 'connection up' no 'dev wifi connect'
        cmds = [' '.join(c) for c in llamadas]
        assert any('connection up' in c for c in cmds)

    def test_network_connect_sin_password(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_ok())
        r = client.post('/api/hardware/network/connect',
                        json={'ssid': 'RedAbierta'},
                        headers=self._headers())
        assert r.status_code == 200

    def test_network_disconnect_sin_iface(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_wifi_iface', lambda: None)
        r = client.post('/api/hardware/network/disconnect',
                        headers=self._headers())
        assert r.status_code == 404

    def test_network_disconnect_falla(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_wifi_iface', lambda: 'wlan0')
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_fail('Device not found'))
        r = client.post('/api/hardware/network/disconnect',
                        headers=self._headers())
        assert r.status_code == 400

    def test_network_restart_falla(self, crud_app, monkeypatch):
        client, mod = crud_app
        monkeypatch.setattr(mod, '_run', lambda cmd, **kw: self._run_fail('Unit not found'))
        monkeypatch.setattr(mod, '_systemctl', lambda action, svc: self._run_fail('Unit not found'))
        r = client.post('/api/hardware/network/restart',
                        headers=self._headers())
        assert r.status_code == 400


class TestLeerUidAdmin:
    """Cubre _leer_uid_admin con archivo presente (1163-1184)."""

    def test_leer_uid_admin_con_archivo_valido(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        uid_file = tmp_path / 'rfid_admin_uid'
        uid_file.write_text('2026-09-15T10:00:00\tABCD1234\n')
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(uid_file))
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        # Activar sesión admin
        with mod._admin_scan_lock:
            mod._admin_scan_state.update({
                'active': True, 'uids': [],
                'expires': __import__('time').time() + 300,
                'ultimo_uid_ts': None
            })
        r = client.get('/api/rfid/admin-scan/status', headers=basic_auth_headers('admin', 'test-admin-password'))
        assert r.status_code == 200
        data = r.get_json()
        assert any(u['uid'] == 'ABCD1234' for u in data['uids'])

    def test_leer_uid_admin_archivo_vacio(self, crud_app, tmp_path, monkeypatch):
        client, mod = crud_app
        uid_file = tmp_path / 'rfid_admin_uid'
        uid_file.write_text('')
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(uid_file))
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        with mod._admin_scan_lock:
            mod._admin_scan_state.update({
                'active': True, 'uids': [],
                'expires': __import__('time').time() + 300,
                'ultimo_uid_ts': None
            })
        r = client.get('/api/rfid/admin-scan/status', headers=basic_auth_headers('admin', 'test-admin-password'))
        assert r.status_code == 200
        assert r.get_json()['uids'] == []

    def test_leer_uid_admin_sin_tab(self, crud_app, tmp_path, monkeypatch):
        """Línea sin tab → devuelve solo el uid sin timestamp."""
        client, mod = crud_app
        uid_file = tmp_path / 'rfid_admin_uid'
        uid_file.write_text('SOLOUID\n')
        monkeypatch.setattr(mod, 'ADMIN_UID_FILE', str(uid_file))
        monkeypatch.setattr(mod, 'ADMIN_FLAG', str(tmp_path / 'rfid_admin_mode'))
        with mod._admin_scan_lock:
            mod._admin_scan_state.update({
                'active': True, 'uids': [],
                'expires': __import__('time').time() + 300,
                'ultimo_uid_ts': None
            })
        r = client.get('/api/rfid/admin-scan/status', headers=basic_auth_headers('admin', 'test-admin-password'))
        assert r.status_code == 200
        data = r.get_json()
        assert any(u['uid'] == 'SOLOUID' for u in data['uids'])
    # ────────────────────────────────────────────────────────────────────────────
# Ramas adicionales para llegar a 90%+
# ────────────────────────────────────────────────────────────────────────────

class TestCheckCredentials:
    """Cubre except (TypeError, UnicodeEncodeError) en _check_credentials (50-51)."""

    def test_credenciales_none_retorna_false(self, crud_app):
        _, mod = crud_app
        assert mod._check_credentials(None, None) is False

    def test_credenciales_bytes_retorna_false(self, crud_app):
        _, mod = crud_app
        # UnicodeEncodeError al intentar encode de caracteres problemáticos
        assert mod._check_credentials('\udcff', 'test-admin-password') is False


class TestSchemaCache:
    """Cubre return _schema_cache cuando ya está cacheado (237)."""

    def test_schema_cache_segunda_llamada(self, crud_app):
        _, mod = crud_app
        conn = mod.get_db()
        try:
            s1 = mod.schema(conn)
            s2 = mod.schema(conn)  # segunda llamada — usa cache
            assert s1 is s2
        finally:
            conn.close()


class TestSystemctl:
    """Cubre ramas de _systemctl con sudo (304-320)."""

    def test_systemctl_falla_usa_sudo_exitoso(self, crud_app, monkeypatch):
        _, mod = crud_app
        llamadas = []
        def fake_run(cmd, **kw):
            llamadas.append(cmd)
            if 'sudo' in cmd:
                return {'success': True, 'stdout': '', 'stderr': '', 'returncode': 0}
            return {'success': False, 'stdout': '', 'stderr': 'error', 'returncode': 1}
        monkeypatch.setattr(mod, '_run', fake_run)
        result = mod._systemctl('restart', 'rfid-reader.service')
        assert result['success'] is True
        assert any('sudo' in c for c in llamadas)

    def test_systemctl_enable_con_symlink(self, crud_app, monkeypatch):
        _, mod = crud_app
        llamadas = []

        def fake_run(cmd, **kw):
            llamadas.append(cmd)

            if 'sudo' in cmd:
                return {
                    'success': False,
                    'stdout': '',
                    'stderr': 'Created symlink',
                    'returncode': 1,
                }

            return {
                'success': False,
                'stdout': '',
                'stderr': 'permission denied',
                'returncode': 1,
            }

        monkeypatch.setattr(mod, '_run', fake_run)

        result = mod._systemctl('enable', 'rfid-reader.service')

        assert result['success'] is True
        assert len(llamadas) == 2
        assert llamadas[0] == [
            'systemctl', 'enable', 'rfid-reader.service'
        ]
        assert llamadas[1] == [
            'sudo', '-n', 'systemctl', 'enable', 'rfid-reader.service'
        ]

# ============================================================================
# Cobertura funcional adicional
# ============================================================================

class TestCoberturaFuncionalAdicional:

    def test_actualizar_tarjeta_inexistente(self, crud_app):
        client, mod = crud_app

        r = client.put(
            '/api/tarjetas/99999',
            headers=AUTH,
            json={
                'uid': 'NOEXISTE',
                'id_estudiante': None,
                'activa': 1,
            }
        )

        assert r.status_code == 404
        assert r.get_json()['success'] is False

    def test_eliminar_tarjeta_inexistente(self, crud_app):
        client, mod = crud_app

        r = client.delete(
            '/api/tarjetas/99999',
            headers=AUTH
        )

        assert r.status_code == 404
        assert r.get_json()['success'] is False

    def test_actualizar_estudiante_inexistente(self, crud_app):
        client, mod = crud_app

        r = client.put(
            '/api/estudiantes/99999',
            headers=AUTH,
            json={
                'nombre': 'No',
                'apellido_paterno': 'Existe',
                'matricula': 'NO999',
                'semestre': 1,
                'grupo': 'A',
            }
        )

        assert r.status_code == 404
        assert r.get_json()['success'] is False

    def test_eliminar_estudiante_inexistente(self, crud_app):
        client, mod = crud_app

        r = client.delete(
            '/api/estudiantes/99999',
            headers=AUTH
        )

        assert r.status_code == 404
        assert r.get_json()['success'] is False

    def test_registros_filtro_fecha(self, crud_app):
        client, mod = crud_app

        r = client.get(
            '/api/registros?fecha=2024-01-01',
            headers=AUTH
        )

        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_registros_filtro_tipo(self, crud_app):
        client, mod = crud_app

        r = client.get(
            '/api/registros?estado=aceptado',
            headers=AUTH
        )

        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_registros_filtro_uid(self, crud_app):
        client, mod = crud_app

        r = client.get(
            '/api/registros?uid=AABBCCDD',
            headers=AUTH
        )

        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_auditoria_filtro_accion(self, crud_app):
        client, mod = crud_app

        r = client.get(
            '/api/audit-log?accion=login',
            headers=AUTH
        )

        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_auditoria_filtro_ip(self, crud_app):
        client, mod = crud_app

        r = client.get(
            '/api/audit-log?ip=127.0.0.1',
            headers=AUTH
        )

        assert r.status_code == 200
        assert r.get_json()['success'] is True

    def test_actualizar_estudiante_cambia_foto(
        self, crud_app, tmp_db, monkeypatch
    ):
        client, mod = crud_app

        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "UPDATE estudiantes SET foto=? WHERE id=1",
            ('old_foto.jpg',)
        )
        conn.commit()
        conn.close()

        eliminadas = []

        monkeypatch.setattr(
            mod,
            '_eliminar_foto_disco',
            lambda foto: eliminadas.append(foto)
        )

        r = client.put(
            '/api/estudiantes/1',
            headers=AUTH,
            json={
                'nombre': 'Juan',
                'apellido_paterno': 'Perez',
                'apellido_materno': '',
                'matricula': '2023001',
                'semestre': 3,
                'grupo': 'A',
                'correo': '',
                'estado': 'activo',
                'foto': 'nueva_foto.jpg',
            }
        )

        assert r.status_code == 200
        assert r.get_json()['success'] is True
        assert eliminadas == ['old_foto.jpg']

    def test_eliminar_estudiante_con_foto(
        self, crud_app, tmp_db, monkeypatch
    ):
        client, mod = crud_app

        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "UPDATE estudiantes SET foto=? WHERE id=1",
            ('foto_a_borrar.jpg',)
        )
        conn.commit()
        conn.close()

        eliminadas = []

        monkeypatch.setattr(
            mod,
            '_eliminar_foto_disco',
            lambda foto: eliminadas.append(foto)
        )

        r = client.delete(
            '/api/estudiantes/1',
            headers=AUTH
        )

        assert r.status_code == 200
        assert r.get_json()['success'] is True
        assert eliminadas == ['foto_a_borrar.jpg']

    def test_eliminar_backup_sin_confirmar(self, crud_app):
        client, _ = crud_app

        r = client.delete(
            "/api/software/database/backups/rfid_backup_test.db",
            headers=AUTH
        )

        assert r.status_code == 400
        data = r.get_json()
        assert data["success"] is False
        assert "confirmación" in data["error"].lower()

    def test_listar_backups_ignora_archivos_invalidos(
        self, crud_app, monkeypatch, tmp_path
    ):
        client, mod = crud_app

        monkeypatch.setattr(mod, "BACKUP_DIR", str(tmp_path))

        (tmp_path / "rfid_backup_20260916_120000.db").write_bytes(b"backup")
        (tmp_path / "archivo_invalido.txt").write_text("no es backup")
        (tmp_path / "otro.db").write_bytes(b"no valido")

        r = client.get(
            "/api/software/database/backups",
            headers=AUTH
        )

        assert r.status_code == 200

        data = r.get_json()
        assert data["success"] is True

        nombres = [b["filename"] for b in data["backups"]]

        assert "rfid_backup_20260916_120000.db" in nombres
        assert "archivo_invalido.txt" not in nombres
        assert "otro.db" not in nombres

    def test_admin_scan_start_elimina_uid_anterior(
        self, crud_app, tmp_path, monkeypatch
    ):
        client, mod = crud_app

        flag = tmp_path / "rfid_admin_mode"
        uid_file = tmp_path / "rfid_admin_uid"

        uid_file.write_text("2026-09-16T10:00:00\tABCD1234\n")

        monkeypatch.setattr(mod, "ADMIN_FLAG", str(flag))
        monkeypatch.setattr(mod, "ADMIN_UID_FILE", str(uid_file))

        assert uid_file.exists()

        r = client.post(
            "/api/rfid/admin-scan/start",
            json={"timeout": 60},
            headers=AUTH
        )

        assert r.status_code == 200
        assert r.get_json()["success"] is True
        assert not uid_file.exists()

    def test_ultimo_scan_sin_registros(self, crud_app):
        client, mod = crud_app

        import sqlite3

        conn = sqlite3.connect(mod.DB)
        conn.execute("DELETE FROM registros_asistencia")
        conn.commit()
        conn.close()

        r = client.get(
            "/api/rfid/ultimo-scan",
            headers=AUTH
        )

        assert r.status_code == 200

        data = r.get_json()

        assert data["success"] is True
        assert data["scan"] is None

    def test_asistencia_hoy_con_presentes(self, crud_app):
        import sqlite3
        import datetime

        client, mod = crud_app

        conn = sqlite3.connect(mod.DB)
        hoy = datetime.date.today().isoformat()

        conn.execute(
            "INSERT INTO registros_asistencia "
            "(id_estudiante, uid, fecha_dia, tipo_evento, mensaje) "
            "VALUES (1, ?, ?, ?, 'test')",
            ("AABBCCDD", hoy, "aceptado")
        )

        conn.commit()
        conn.close()

        r = client.get(
            "/api/asistencia/hoy",
            headers=AUTH
        )

        assert r.status_code == 200

        data = r.get_json()

        assert data["success"] is True
        assert isinstance(data["presentes"], list)
        assert 1 in data["presentes"]

    def test_asistencia_hoy_sin_presentes(self, crud_app):
        client, mod = crud_app

        import sqlite3

        conn = sqlite3.connect(mod.DB)
        conn.execute("DELETE FROM registros_asistencia")
        conn.commit()
        conn.close()

        r = client.get(
            "/api/asistencia/hoy",
            headers=AUTH
        )

        assert r.status_code == 200

        data = r.get_json()

        assert data["success"] is True
        assert data["presentes"] == []

    def test_csv_safe_previene_formula_injection(self, crud_app):
        _, mod = crud_app

        assert mod._csv_safe("=SUM(A1:A2)") == "'=SUM(A1:A2)"
        assert mod._csv_safe("+123") == "'+123"
        assert mod._csv_safe("-123") == "'-123"
        assert mod._csv_safe("@usuario") == "'@usuario"

        assert mod._csv_safe("Juan") == "Juan"
        assert mod._csv_safe("") == ""
        assert mod._csv_safe(None) is None

    def test_hardware_service_logs_respeta_limite(
        self, crud_app, monkeypatch
    ):
        client, mod = crud_app

        llamadas = []

        def fake_run(cmd, **kw):
            llamadas.append(cmd)
            return {
                "success": True,
                "stdout": "línea 1\nlínea 2",
                "stderr": "",
                "returncode": 0
            }

        monkeypatch.setattr(mod, "_run", fake_run)

        r = client.get(
            "/api/hardware/services/rfid-reader.service/logs?lines=120",
            headers={
                **basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'
            }
        )

        assert r.status_code == 200
        assert r.get_json()["success"] is True

        assert any(
            "-n120" in str(cmd)
            for cmd in llamadas
        )
    def test_software_service_logs_respeta_limite(
        self, crud_app, monkeypatch
    ):
        client, mod = crud_app

        llamadas = []

        def fake_run(cmd, **kw):
            llamadas.append(cmd)
            return {
                "success": True,
                "stdout": "línea 1\nlínea 2",
                "stderr": "",
                "returncode": 0
            }

        monkeypatch.setattr(mod, "_run", fake_run)

        r = client.get(
            "/api/software/services/rfid-reader.service/logs?lines=120",
            headers={
                **basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'
            }
        )

        assert r.status_code == 200

        data = r.get_json()

        assert data["success"] is True
        assert data["service"] == "rfid-reader.service"
        assert data["lines"] == 120
        assert data["log"] == "línea 1\nlínea 2"

        assert any(
            "-n120" in str(cmd)
            for cmd in llamadas
        )

    def test_grupos_fallback_operational_error(
        self, crud_app, monkeypatch
    ):
        client, mod = crud_app

        real_execute = None

        class FakeCursor:
            def __init__(self):
                self._rows = [
                    {
                        "id": 1,
                        "nombre": "Juan",
                        "apellido_paterno": "Pérez",
                        "apellido_materno": "",
                        "matricula": "TEST001",
                        "carrera": mod.CARRERA,
                        "semestre": "8",
                        "grupo": "A",
                        "estado": "activo",
                        "tarjetas_asignadas": 0
                    }
                ]

            def fetchall(self):
                return self._rows

            def fetchone(self):      # ← AGREGAR ESTO
                return self._rows[0] if self._rows else None

        class FakeConnection:
            def execute(self, query, params=()):
                if "COALESCE(e.grupo" in query:
                    import sqlite3
                    raise sqlite3.OperationalError(
                        "simulated missing function"
                    )

                if "auth_fail_log" in query:
                    class _C:
                        def fetchone(self): return {"n": 0}
                        def fetchall(self): return []
                    return _C()
                return FakeCursor()

            def close(self):
                pass

        def fake_get_db():
            return FakeConnection()

        monkeypatch.setattr(mod, "get_db", fake_get_db)

        r = client.get(
            "/api/estudiantes/grupos",
            headers={
                **basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'
            }
        )

        assert r.status_code == 200

        data = r.get_json()

        assert data["success"] is True
        assert isinstance(data["grupos"], list)

        assert data["grupos"][0]["semestre"] == "8"
        assert data["grupos"][0]["grupo"] == "A"

    def test_audit_log_tabla_no_disponible(
        self, crud_app, monkeypatch
    ):
        client, mod = crud_app

        import sqlite3

        class FakeConnection:
            def execute(self, query="", *args, **kwargs):
                if "auth_fail_log" in query:
                    class _C:
                        def fetchone(self): return {"n": 0}
                        def fetchall(self): return []
                    return _C()
                raise sqlite3.OperationalError(
                    "no such table: audit_log"
                )

            def close(self):
                pass

        monkeypatch.setattr(mod, "get_db", lambda: FakeConnection())

        r = client.get(
            "/api/audit-log",
            headers={
                **basic_auth_headers('admin', 'test-admin-password'),
                'X-Requested-With': 'XMLHttpRequest'
            }
        )

        assert r.status_code == 400

        data = r.get_json()

        assert data["success"] is False
        assert "audit_log no disponible" in data["error"]

def test_rate_limit_intentos_fallidos_devuelve_429(crud_app):
    client, mod = crud_app

    mod._AUTH_FAIL_STORAGE.reset()

    try:
        for _ in range(5):
            r = client.get('/api/estadisticas')
            assert r.status_code == 401

        r = client.get('/api/estadisticas')

        assert r.status_code == 429
        data = r.get_json()
        assert data['success'] is False
        assert 'Demasiados intentos fallidos' in data['error']
    finally:
        mod._AUTH_FAIL_STORAGE.reset()

def test_allowed_subnet_bloquea_ip_fuera_de_red(crud_app, monkeypatch):
    client, mod = crud_app

    monkeypatch.setattr(
        mod,
        '_ALLOWED_NETWORKS',
        [mod.ipaddress.ip_network('192.168.1.0/24')]
    )

    try:
        with client.get(
            '/api/estadisticas',
            environ_base={'REMOTE_ADDR': '10.0.0.50'}
        ) as response:
            assert response.status_code == 403
            assert response.data == b'Acceso denegado.'
    finally:
        monkeypatch.setattr(mod, '_ALLOWED_NETWORKS', None)

def test_allowed_subnet_permite_ip_dentro_de_red(crud_app, monkeypatch):
    client, mod = crud_app

    monkeypatch.setattr(
        mod,
        '_ALLOWED_NETWORKS',
        [mod.ipaddress.ip_network('192.168.1.0/24')]
    )

    try:
        response = client.get(
            '/api/estadisticas',
            environ_base={'REMOTE_ADDR': '192.168.1.77'}
        )

        assert response.status_code == 401
        assert response.headers.get('WWW-Authenticate') == 'Basic realm="RFID Admin"'
    finally:
        monkeypatch.setattr(mod, '_ALLOWED_NETWORKS', None)

def test_allowed_subnet_disabled_no_bloquea_ip_externa(crud_app, monkeypatch):
    client, mod = crud_app

    monkeypatch.setattr(mod, '_ALLOWED_NETWORKS', None)

    response = client.get(
        '/api/estadisticas',
        environ_base={'REMOTE_ADDR': '10.0.0.50'}
    )

    assert response.status_code == 401

def test_backup_registra_auditoria(crud_app):
    client, mod = crud_app

    response = client.post(
        '/api/software/database/backup',
        headers=basic_auth_headers('admin', 'test-admin-password')
    )

    assert response.status_code == 200

    audit_response = client.get(
        '/api/audit-log',
        headers=basic_auth_headers('admin', 'test-admin-password')
    )

    assert audit_response.status_code == 200

    data = audit_response.get_json()
    assert data['success'] is True

    backups = [
        row for row in data.get('registros', [])
        if row.get('accion') == 'software_database_backup'
    ]

    assert backups

    latest = backups[-1]
    assert latest['resultado'] == 'éxito'
