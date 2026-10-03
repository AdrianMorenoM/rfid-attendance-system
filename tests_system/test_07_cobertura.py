"""Pruebas dirigidas a lo que la cobertura sin pragmas mostró como no ejecutado."""
import io
import os
import sqlite3
from contextlib import closing

import pytest
from PIL import Image

import syslib
from conftest import _importar


def _png(modo="RGB", size=(4, 4)):
    buf = io.BytesIO()
    color = (200, 30, 30, 128) if modo == "RGBA" else (200, 30, 30)
    Image.new(modo, size, color).save(buf, "PNG")
    return buf.getvalue()


class TestEliminarFotoDisco:
    def test_borra_la_foto_indicada(self, crud_app, tmp_path, monkeypatch):
        _, m = crud_app
        fotos = tmp_path / "fotos"
        fotos.mkdir()
        (fotos / "a.jpg").write_bytes(b"x")
        monkeypatch.setattr(m, "FOTOS", str(fotos))
        m._eliminar_foto_disco("/static/fotos/a.jpg")
        assert not (fotos / "a.jpg").exists()

    def test_no_sale_del_directorio_de_fotos(self, crud_app, tmp_path, monkeypatch):
        _, m = crud_app
        fotos = tmp_path / "fotos"
        fotos.mkdir()
        fuera = tmp_path / "rfid.db"
        fuera.write_bytes(b"datos")
        monkeypatch.setattr(m, "FOTOS", str(fotos))
        for url in ("../rfid.db", "/static/fotos/../../rfid.db", "../../shared/rfid.db"):
            m._eliminar_foto_disco(url)
        assert fuera.exists(), "un foto_url con traversal borró un archivo fuera de FOTOS"

    def test_tolera_valores_vacios_o_inexistentes(self, crud_app, tmp_path, monkeypatch):
        _, m = crud_app
        monkeypatch.setattr(m, "FOTOS", str(tmp_path))
        for url in (None, "", "/static/fotos/", "/static/fotos/no_existe.jpg"):
            m._eliminar_foto_disco(url)  # no debe lanzar


class TestErroresDeValidacion:
    def test_perfil_de_estudiante_inexistente_da_404(self, crud_app):
        client, _ = crud_app
        r = client.get("/api/estudiantes/999999/perfil", headers=syslib.auth_headers())
        assert r.status_code == 404 and r.get_json()["success"] is False

    def test_tarjeta_sin_uid_da_400(self, crud_app):
        client, _ = crud_app
        r = client.post("/api/tarjetas", json={"uid": "   "}, headers=syslib.auth_headers())
        assert r.status_code == 400

    def test_bulk_toggle_sin_ids_validos_da_400(self, crud_app):
        client, _ = crud_app
        r = client.post("/api/tarjetas/bulk-toggle", json={"ids": ["x", "-3"]},
                        headers=syslib.auth_headers())
        assert r.status_code == 400


class TestUploadFoto:
    def _subir(self, client, contenido, nombre="foto.png"):
        return client.post("/api/upload-foto", headers=syslib.auth_headers(),
                           content_type="multipart/form-data",
                           data={"foto": (io.BytesIO(contenido), nombre)})

    def test_png_con_transparencia_se_guarda_como_jpg_rgb(self, crud_app, tmp_path, monkeypatch):
        client, m = crud_app
        monkeypatch.setattr(m, "FOTOS", str(tmp_path))
        r = self._subir(client, _png("RGBA"))
        assert r.status_code == 200, r.get_json()
        with Image.open(tmp_path / os.path.basename(r.get_json()["foto_url"])) as img:
            assert img.format == "JPEG" and img.mode == "RGB"

    def test_imagen_mas_grande_que_el_limite_se_reduce(self, crud_app, tmp_path, monkeypatch):
        client, m = crud_app
        monkeypatch.setattr(m, "FOTOS", str(tmp_path))
        limite = m.MAX_DIMENSION_FOTO
        r = self._subir(client, _png("RGB", (limite + 50, 20)))
        assert r.status_code == 200, r.get_json()
        with Image.open(tmp_path / os.path.basename(r.get_json()["foto_url"])) as img:
            assert max(img.size) <= limite

    def test_si_no_puede_guardar_responde_400(self, crud_app, tmp_path, monkeypatch):
        client, m = crud_app
        monkeypatch.setattr(m, "FOTOS", str(tmp_path / "no_existe"))
        r = self._subir(client, _png())
        assert r.status_code == 400


def test_csv_de_registros_neutraliza_formulas(crud_app, tmp_db):
    client, m = crud_app
    with closing(sqlite3.connect(tmp_db)) as c:
        cur = c.execute(
            "INSERT INTO estudiantes (nombre, apellido_paterno, matricula, carrera, semestre, grupo, estado) "
            "VALUES (?,?,?,?,?,?,?)", ("=1+1", "Prueba", "T070001", m.CARRERA, 1, "A", "activo"))
        c.execute(
            "INSERT INTO registros_asistencia (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje) "
            "VALUES (?,?,?,?,?,?)", (cur.lastrowid, "AABBCCDD", "2026-01-15 10:00:00", "2026-01-15", "aceptado", "ok"))
        c.commit()
    r = client.get("/api/export/registros?fecha=2026-01-15", headers=syslib.auth_headers())
    cuerpo = r.get_data(as_text=True)
    assert r.status_code == 200 and cuerpo.startswith("\ufeff")
    assert "'=1+1 Prueba" in cuerpo, "la fórmula no quedó neutralizada"
    assert ",=1+1" not in cuerpo and "\n=1+1" not in cuerpo


@pytest.fixture
def crud_app_produccion(guard, tmp_db, monkeypatch, tmp_path):
    """Como crud_app, pero SIN ALLOW_HTTP_MIGRATIONS: la configuración real de producción."""
    for k, v in dict(ADMIN_USER="admin", ADMIN_PASSWORD=syslib.TEST_PWD, ALLOWED_SUBNET="disabled").items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ALLOW_HTTP_MIGRATIONS", raising=False)
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
    m.app.config["PROPAGATE_EXCEPTIONS"] = False
    with m.app.test_client() as client:
        yield client, m


def test_migrate_esta_cerrado_sin_la_variable(crud_app_produccion):
    client, m = crud_app_produccion
    assert m.ALLOW_HTTP_MIGRATIONS is False
    r = client.post("/api/migrate", headers=syslib.auth_headers())
    assert r.status_code == 404


def test_get_db_del_lector_cierra_la_conexion_si_falla_la_configuracion(reader, monkeypatch):
    class _Falsa:
        cerrada = False
        row_factory = None

        def execute(self, *_):
            raise sqlite3.DatabaseError("file is not a database")

        def close(self):
            self.cerrada = True

    falsa = _Falsa()
    monkeypatch.setattr(reader.sqlite3, "connect", lambda *a, **k: falsa)
    with pytest.raises(sqlite3.DatabaseError):
        reader.get_db()
    assert falsa.cerrada, "get_db dejó abierta la conexión cuando el PRAGMA falló"
