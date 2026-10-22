"""01 · RFID end-to-end — lector simulado → rfid_reader → SQLite → CRUD → dashboard.

Todas las pruebas usan una BD temporal: nunca tocan shared/rfid.db.
"""
import sqlite3
import time
from datetime import datetime, timedelta

import pytest

import syslib
from syslib import CARDS, UID, FakeMFRC522, auth_headers


def hoy():
    return datetime.now().strftime("%Y-%m-%d")


def registros(db, where="1=1", args=()):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            f"SELECT * FROM registros_asistencia WHERE {where} ORDER BY id", args).fetchall()
    finally:
        conn.close()


def escanear(reader, card):
    """Simula: tarjeta frente al lector → leer_uid → procesar."""
    uid = reader.leer_uid(FakeMFRC522(card=card))
    assert uid is not None, "leer_uid no devolvió UID"
    return uid, reader.procesar(uid)


def sql(db, stmt, args=()):
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute(stmt, args)
        conn.commit()
    finally:
        conn.close()


class TestLecturaUID:
    @pytest.mark.parametrize("card,esperado", [
        ([0xAA, 0xBB, 0xCC, 0xDD, 0x00], str(0xAABBCCDD)),
        ([0x00, 0x00, 0x00, 0x01, 0x00], "1"),
        ([0xFF, 0xFF, 0xFF, 0xFF, 0xFF], "4294967295"),
        ([0x12, 0x34, 0x56, 0x78, 0x99], str(0x12345678)),
    ])
    def test_convierte_los_4_primeros_bytes_a_decimal(self, reader, card, esperado):
        assert reader.leer_uid(FakeMFRC522(card=card)) == esperado

    def test_sin_tarjeta_devuelve_none(self, reader):
        assert reader.leer_uid(FakeMFRC522(card=None)) is None

    def test_error_de_anticolision_devuelve_none(self, reader):
        assert reader.leer_uid(FakeMFRC522(card=CARDS["juan"], anticoll_status=FakeMFRC522.MI_ERR)) is None

    def test_uid_vacio_devuelve_none(self, reader):
        assert reader.leer_uid(FakeMFRC522(card=[])) is None

    def test_la_misma_tarjeta_da_siempre_el_mismo_uid(self, reader):
        lecturas = {reader.leer_uid(FakeMFRC522(card=CARDS["maria"])) for _ in range(10)}
        assert lecturas == {UID["maria"]}


class TestUIDValido:
    def test_estudiante_activo_es_aceptado(self, reader):
        _, (tipo, nombre, msg) = escanear(reader, CARDS["juan"])
        assert (tipo, nombre, msg) == ("aceptado", "Juan Pérez", "Acceso permitido")

    def test_fila_registrada_con_estudiante_fecha_y_uid(self, reader, tmp_db):
        uid, _ = escanear(reader, CARDS["juan"])
        (fila,) = registros(tmp_db)
        assert fila["uid"] == uid
        assert fila["id_estudiante"] == 1
        assert fila["fecha_dia"] == hoy()
        assert fila["tipo_evento"] == "aceptado"
        assert fila["timestamp"].startswith(hoy())

    def test_estudiantes_distintos_no_se_interfieren(self, reader, tmp_db):
        escanear(reader, CARDS["juan"])
        _, (tipo, nombre, _) = escanear(reader, CARDS["maria"])
        assert (tipo, nombre) == ("aceptado", "María López")
        assert len(registros(tmp_db, "tipo_evento='aceptado'")) == 2


class TestUIDInexistente:
    def test_uid_desconocido_es_rebote(self, reader):
        _, (tipo, nombre, msg) = escanear(reader, CARDS["nadie"])
        assert (tipo, nombre, msg) == ("rebote", "DESCONOCIDO", "UID no registrado")

    def test_se_registra_sin_estudiante(self, reader, tmp_db):
        uid, _ = escanear(reader, CARDS["nadie"])
        (fila,) = registros(tmp_db)
        assert fila["id_estudiante"] is None
        assert fila["uid"] == uid
        assert fila["tipo_evento"] == "rebote"

    def test_desconocido_repetido_siempre_rebota(self, reader, tmp_db):
        for _ in range(3):
            _, (tipo, _, _) = escanear(reader, CARDS["nadie"])
            assert tipo == "rebote"
        assert len(registros(tmp_db, "tipo_evento='rebote'")) == 3


class TestRegistroAsistencia:
    def test_cada_escaneo_inserta_exactamente_una_fila(self, reader, tmp_db):
        for i in range(1, 5):
            escanear(reader, CARDS["juan"])
            assert len(registros(tmp_db)) == i

    def test_cadena_completa_lector_bd_crud_dashboard(self, reader, crud_app, dash_app):
        """Un escaneo debe ser visible por la API del CRUD y por el dashboard."""
        client, _ = crud_app
        dclient, _ = dash_app
        uid, (tipo, _, _) = escanear(reader, CARDS["juan"])
        assert tipo == "aceptado"

        candidatos = ["/api/registros", f"/api/registros?fecha={hoy()}"]
        textos = []
        for url in candidatos:
            r = client.get(url, headers=auth_headers())
            assert r.status_code == 200, f"{url} → {r.status_code}"
            textos.append(r.get_data(as_text=True))
        assert any(uid in t for t in textos), "/api/registros no muestra el UID recién escaneado"

        r = client.get(f"/api/rfid/historial/{uid}", headers=auth_headers())
        assert r.status_code == 200
        assert uid in r.get_data(as_text=True) or "aceptado" in r.get_data(as_text=True)

        assert client.get("/api/asistencia/hoy", headers=auth_headers()).status_code == 200

        r = dclient.get("/api/ultimo-evento")
        assert r.status_code == 200
        t = r.get_data(as_text=True)
        assert uid in t or "Juan" in t or "aceptado" in t, "el dashboard no refleja el último evento"


class TestDuplicadoMismoDia:
    def test_segundo_escaneo_es_ya_escaneado(self, reader):
        escanear(reader, CARDS["juan"])
        _, (tipo, _, msg) = escanear(reader, CARDS["juan"])
        assert tipo == "ya_escaneado"
        assert "2" in msg

    def test_solo_hay_un_aceptado_por_dia(self, reader, tmp_db):
        for _ in range(4):
            escanear(reader, CARDS["juan"])
        assert len(registros(tmp_db, "tipo_evento='aceptado'")) == 1
        assert len(registros(tmp_db, "tipo_evento='ya_escaneado'")) == 3

    def test_el_contador_del_mensaje_avanza_en_cada_reintento(self, reader):
        """El mensaje dice 'Nª vez hoy'; en el 3er escaneo debería decir 3ª."""
        escanear(reader, CARDS["juan"])
        escanear(reader, CARDS["juan"])
        _, (_, _, msg) = escanear(reader, CARDS["juan"])
        assert "3" in msg, f"el 3er escaneo del día dice: {msg!r}"

    def test_un_aceptado_de_ayer_no_cuenta_como_duplicado(self, reader, tmp_db):
        ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        sql(tmp_db, "INSERT INTO registros_asistencia (id_estudiante, uid, timestamp, fecha_dia,"
                    " tipo_evento) VALUES (1, ?, ?, ?, 'aceptado')",
            (UID["juan"], f"{ayer} 08:00:00", ayer))
        _, (tipo, _, _) = escanear(reader, CARDS["juan"])
        assert tipo == "aceptado"

    def test_duplicado_es_por_tarjeta_no_global(self, reader):
        escanear(reader, CARDS["juan"])
        _, (tipo, _, _) = escanear(reader, CARDS["maria"])
        assert tipo == "aceptado"


class TestEstadoDelEstudiante:
    def test_estudiante_inactivo_es_rebote(self, reader):
        _, (tipo, nombre, msg) = escanear(reader, CARDS["pedro"])
        assert (tipo, nombre, msg) == ("rebote", "Pedro Gómez", "Estudiante inactivo")

    def test_tarjeta_inactiva_es_rebote(self, reader):
        _, (tipo, _, msg) = escanear(reader, CARDS["ana"])
        assert (tipo, msg) == ("rebote", "Tarjeta inactiva")

    def test_baja_y_reactivacion_se_reflejan_de_inmediato(self, reader, tmp_db):
        assert escanear(reader, CARDS["maria"])[1][0] == "aceptado"
        sql(tmp_db, "UPDATE estudiantes SET estado='inactivo' WHERE id=2")
        assert escanear(reader, CARDS["maria"])[1][0] == "rebote"
        sql(tmp_db, "UPDATE estudiantes SET estado='activo' WHERE id=2")
        # ya se aceptó hoy, así que reactivar produce 'ya_escaneado', no rebote
        assert escanear(reader, CARDS["maria"])[1][0] == "ya_escaneado"

    def test_tarjeta_huerfana_tras_borrar_estudiante_es_rebote(self, reader, tmp_db):
        sql(tmp_db, "DELETE FROM estudiantes WHERE id=1")  # FK: tarjetas.id_estudiante → NULL
        _, (tipo, nombre, _) = escanear(reader, CARDS["juan"])
        assert (tipo, nombre) == ("rebote", "Sin nombre")

    def test_solo_una_tarjeta_activa_por_estudiante(self, tmp_db):
        with pytest.raises(sqlite3.IntegrityError):
            sql(tmp_db, "INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES ('9999', 1, 1)")


class TestHardwareReal:
    @pytest.mark.hardware
    @pytest.mark.destructive
    def test_lectura_real_de_tarjeta(self, reader, capsys):
        """Detiene rfid-reader, espera 15 s una tarjeta física y lo vuelve a iniciar."""
        if not syslib.can_sudo("systemctl", "stop", "rfid-reader.service"):
            pytest.skip("sudo -n no permite detener rfid-reader.service")
        try:
            from mfrc522 import MFRC522
        except ImportError:
            pytest.skip("mfrc522 no disponible")
        syslib.sudo_systemctl("stop", "rfid-reader.service")
        try:
            try:
                lector = MFRC522()
            except Exception as e:  # SPI/GPIO sin permisos
                pytest.skip(f"No se pudo inicializar el RC522: {e}")
            with capsys.disabled():
                print("\n>>> Acerca una tarjeta al lector (15 s)...")
            uid, fin = None, time.time() + 15
            while uid is None and time.time() < fin:
                uid = reader.leer_uid(lector)
                time.sleep(0.15)
            assert uid is not None, "No se leyó ninguna tarjeta en 15 s"
            assert uid.isdigit()
        finally:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup()
            except Exception:
                pass
            syslib.sudo_systemctl("start", "rfid-reader.service")
