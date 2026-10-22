"""06 · Integraciones — Nginx, Gunicorn, systemd y Tailscale (solo lectura, en vivo)."""
import json
import os
import re
import ssl

import pytest
import requests

import syslib
from syslib import CFG, TIMERS, UNITS, is_active, listeners, sh, show

pytestmark = pytest.mark.live

H = CFG["nginx_host"]
DASH_TLS = f"https://{H}:{CFG['dash_https_port']}"
CRUD_TLS = f"https://{H}:{CFG['crud_https_port']}"
OK_REDIR = (200, 301, 302, 307, 308, 401)


def _claves(r):
    j = r.json()
    return set(j) if isinstance(j, dict) else {"<lista>"}


def _pem(puerto):
    return ssl.get_server_certificate((H, puerto))


def _ip_lan():
    """IP privada de la Pi en la red local (no Tailscale, no loopback)."""
    _, out, _ = sh(["hostname", "-I"])
    for ip in out.split():
        if re.match(r"^(192\.168|10\.|172\.(1[6-9]|2\d|3[01]))\.", ip):
            return ip
    return None


def _tailscale():
    rc, out, err = sh(["tailscale", "status", "--json"])
    if rc != 0:
        pytest.skip(f"tailscale no disponible: {err[:80]}")
    return json.loads(out)


class TestNginx:
    def test_servicio_activo(self, live):
        if sh(["systemctl", "cat", "nginx"])[0] != 0:
            pytest.skip("unidad nginx no encontrada")
        assert is_active("nginx")

    @pytest.mark.parametrize("puerto", [CFG["dash_http_port"], CFG["dash_https_port"],
                                        CFG["crud_http_port"], CFG["crud_https_port"]])
    def test_puertos_publicos_en_escucha(self, live, puerto):
        assert puerto in {p for _, p in listeners()}, f"nadie escucha en :{puerto}"

    def test_proxy_https_al_dashboard(self, live):
        directo = live.get(CFG["dash_url"] + "/api/estado", timeout=15)
        via = live.get(DASH_TLS + "/api/estado", timeout=15)
        assert via.status_code == 200
        assert _claves(via) == _claves(directo)

    def test_proxy_https_al_crud(self, live):
        directo = live.get(CFG["crud_url"] + "/api/estadisticas", timeout=15)
        via = live.get(CRUD_TLS + "/api/estadisticas", timeout=15)
        assert via.status_code == 200
        assert _claves(via) == _claves(directo)

    @pytest.mark.parametrize("base", [f"http://{H}:{CFG['dash_http_port']}", f"http://{H}:{CFG['crud_http_port']}"])
    def test_puertos_http_responden_o_redirigen(self, live, base):
        r = requests.get(base + "/", timeout=10, allow_redirects=False)
        assert r.status_code in OK_REDIR, f"{base} → {r.status_code}"

    @pytest.mark.parametrize("puerto,ruta", [(CFG["dash_https_port"], "/api/estado"),
                                             (CFG["crud_https_port"], "/api/estadisticas")])
    def test_rechaza_conexiones_que_no_vienen_de_tailscale_ni_de_la_pi(self, live, puerto, ruta):
        """Nginx debe aceptar solo 127.0.0.1 y la red Tailscale. Se conecta a la IP de LAN de la propia
        Pi (el origen será esa IP) y, incluso con credenciales válidas, debe recibir 403."""
        ip = _ip_lan()
        if not ip:
            pytest.skip("la Pi no tiene una IP de LAN privada")
        r = requests.get(f"https://{ip}:{puerto}{ruta}", auth=syslib.admin_creds(), verify=False, timeout=10)
        assert r.status_code == 403, \
            f"https://{ip}:{puerto}{ruta} → {r.status_code}: Nginx acepta conexiones desde la red local"

    @pytest.mark.parametrize("base,ruta", [(DASH_TLS, "/api/estado"), (CRUD_TLS, "/api/estadisticas")])
    def test_nginx_reenvia_la_autenticacion(self, live, base, ruta):
        if base == DASH_TLS and os.environ.get("RFID_DASH_PUBLICO") == "1":
            pytest.skip("RFID_DASH_PUBLICO=1: dashboard sin login en la app (público o protegido por Nginx)")
        assert requests.get(base + ruta, verify=False, timeout=10).status_code == 401

    @pytest.mark.parametrize("puerto", [CFG["dash_https_port"], CFG["crud_https_port"]])
    def test_certificado_tls_vigente(self, live, puerto):
        pem = _pem(puerto)
        rc, _, err = sh(["openssl", "x509", "-noout", "-checkend", str(CFG["cert_min_days"] * 86400)], input_=pem)
        if rc == 127:
            pytest.skip("openssl no instalado")
        assert rc == 0, f"el certificado de :{puerto} vence en menos de {CFG['cert_min_days']} días ({err})"


class TestGunicorn:
    @pytest.mark.parametrize("puerto", [5000, 5001])
    def test_solo_escucha_en_localhost(self, live, puerto):
        direcciones = [a for a, p in listeners() if p == puerto]
        assert direcciones, f"gunicorn no escucha en :{puerto}"
        assert all(a in ("127.0.0.1", "[::1]") for a in direcciones), f":{puerto} expuesto en {direcciones}"

    @pytest.mark.parametrize("unit,esperados", [("rfid-crud.service", None), ("rfid-dashboard.service", None)])
    def test_numero_de_workers_coincide_con_la_unidad(self, live, unit, esperados):
        _, cfg, _ = sh(["systemctl", "cat", unit])
        m = re.search(r"-w\s+(\d+)", cfg)
        assert m, f"{unit} no define -w"
        main = show(unit, "MainPID")["MainPID"]
        _, hijos, _ = sh(["pgrep", "-P", main])
        assert len(hijos.split()) == int(m.group(1)), f"workers vivos {len(hijos.split())} ≠ -w {m.group(1)}"

    @pytest.mark.parametrize("unit", ["rfid-crud.service", "rfid-dashboard.service", "rfid-reader.service"])
    def test_no_corre_como_root(self, live, unit):
        pid = show(unit, "MainPID")["MainPID"]
        _, usuario, _ = sh(["ps", "-o", "user=", "-p", pid])
        assert usuario and usuario != "root", f"{unit} corre como {usuario!r}"


class TestSystemd:
    @pytest.mark.parametrize("unit", UNITS)
    def test_unidades_activas_y_habilitadas(self, live, unit):
        assert is_active(unit), f"{unit} no está activa"
        assert sh(["systemctl", "is-enabled", unit])[1] == "enabled"

    @pytest.mark.parametrize("unit", UNITS)
    def test_endurecimiento_basico(self, live, unit):
        p = show(unit, "NoNewPrivileges", "PrivateTmp", "UMask", "User")
        assert p["NoNewPrivileges"] == "yes"
        assert p["PrivateTmp"] == "yes"
        assert p["UMask"] in ("0077", "077")
        assert p["User"] == "rfid-svc"

    @pytest.mark.parametrize("unit", ["rfid-crud.service", "rfid-dashboard.service"])
    def test_killmode_control_group_evita_workers_huerfanos(self, live, unit):
        assert show(unit, "KillMode")["KillMode"] == "control-group"

    @pytest.mark.parametrize("timer", TIMERS)
    def test_timers_activos_con_proxima_ejecucion(self, live, timer):
        assert sh(["systemctl", "is-enabled", timer])[1] == "enabled"
        assert is_active(timer)
        assert show(timer, "NextElapseUSecRealtime")["NextElapseUSecRealtime"], f"{timer} sin próxima ejecución"

    def test_vacuum_programado_a_las_0330(self, live):
        assert "03:30" in show("rfid-incremental-vacuum.timer", "TimersCalendar")["TimersCalendar"]

    def test_ultima_ejecucion_del_vacuum_fue_exitosa(self, live):
        p = show("rfid-incremental-vacuum.service", "Result", "ExecMainStatus", "ExecMainExitTimestamp")
        if not p.get("ExecMainExitTimestamp"):
            # systemd descarga los oneshot terminados y pierde el timestamp: usar el log
            import pathlib
            log = pathlib.Path(__file__).resolve().parent.parent / "shared" / "incremental_vacuum.log"
            if not log.exists():
                pytest.skip("el vacuum aún no se ha ejecutado")
            lineas = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
            assert lineas and "incremental_vacuum OK" in lineas[-1], lineas[-1:]
            return
        assert p["Result"] == "success" and p["ExecMainStatus"] == "0"

    def test_no_hay_unidades_rfid_en_estado_failed(self, live):
        _, out, _ = sh(["systemctl", "--failed", "--no-legend", "--plain"])
        fallidas = [l.split()[0] for l in out.splitlines() if l.startswith("rfid-")]
        assert not fallidas, f"unidades fallidas: {fallidas}"


class TestTailscale:
    def test_daemon_conectado(self, live):
        ts = _tailscale()
        assert ts["BackendState"] == "Running"
        assert ts["Self"]["Online"] is True

    def test_tiene_ip_de_tailnet(self, live):
        ips = _tailscale()["Self"]["TailscaleIPs"]
        assert any(ip.startswith("100.") for ip in ips), ips

    def test_servicios_accesibles_por_la_ip_de_tailscale(self, live):
        ip = next(i for i in _tailscale()["Self"]["TailscaleIPs"] if i.startswith("100."))
        a = live.get(f"https://{ip}:{CFG['dash_https_port']}/api/estado", timeout=15)
        b = live.get(f"https://{ip}:{CFG['crud_https_port']}/api/estadisticas", timeout=15)
        assert (a.status_code, b.status_code) == (200, 200)

    def test_certificado_valido_para_el_nombre_de_tailscale(self, live):
        dns = _tailscale()["Self"]["DNSName"].rstrip(".")
        try:
            r = requests.get(f"https://{dns}:{CFG['dash_https_port']}/api/estado",
                             auth=syslib.admin_creds(), verify=True, timeout=15)
        except requests.exceptions.SSLError as e:
            pytest.fail(f"el certificado no es válido para {dns}: {e}")
        except requests.exceptions.ConnectionError as e:
            pytest.skip(f"{dns} no se resuelve/alcanza desde esta máquina: {str(e)[:80]}")
        assert r.status_code == 200

    def test_el_certificado_cubre_el_nombre_de_tailscale(self, live):
        dns = _tailscale()["Self"]["DNSName"].rstrip(".")
        rc, out, _ = sh(["openssl", "x509", "-noout", "-ext", "subjectAltName"], input_=_pem(CFG["dash_https_port"]))
        if rc != 0:
            pytest.skip("no se pudo leer el SAN del certificado")
        assert dns in out, f"el SAN del certificado no incluye {dns}: {out}"
