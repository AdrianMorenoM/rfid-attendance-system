"""Modo de escaneo admin (asignar tarjetas desde la web). Las señales /run/rfid-shared/* se
redirigen a un directorio temporal: ninguna prueba toca los archivos que lee el lector real."""
import os
import time

import pytest

import syslib

TS = "2026-01-01T10:00:00"


@pytest.fixture
def senales(crud_app, tmp_path, monkeypatch):
    client, m = crud_app
    flag, uidf = tmp_path / "rfid_admin_mode", tmp_path / "rfid_admin_uid"
    monkeypatch.setattr(m, "ADMIN_FLAG", str(flag))
    monkeypatch.setattr(m, "ADMIN_UID_FILE", str(uidf))
    monkeypatch.setattr(m, "_admin_scan_state",
                        {"active": False, "uids": [], "expires": None, "ultimo_uid_ts": None})
    return client, m, flag, uidf


def _estado(client):
    return client.get("/api/rfid/admin-scan/status", headers=syslib.auth_headers()).get_json()


def _iniciar(client, **cuerpo):
    return client.post("/api/rfid/admin-scan/start", json=cuerpo, headers=syslib.auth_headers())


class TestLeerUidAdmin:
    def test_sin_archivo(self, senales):
        _, m, _, _ = senales
        assert m._leer_uid_admin() == (None, None)

    def test_lee_uid_y_marca_de_tiempo_y_consume_el_archivo(self, senales):
        _, m, _, uidf = senales
        uidf.write_text(f"{TS}\tAABBCCDD\n")
        assert m._leer_uid_admin() == ("AABBCCDD", TS)
        assert not uidf.exists()

    def test_formato_sin_marca_de_tiempo(self, senales):
        _, m, _, uidf = senales
        uidf.write_text("AABBCCDD\n")
        uid, ts = m._leer_uid_admin()
        assert uid == "AABBCCDD" and ts

    def test_archivo_vacio(self, senales):
        _, m, _, uidf = senales
        uidf.write_text("")
        assert m._leer_uid_admin() == (None, None)
        assert not uidf.exists()

    def test_ruta_ilegible_devuelve_none(self, senales, tmp_path, monkeypatch):
        _, m, _, _ = senales
        carpeta = tmp_path / "carpeta"
        carpeta.mkdir()
        monkeypatch.setattr(m, "ADMIN_UID_FILE", str(carpeta))  # existe pero no se puede abrir como archivo
        assert m._leer_uid_admin() == (None, None)

    def test_archivo_que_desaparece_entre_la_comprobacion_y_la_lectura(self, senales, monkeypatch):
        _, m, _, _ = senales
        real = os.path.exists
        monkeypatch.setattr(m.os.path, "exists", lambda p: True if p == m.ADMIN_UID_FILE else real(p))
        assert m._leer_uid_admin() == (None, None)

    @pytest.mark.parametrize("exc", [FileNotFoundError, PermissionError])
    def test_no_poder_borrar_el_archivo_no_impide_devolver_el_uid(self, senales, monkeypatch, exc):
        _, m, _, uidf = senales
        uidf.write_text(f"{TS}\tAABBCCDD\n")
        real = os.remove

        def _remove(p, *a, **k):
            if p == m.ADMIN_UID_FILE:
                raise exc("simulado")
            return real(p, *a, **k)

        monkeypatch.setattr(m.os, "remove", _remove)
        assert m._leer_uid_admin() == ("AABBCCDD", TS)


class TestIniciarEscaneo:
    def test_crea_la_senal_y_activa_el_estado(self, senales):
        client, m, flag, _ = senales
        r = _iniciar(client)
        assert r.status_code == 200 and r.get_json()["timeout"] == 300
        assert flag.exists()
        assert m._admin_scan_state["active"] is True and m._admin_scan_state["uids"] == []
        assert abs(m._admin_scan_state["expires"] - (time.time() + 300)) < 5

    def test_respeta_el_timeout_indicado(self, senales):
        client, m, _, _ = senales
        assert _iniciar(client, timeout=60).get_json()["timeout"] == 60

    def test_descarta_un_uid_pendiente_de_una_sesion_anterior(self, senales):
        client, _, _, uidf = senales
        uidf.write_text(f"{TS}\tVIEJO\n")
        assert _iniciar(client).status_code == 200
        assert not uidf.exists()

    def test_si_no_puede_crear_la_senal_responde_500(self, senales, tmp_path, monkeypatch):
        client, m, _, _ = senales
        monkeypatch.setattr(m, "ADMIN_FLAG", str(tmp_path / "no_existe" / "flag"))
        r = _iniciar(client)
        assert r.status_code == 500 and "señal" in r.get_json()["error"]


class TestEstadoDelEscaneo:
    def test_inactivo(self, senales):
        client, _, _, _ = senales
        assert _estado(client) == {"success": True, "active": False, "uids": []}

    @pytest.mark.parametrize("hay_senal", [True, False])
    def test_al_expirar_se_desactiva_y_limpia_la_senal(self, senales, hay_senal):
        client, m, flag, _ = senales
        m._admin_scan_state.update({"active": True, "expires": time.time() - 1})
        if hay_senal:
            flag.write_text("x")
        assert _estado(client)["active"] is False
        assert not flag.exists()

    def test_registra_cada_tarjeta_una_sola_vez(self, senales):
        client, _, _, uidf = senales
        _iniciar(client)
        uidf.write_text(f"{TS}\tAABBCCDD\n")
        b = _estado(client)
        assert [e["uid"] for e in b["uids"]] == ["AABBCCDD"] and b["uids"][0]["ts"] == TS
        assert not uidf.exists(), "el CRUD debe consumir la señal del lector"
        uidf.write_text("2026-01-01T10:00:05\tAABBCCDD\n")   # la misma tarjeta otra vez
        assert len(_estado(client)["uids"]) == 1
        uidf.write_text("2026-01-01T10:00:09\tBBCCDDEE\n")   # otra distinta
        assert [e["uid"] for e in _estado(client)["uids"]] == ["AABBCCDD", "BBCCDDEE"]


@pytest.mark.parametrize("delta, activo", [(-5, False), (60, True)])
def test_escucha_rfid_respeta_la_expiracion(crud_app, monkeypatch, delta, activo):
    client, m = crud_app
    monkeypatch.setattr(m, "_rfid_listen_state", {"active": True, "expires": time.time() + delta})
    body = client.get("/api/rfid/listen/status", headers=syslib.auth_headers()).get_json()
    assert body["success"] is True and body["active"] is activo
