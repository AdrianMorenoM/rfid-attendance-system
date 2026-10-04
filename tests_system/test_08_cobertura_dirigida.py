"""Pruebas dirigidas a lo que la cobertura real (sin pragmas) mostró como no ejecutado:
purga de datos, lista de IPs permitidas, variables obligatorias, decorador @api y auditoría."""
import ipaddress
import os
import sqlite3
from contextlib import closing

import pytest

import syslib

CARRERA_PRUEBA = "PURGA-TEST"


def _sembrar(tmp_db, m, matricula, fechas, carrera=None, semestre=1, grupo="A"):
    """Crea un estudiante con un registro por fecha. Devuelve su id."""
    with closing(sqlite3.connect(tmp_db)) as c:
        cur = c.execute(
            "INSERT INTO estudiantes (nombre, apellido_paterno, matricula, carrera, semestre, grupo, estado) "
            "VALUES (?,?,?,?,?,?,?)",
            ("Purga", "Prueba", matricula, carrera or m.CARRERA, semestre, grupo, "activo"))
        eid = cur.lastrowid
        for f in fechas:
            c.execute(
                "INSERT INTO registros_asistencia (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje) "
                "VALUES (?,?,?,?,?,?)", (eid, "UIDPURGA", f + " 10:00:00", f, "aceptado", "ok"))
        c.commit()
    return eid


def _n(tmp_db, eid):
    return syslib.q(tmp_db).execute(
        "SELECT COUNT(*) FROM registros_asistencia WHERE id_estudiante = ?", (eid,)).fetchone()[0]


def _total(tmp_db):
    return syslib.q(tmp_db).execute("SELECT COUNT(*) FROM registros_asistencia").fetchone()[0]


def _purgar(client, cuerpo):
    return client.post("/api/software/database/purge", json=cuerpo, headers=syslib.auth_headers())


def _vista_previa(client, cuerpo):
    return client.post("/api/software/database/purge/preview", json=cuerpo, headers=syslib.auth_headers())


class TestPurga:
    def test_sin_confirmacion_no_borra(self, crud_app, tmp_db):
        client, m = crud_app
        eid = _sembrar(tmp_db, m, "PURGA-1", ["2001-01-01", "2001-01-02"])
        for cuerpo in ({"matricula": "PURGA-1"}, {"matricula": "PURGA-1", "confirm": False}):
            assert _purgar(client, cuerpo).status_code == 400
        assert _n(tmp_db, eid) == 2

    def test_vista_previa_y_ejecucion_cuentan_lo_mismo(self, crud_app, tmp_db):
        client, m = crud_app
        eid = _sembrar(tmp_db, m, "PURGA-2", ["2001-01-01", "2001-01-02", "2001-01-03"])
        previa = _vista_previa(client, {"matricula": "PURGA-2"}).get_json()
        assert previa["success"] and previa["count"] == 3
        assert _n(tmp_db, eid) == 3, "la vista previa no debe borrar"
        r = _purgar(client, {"matricula": "PURGA-2", "confirm": True})
        body = r.get_json()
        assert r.status_code == 200 and body["deleted"] == previa["count"]
        assert _n(tmp_db, eid) == 0
        existe = syslib.q(tmp_db).execute("SELECT COUNT(*) FROM estudiantes WHERE id = ?", (eid,)).fetchone()[0]
        assert existe == 1, "la purga de registros no debe borrar al estudiante"
        assert os.path.isfile(os.path.join(m.BACKUP_DIR, body["safety_backup"])), "falta el respaldo previo"

    @pytest.mark.parametrize("desde, hasta", [
        ("2001-02-01", "2001-02-28"),
        ("2001-02-10 00:00:00", "2001-02-10 23:59:59"),
    ])
    def test_rango_de_fechas_borra_solo_el_rango(self, crud_app, tmp_db, desde, hasta):
        client, m = crud_app
        eid = _sembrar(tmp_db, m, "PURGA-3", ["2001-01-10", "2001-02-10", "2001-03-10"])
        r = _purgar(client, {"matricula": "PURGA-3", "fecha_desde": desde, "fecha_hasta": hasta, "confirm": True})
        assert r.status_code == 200 and r.get_json()["deleted"] == 1, r.get_json()
        assert _n(tmp_db, eid) == 2

    @pytest.mark.parametrize("filtros, objetivo", [
        (lambda a, b: {"carrera": CARRERA_PRUEBA, "semestre": 8}, "a"),
        (lambda a, b: {"carrera": CARRERA_PRUEBA, "grupo": "zb"}, "b"),
        (lambda a, b: {"matricula": "  PURGA-A  "}, "a"),
        (lambda a, b: {"estudiante_id": b}, "b"),
    ], ids=["carrera+semestre", "grupo sin mayusculas", "matricula con espacios", "id de estudiante"])
    def test_cada_filtro_borra_solo_lo_suyo(self, crud_app, tmp_db, filtros, objetivo):
        client, m = crud_app
        a = _sembrar(tmp_db, m, "PURGA-A", ["2001-05-01", "2001-05-02"], CARRERA_PRUEBA, 8, "ZA")
        b = _sembrar(tmp_db, m, "PURGA-B", ["2001-05-01", "2001-05-02"], CARRERA_PRUEBA, 9, "ZB")
        r = _purgar(client, {**filtros(a, b), "confirm": True})
        assert r.status_code == 200 and r.get_json()["deleted"] == 2, r.get_json()
        borrado, intacto = (a, b) if objetivo == "a" else (b, a)
        assert _n(tmp_db, borrado) == 0 and _n(tmp_db, intacto) == 2

    def test_valores_hostiles_en_los_filtros_no_borran_de_mas(self, crud_app, tmp_db):
        client, m = crud_app
        _sembrar(tmp_db, m, "PURGA-4", ["2001-01-01"])
        antes = _total(tmp_db)
        for campo in ("carrera", "grupo", "matricula", "semestre"):
            r = _purgar(client, {campo: "x' OR '1'='1", "confirm": True})
            assert r.status_code == 200 and r.get_json()["deleted"] == 0, (campo, r.get_json())
        assert _total(tmp_db) == antes

    def test_id_no_numerico_da_400_y_no_borra(self, crud_app, tmp_db):
        client, m = crud_app
        eid = _sembrar(tmp_db, m, "PURGA-5", ["2001-01-01"])
        assert _vista_previa(client, {"estudiante_id": "abc"}).status_code == 400
        assert _purgar(client, {"estudiante_id": "abc", "confirm": True}).status_code == 400
        assert _n(tmp_db, eid) == 1

    def test_si_falla_el_respaldo_previo_no_se_borra_nada(self, crud_app, tmp_db, monkeypatch):
        client, m = crud_app
        eid = _sembrar(tmp_db, m, "PURGA-6", ["2001-01-01", "2001-01-02"])

        def _sin_disco():
            raise OSError("disco lleno")

        monkeypatch.setattr(m, "_crear_backup", _sin_disco)
        r = _purgar(client, {"matricula": "PURGA-6", "confirm": True})
        assert r.status_code == 500 and "respaldo" in r.get_json()["error"].lower()
        assert _n(tmp_db, eid) == 2, "la purga borró datos aunque no pudo respaldarlos"
        quedo = syslib.q(tmp_db).execute(
            "SELECT COUNT(*) FROM audit_log WHERE accion = 'software_database_purge' AND resultado = 'error'"
        ).fetchone()[0]
        assert quedo >= 1, "el fallo de la purga no quedó en la auditoría"


class TestListaDeIPs:
    @pytest.mark.parametrize("raw, esperado", [
        (None, None), ("", None), ("disabled", None), ("DISABLED", None),
        ("10.0.0.0/8, ,192.168.1.5/24", ["10.0.0.0/8", "192.168.1.0/24"]),
    ])
    def test_interpreta_la_configuracion(self, crud_app, raw, esperado):
        _, m = crud_app
        res = m._parse_allowed_networks(raw)
        assert (None if res is None else [str(n) for n in res]) == esperado

    def test_un_valor_invalido_aborta_el_arranque(self, crud_app):
        _, m = crud_app
        with pytest.raises(SystemExit):
            m._parse_allowed_networks("10.0.0.0/8, esto-no-es-una-red")

    def test_deniega_fuera_de_la_lista_y_ante_direcciones_ilegibles(self, crud_app, monkeypatch):
        client, m = crud_app
        monkeypatch.setattr(m, "_ALLOWED_NETWORKS", [ipaddress.ip_network("192.168.1.0/24")])
        h = syslib.auth_headers()
        ok = client.get("/api/health/db", headers=h, environ_base={"REMOTE_ADDR": "192.168.1.77"})
        assert ok.status_code != 403
        for remota in ("10.9.9.9", "garbage", "", "999.1.1.1"):
            r = client.get("/api/health/db", headers=h, environ_base={"REMOTE_ADDR": remota})
            assert r.status_code == 403, f"REMOTE_ADDR={remota!r} no fue rechazado"


class TestVariablesObligatorias:
    def test_devuelve_el_valor_si_existe(self, crud_app, monkeypatch):
        _, m = crud_app
        monkeypatch.setenv("VAR_DE_PRUEBA_RFID", "valor")
        assert m._get_required_env("VAR_DE_PRUEBA_RFID") == "valor"

    @pytest.mark.parametrize("valor", [None, ""])
    def test_aborta_si_falta_o_esta_vacia(self, crud_app, monkeypatch, valor):
        _, m = crud_app
        if valor is None:
            monkeypatch.delenv("VAR_DE_PRUEBA_RFID", raising=False)
        else:
            monkeypatch.setenv("VAR_DE_PRUEBA_RFID", valor)
        with pytest.raises(SystemExit):
            m._get_required_env("VAR_DE_PRUEBA_RFID")


class TestDecoradorApi:
    @staticmethod
    def _llamar(m, excepcion):
        @m.api
        def ruta():
            raise excepcion

        with m.app.test_request_context():
            resp, status = ruta()
        return resp.get_json(), status

    def test_error_inesperado_da_500_sin_filtrar_detalles(self, crud_app):
        _, m = crud_app
        for exc in (RuntimeError("secreto /home/admin/rfid-system/.env"),
                    sqlite3.OperationalError("no such table: usuarios_secretos")):
            cuerpo, status = self._llamar(m, exc)
            assert status == 500 and cuerpo == {"success": False, "error": "Error interno"}

    @pytest.mark.parametrize("mensaje, esperado", [
        ("NOT NULL constraint failed: estudiantes.nombre", "Faltan campos requeridos."),
        ("CHECK constraint failed: semestre", "Los datos no cumplen con las reglas de validación."),
        ("FOREIGN KEY constraint failed", "Los datos no cumplen con las reglas de validación."),
    ])
    def test_errores_de_integridad_dan_400_con_mensaje_generico(self, crud_app, mensaje, esperado):
        _, m = crud_app
        cuerpo, status = self._llamar(m, sqlite3.IntegrityError(mensaje))
        assert status == 400 and cuerpo["error"] == esperado


class TestAuditoria:
    def test_un_fallo_al_registrar_no_rompe_la_operacion(self, crud_app, monkeypatch):
        _, m = crud_app

        def _sin_bd():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(m, "get_db", _sin_bd)
        assert m._registrar_auditoria("accion_de_prueba", "detalle", "éxito", ip="127.0.0.1") is None
