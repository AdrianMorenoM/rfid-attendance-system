import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'crud'))
import reloj_api


def test_ignora_respuesta_vieja(tmp_path, monkeypatch):
    res = tmp_path / 'fijar_hora.res'
    res.write_text('0 OK\n')
    previa = reloj_api._firma(str(res))
    monkeypatch.setattr(reloj_api, 'ESPERA_S', 0.5)
    assert reloj_api._esperar_respuesta(str(res), previa) == (None, '')


def test_acepta_respuesta_nueva(tmp_path):
    res = tmp_path / 'fijar_hora.res'
    previa = reloj_api._firma(str(res))
    res.write_text('2 ya sincronizado\n')
    assert reloj_api._esperar_respuesta(str(res), previa) == (2, 'ya sincronizado')
