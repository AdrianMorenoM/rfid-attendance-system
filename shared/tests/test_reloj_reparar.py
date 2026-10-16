# Pruebas de rfid_reloj.py: corrección de horas con anclas de arranque.
import os, sys, sqlite3, pytest
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.dirname(_HERE)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import rfid_reloj as rl

AHORA = datetime(2026, 10, 15, 7, 5, 0)


@pytest.fixture()
def con_reloj(tmp_db):
    c = sqlite3.connect(tmp_db)
    rl.asegurar_esquema(c)
    yield c
    c.close()


def _insertar(c, uid, ts, fecha, tipo="aceptado", msg="Acceso permitido", boot="b1", up=None, conf=0):
    cur = c.execute(
        "INSERT INTO registros_asistencia "
        "(uid, timestamp, fecha_dia, tipo_evento, mensaje, boot_id, uptime_s, reloj_confiable) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uid, ts, fecha, tipo, msg, boot, up, conf))
    c.commit()
    return cur.lastrowid


def _fila(c, rid):
    return c.execute(
        "SELECT timestamp, fecha_dia, tipo_evento, mensaje, reloj_confiable, timestamp_original "
        "FROM registros_asistencia WHERE id = ?", (rid,)).fetchone()


def test_recalcula_la_hora_con_el_ancla(con_reloj):
    a = _insertar(con_reloj, "U1", "2026-10-14 07:00:00", "2026-10-14", up=100.0)
    b = _insertar(con_reloj, "U2", "2026-10-14 07:01:00", "2026-10-14", up=160.0)
    res = rl.reparar(con_reloj, "b1", 200.0, AHORA, True)
    assert res["ancla_creada"] and res["corregidas"] == 2
    fa = _fila(con_reloj, a)
    assert fa[:2] == ("2026-10-15 07:03:20", "2026-10-15")
    assert fa[4] == 2 and fa[5] == "2026-10-14 07:00:00"
    assert _fila(con_reloj, b)[:2] == ("2026-10-15 07:04:20", "2026-10-15")


def test_no_hace_nada_si_el_reloj_no_es_confiable(con_reloj):
    a = _insertar(con_reloj, "U1", "2026-10-14 07:00:00", "2026-10-14", up=100.0)
    res = rl.reparar(con_reloj, "b1", 200.0, AHORA, False)
    assert res["corregidas"] == 0 and not res["ancla_creada"]
    assert _fila(con_reloj, a)[0] == "2026-10-14 07:00:00"
    assert con_reloj.execute("SELECT COUNT(*) FROM reloj_anclas").fetchone()[0] == 0


def test_es_idempotente(con_reloj):
    _insertar(con_reloj, "U1", "2026-10-14 07:00:00", "2026-10-14", up=100.0)
    rl.reparar(con_reloj, "b1", 200.0, AHORA, True)
    res = rl.reparar(con_reloj, "b1", 260.0, datetime(2026, 10, 15, 7, 6, 0), True)
    assert res["corregidas"] == 0 and not res["ancla_creada"]


def test_reclasifica_duplicados_al_corregir_la_fecha(con_reloj):
    primero = _insertar(con_reloj, "U1", "2026-10-15 06:50:00", "2026-10-15", boot="b0", up=50.0, conf=1)
    segundo = _insertar(con_reloj, "U1", "2026-10-14 07:00:00", "2026-10-14", boot="b1", up=100.0)
    res = rl.reparar(con_reloj, "b1", 200.0, AHORA, True)
    assert res["reclasificadas"] == 1
    assert _fila(con_reloj, primero)[2] == "aceptado"
    f = _fila(con_reloj, segundo)
    assert f[2] == "ya_escaneado" and f[3] == "Ya registrado (2ª vez hoy)"


def test_lecturas_de_otro_arranque_no_se_tocan(con_reloj):
    x = _insertar(con_reloj, "U1", "2026-10-13 07:00:00", "2026-10-13", boot="otro", up=30.0)
    _insertar(con_reloj, "U2", "2026-10-14 07:00:00", "2026-10-14", boot="b1", up=100.0)
    res = rl.reparar(con_reloj, "b1", 200.0, AHORA, True)
    assert res["corregidas"] == 1 and res["pendientes_otros_arranques"] == 1
    fx = _fila(con_reloj, x)
    assert fx[0] == "2026-10-13 07:00:00" and fx[4] == 0


def test_los_rebotes_no_se_reclasifican(con_reloj):
    _insertar(con_reloj, "U1", "2026-10-15 06:50:00", "2026-10-15", boot="b0", up=50.0, conf=1)
    r = _insertar(con_reloj, "U1", "2026-10-14 07:00:00", "2026-10-14",
                  tipo="rebote", msg="Tarjeta inactiva", boot="b1", up=100.0)
    rl.reparar(con_reloj, "b1", 200.0, AHORA, True)
    f = _fila(con_reloj, r)
    assert f[2] == "rebote" and f[3] == "Tarjeta inactiva" and f[1] == "2026-10-15"
