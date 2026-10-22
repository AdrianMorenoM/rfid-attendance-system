"""La señal del modo admin no debe dejar al lector sin registrar asistencia si la web se abandona."""
import os
import time

import pytest

import syslib


@pytest.fixture
def senal_del_lector(reader, tmp_path, monkeypatch):
    flag = tmp_path / "rfid_admin_mode"
    monkeypatch.setattr(reader, "ADMIN_FLAG", str(flag))
    return reader, flag


def _envejecer(flag, segundos):
    t = time.time() - segundos
    os.utime(flag, (t, t))


class TestSenalAbandonadaEnElLector:
    def test_sin_senal_no_hay_modo_admin(self, senal_del_lector):
        reader, _ = senal_del_lector
        assert reader._modo_admin_activo() is False

    def test_senal_reciente_activa_el_modo_admin(self, senal_del_lector):
        reader, flag = senal_del_lector
        flag.write_text("x")
        assert reader._modo_admin_activo() is True and flag.exists()

    def test_senal_abandonada_se_ignora_y_se_elimina(self, senal_del_lector):
        reader, flag = senal_del_lector
        flag.write_text("x")
        _envejecer(flag, reader.ADMIN_FLAG_MAX_AGE + 60)
        assert reader._modo_admin_activo() is False
        assert not flag.exists()

    def test_si_no_puede_borrarla_igual_la_ignora(self, senal_del_lector, monkeypatch):
        reader, flag = senal_del_lector
        flag.write_text("x")
        _envejecer(flag, reader.ADMIN_FLAG_MAX_AGE + 60)

        def _no_borrar(*a, **k):
            raise PermissionError("simulado")

        monkeypatch.setattr(reader.os, "remove", _no_borrar)
        assert reader._modo_admin_activo() is False


@pytest.fixture
def senales_crud(crud_app, tmp_path, monkeypatch):
    client, m = crud_app
    flag = tmp_path / "rfid_admin_mode"
    monkeypatch.setattr(m, "ADMIN_FLAG", str(flag))
    monkeypatch.setattr(m, "ADMIN_UID_FILE", str(tmp_path / "rfid_admin_uid"))
    monkeypatch.setattr(m, "_admin_scan_state",
                        {"active": False, "uids": [], "expires": None, "ultimo_uid_ts": None})
    return client, m, flag


def _iniciar(client, **cuerpo):
    return client.post("/api/rfid/admin-scan/start", json=cuerpo, headers=syslib.auth_headers())


class TestTimeoutDelEscaneo:
    @pytest.mark.parametrize("valor", ["abc", None, [], {}, 0, -5])
    def test_invalido_da_400_y_no_deja_la_senal_puesta(self, senales_crud, valor):
        client, m, flag = senales_crud
        r = _iniciar(client, timeout=valor)
        assert r.status_code == 400, r.get_json()
        assert not flag.exists(), "dejó la señal puesta: el lector dejaría de registrar asistencia"
        assert m._admin_scan_state["active"] is False

    def test_infinito_da_400(self, senales_crud):
        client, _, flag = senales_crud
        r = client.post("/api/rfid/admin-scan/start", data='{"timeout": Infinity}',
                        content_type="application/json", headers=syslib.auth_headers())
        assert r.status_code == 400 and not flag.exists()

    def test_acepta_un_numero_escrito_como_texto(self, senales_crud):
        client, _, flag = senales_crud
        r = _iniciar(client, timeout="60")
        assert r.status_code == 200 and r.get_json()["timeout"] == 60 and flag.exists()

    def test_limita_el_timeout_a_lo_que_respeta_el_lector(self, senales_crud):
        client, _, _ = senales_crud
        assert _iniciar(client, timeout=99999).get_json()["timeout"] == 600
