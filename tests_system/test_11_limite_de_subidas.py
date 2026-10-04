"""El tamaño máximo de las subidas debe coincidir de punta a punta: Nginx no puede cortar antes
que la aplicación. (Nginx traía 1 MB por defecto y rechazaba fotos que Flask sí aceptaba.)"""
import re

import pytest

import syslib
from syslib import CFG

MB = 1024 * 1024


def _limite_de_la_app():
    fuente = (syslib.CRUD_DIR / "app_crud.py").read_text(encoding="utf-8")
    m = re.search(r"MAX_CONTENT_LENGTH'\]\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024", fuente)
    assert m, "no encontré MAX_CONTENT_LENGTH en app_crud.py"
    return int(m.group(1)) * MB


LIMITE = _limite_de_la_app()


def _subir(live, clave_puerto, tls, nbytes):
    url = f"{'https' if tls else 'http'}://{CFG['nginx_host']}:{CFG[clave_puerto]}/api/upload-foto"
    return live.post(url, headers={"X-Requested-With": "XMLHttpRequest"},
                     files={"foto": ("prueba.png", b"\0" * nbytes, "image/png")}, timeout=60)


@pytest.mark.live
@pytest.mark.parametrize("clave_puerto, tls", [("crud_https_port", True)])   # el puerto HTTP (8001) solo redirige a HTTPS: no sirve subidas
class TestLimiteDeSubidas:
    def test_un_archivo_dentro_del_limite_de_la_app_llega_a_la_app(self, live, clave_puerto, tls):
        r = _subir(live, clave_puerto, tls, LIMITE - MB)
        assert r.status_code != 413, (
            f"Nginx cortó un archivo de {(LIMITE - MB) // MB} MB que la app acepta "
            f"(su límite es {LIMITE // MB} MB): revisa client_max_body_size")
        assert r.status_code == 400, f"debía llegar a la app y no ser una imagen válida: {r.status_code}"

    def test_un_archivo_por_encima_del_limite_se_rechaza(self, live, clave_puerto, tls):
        r = _subir(live, clave_puerto, tls, LIMITE + MB // 2)
        assert r.status_code == 413, f"se aceptó un archivo mayor que el límite: {r.status_code}"
