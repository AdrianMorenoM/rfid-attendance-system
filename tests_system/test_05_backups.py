"""05 · Backups — crear, validar, restaurar, integridad y datos.

· En proceso: ciclo completo contra el CRUD con BD y directorio de backups temporales.
· En vivo: solo se crea un backup (y se borra el mismo) y se valida el más reciente.
  NUNCA se restaura sobre la BD real.
"""
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

import syslib
from syslib import CFG, auth_headers, dump_table, integrity_ok, table_counts

PATRON = re.compile(r"rfid_backup_(\d{8})_(\d{6})\.db")
SIN_AUDITORIA = ["estudiantes", "tarjetas", "registros_asistencia"]


def crear(client):
    r = client.post("/api/software/database/backup", headers=auth_headers(), json={})
    assert r.status_code == 200, f"crear backup → {r.status_code}: {r.get_data(as_text=True)[:150]}"
    return r.get_json()


def ruta(m, nombre):
    return os.path.join(m.BACKUP_DIR, nombre)


def sql(db, stmt, args=()):
    c = sqlite3.connect(db)
    c.execute(stmt, args)
    c.commit()
    c.close()


class TestCrearBackup:
    def test_crea_un_archivo_con_nombre_estandar(self, crud_app):
        client, m = crud_app
        info = crear(client)
        assert info["success"] is True
        assert PATRON.fullmatch(info["filename"]), info["filename"]
        assert os.path.isfile(ruta(m, info["filename"]))
        assert "size_mb" in info

    def test_aparece_en_el_listado(self, crud_app):
        client, _ = crud_app
        nombre = crear(client)["filename"]
        r = client.get("/api/software/database/backups", headers=auth_headers())
        assert r.status_code == 200 and nombre in r.get_data(as_text=True)

    def test_borrar_exige_confirmacion_y_elimina_el_archivo(self, crud_app):
        client, m = crud_app
        nombre = crear(client)["filename"]
        url = f"/api/software/database/backups/{nombre}"
        assert client.delete(url, headers=auth_headers()).status_code == 400
        assert os.path.isfile(ruta(m, nombre))
        assert client.delete(url + "?confirm=1", headers=auth_headers()).status_code == 200
        assert not os.path.isfile(ruta(m, nombre))

    @pytest.mark.live
    def test_en_vivo_crear_descargar_validar_y_borrar(self, live, tmp_path):
        base = CFG["crud_url"]
        r = live.post(base + "/api/software/database/backup", json={}, timeout=60)
        assert r.status_code == 200, r.text[:200]
        nombre = r.json()["filename"]
        try:
            d = live.get(f"{base}/api/software/database/backups/{nombre}/download", timeout=60)
            assert d.status_code == 200
            destino = tmp_path / nombre
            destino.write_bytes(d.content)
            assert destino.read_bytes()[:15] == b"SQLite format 3"
            assert integrity_ok(str(destino))
            assert set(table_counts(str(destino))) == set(syslib.TABLES)
        finally:
            live.delete(f"{base}/api/software/database/backups/{nombre}?confirm=1", timeout=30)
        assert nombre not in live.get(base + "/api/software/database/backups", timeout=30).text


class TestValidarBackup:
    def test_cabecera_sqlite_e_integrity_check(self, crud_app):
        client, m = crud_app
        p = ruta(m, crear(client)["filename"])
        assert Path(p).read_bytes()[:15] == b"SQLite format 3"
        assert integrity_ok(p)

    def test_mismo_esquema_que_la_bd_original(self, crud_app, tmp_db):
        client, m = crud_app
        p = ruta(m, crear(client)["filename"])
        consulta = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        a = syslib.q(tmp_db).execute(consulta).fetchall()
        b = syslib.q(p).execute(consulta).fetchall()
        assert a == b

    def test_backup_valido_aun_con_escrituras_concurrentes(self, crud_app, tmp_db):
        client, m = crud_app
        parar = threading.Event()

        def escritor():
            c = sqlite3.connect(tmp_db, timeout=30)
            i = 0
            while not parar.is_set():
                c.execute("INSERT INTO registros_asistencia (uid, fecha_dia, tipo_evento) VALUES (?, '2026-01-01', 'rebote')",
                          (f"w{i}",))
                c.commit()
                i += 1
            c.close()

        t = threading.Thread(target=escritor)
        t.start()
        try:
            nombres = []
            for _ in range(4):
                nombres.append(crear(client)["filename"])
                time.sleep(1.05)  # el nombre tiene resolución de 1 s
        finally:
            parar.set()
            t.join()
        for n in nombres:
            assert integrity_ok(ruta(m, n)), f"{n} quedó inconsistente"

    @pytest.mark.live
    def test_en_vivo_existe_un_backup_reciente(self, live):
        txt = live.get(CFG["crud_url"] + "/api/software/database/backups", timeout=30).text
        marcas = sorted(PATRON.findall(txt))
        assert marcas, "no hay ningún backup listado"
        fecha, hora = marcas[-1]
        edad_h = (datetime.now() - datetime.strptime(fecha + hora, "%Y%m%d%H%M%S")).total_seconds() / 3600
        assert edad_h <= CFG["backup_max_age_h"], f"el último backup tiene {edad_h:.0f} h (umbral {CFG['backup_max_age_h']})"

    @pytest.mark.live
    def test_en_vivo_hay_una_tarea_programada_de_backup(self, live):
        """El backup automático lo dispara rfid-backup.timer; una entrada de cron también es válida."""
        rc, out, _ = syslib.sh(["crontab", "-l"])
        en_cron = rc == 0 and "run_backup.sh" in out
        timer = (syslib.sh(["systemctl", "is-enabled", "rfid-backup.timer"])[1].strip() == "enabled"
                 and syslib.sh(["systemctl", "is-active", "rfid-backup.timer"])[1].strip() == "active")
        assert en_cron or timer, "no hay backup programado: ni cron para run_backup.sh ni rfid-backup.timer activo"

    @pytest.mark.live
    def test_en_vivo_el_ultimo_backup_es_integro(self, live, tmp_path):
        base = CFG["crud_url"]
        marcas = sorted(PATRON.findall(live.get(base + "/api/software/database/backups", timeout=30).text))
        if not marcas:
            pytest.skip("sin backups")
        nombre = f"rfid_backup_{marcas[-1][0]}_{marcas[-1][1]}.db"
        d = live.get(f"{base}/api/software/database/backups/{nombre}/download", timeout=60)
        assert d.status_code == 200
        p = tmp_path / nombre
        p.write_bytes(d.content)
        assert integrity_ok(str(p)), f"{nombre} falla integrity_check"

    @pytest.mark.live
    def test_en_vivo_la_cantidad_de_backups_esta_acotada(self, live):
        n = len(set(PATRON.findall(live.get(CFG["crud_url"] + "/api/software/database/backups", timeout=30).text)))
        assert n <= CFG["max_backups"], f"{n} backups acumulados: falta política de retención"


class TestRestaurar:
    def test_revierte_los_cambios_posteriores_al_backup(self, crud_app, tmp_db):
        client, m = crud_app
        antes = table_counts(tmp_db)
        nombre = crear(client)["filename"]
        time.sleep(1.1)  # el respaldo de seguridad usa nombre con resolución de segundos
        sql(tmp_db, "INSERT INTO estudiantes (nombre, apellido_paterno, matricula) VALUES ('Nuevo','Post','POST-1')")
        sql(tmp_db, "DELETE FROM registros_asistencia")
        r = client.post("/api/software/database/restore", headers=auth_headers(),
                        json={"filename": nombre, "confirm": True})
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        data = r.get_json()
        assert data["success"] is True
        assert table_counts(tmp_db)["estudiantes"] == antes["estudiantes"]
        assert integrity_ok(tmp_db)
        # el respaldo de seguridad conserva el estado previo a la restauración
        seguridad = ruta(m, data["safety_backup"])
        assert os.path.isfile(seguridad)
        assert syslib.q(seguridad).execute(
            "SELECT COUNT(*) FROM estudiantes WHERE matricula='POST-1'").fetchone()[0] == 1

    def test_exige_confirmacion(self, crud_app, tmp_db):
        client, _ = crud_app
        nombre = crear(client)["filename"]
        r = client.post("/api/software/database/restore", headers=auth_headers(), json={"filename": nombre})
        assert r.status_code == 400

    def test_archivo_inexistente_devuelve_404(self, crud_app):
        client, _ = crud_app
        r = client.post("/api/software/database/restore", headers=auth_headers(),
                        json={"filename": "rfid_backup_19990101_000000.db", "confirm": True})
        assert r.status_code == 404

    def test_un_respaldo_danado_se_rechaza_sin_tocar_la_bd(self, crud_app, tmp_db):
        client, m = crud_app
        malo = "rfid_backup_20200101_000000.db"
        Path(ruta(m, malo)).write_bytes(b"SQLite format 3\x00" + os.urandom(4096))
        antes = table_counts(tmp_db)
        r = client.post("/api/software/database/restore", headers=auth_headers(),
                        json={"filename": malo, "confirm": True})
        assert r.status_code in (400, 422), f"restaurar un archivo dañado devolvió {r.status_code}"
        assert integrity_ok(tmp_db) and table_counts(tmp_db) == antes, "la BD viva quedó alterada"

    def test_restaurar_en_el_mismo_segundo_del_backup_no_lo_corrompe(self, crud_app, tmp_db):
        """Hallazgo esperado: el respaldo de seguridad se llama rfid_backup_<segundo>.db; si coincide con el
        archivo a restaurar, se sobrescribe antes de copiarlo y la restauración no revierte nada."""
        client, m = crud_app
        antes = table_counts(tmp_db)["estudiantes"]
        nombre = crear(client)["filename"]
        sql(tmp_db, "INSERT INTO estudiantes (nombre, apellido_paterno, matricula) VALUES ('X','Y','MISMO-SEG')")
        client.post("/api/software/database/restore", headers=auth_headers(), json={"filename": nombre, "confirm": True})
        assert table_counts(tmp_db)["estudiantes"] == antes, \
            "la restauración no revirtió: el respaldo de seguridad pisó al archivo origen (mismo segundo)"

    def test_restaurar_con_una_conexion_wal_activa(self, crud_app, tmp_db):
        """Si un servicio mantiene la BD abierta (WAL), reemplazar el archivo con os.replace puede dejar un
        -wal/-shm del archivo anterior. Tras restaurar, los datos deben ser exactamente los del backup."""
        client, m = crud_app
        antes = table_counts(tmp_db)["estudiantes"]
        nombre = crear(client)["filename"]
        time.sleep(1.1)
        activa = sqlite3.connect(tmp_db)
        activa.execute("PRAGMA journal_mode=WAL")
        activa.execute("INSERT INTO estudiantes (nombre, apellido_paterno, matricula) VALUES ('W','A','WAL-1')")
        activa.commit()  # queda en el WAL, la conexión sigue abierta
        try:
            r = client.post("/api/software/database/restore", headers=auth_headers(),
                            json={"filename": nombre, "confirm": True})
            assert r.status_code == 200
            assert integrity_ok(tmp_db), "la BD restaurada falla integrity_check"
            assert table_counts(tmp_db)["estudiantes"] == antes, \
                "tras restaurar reaparecen datos del WAL anterior (restore no limpia -wal/-shm)"
        finally:
            activa.close()


class TestVerificarIntegridad:
    def test_integrity_y_foreign_key_check_limpios(self, crud_app):
        client, m = crud_app
        p = ruta(m, crear(client)["filename"])
        assert integrity_ok(p)
        c = sqlite3.connect(p)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        c.close()

    def test_conserva_los_indices_unicos(self, crud_app):
        client, m = crud_app
        p = ruta(m, crear(client)["filename"])
        nombres = {n for (n,) in syslib.q(p).execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_tarjeta_activa_unica" in nombres

    def test_un_archivo_corrupto_se_detecta(self, tmp_path):
        p = tmp_path / "malo.db"
        p.write_bytes(b"SQLite format 3\x00" + os.urandom(4096))
        with pytest.raises(sqlite3.DatabaseError):
            integrity_ok(str(p))


class TestVerificarDatos:
    def test_el_backup_contiene_exactamente_los_mismos_datos(self, crud_app, tmp_db):
        client, m = crud_app
        sql(tmp_db, "INSERT INTO registros_asistencia (id_estudiante, uid, fecha_dia, tipo_evento, mensaje)"
                    " VALUES (1, 'u1', '2026-01-02', 'aceptado', 'ok')")
        p = ruta(m, crear(client)["filename"])
        for t in SIN_AUDITORIA:
            assert dump_table(p, t) == dump_table(tmp_db, t), f"la tabla {t} difiere entre BD y backup"

    def test_fila_concreta_presente_en_el_backup(self, crud_app):
        client, m = crud_app
        p = ruta(m, crear(client)["filename"])
        fila = syslib.q(p).execute(
            "SELECT nombre, apellido_paterno, estado FROM estudiantes WHERE matricula='2023001'").fetchone()
        assert fila == ("Juan", "Pérez", "activo")

    def test_la_auditoria_registra_la_creacion_del_backup(self, crud_app, tmp_db):
        client, _ = crud_app
        antes = table_counts(tmp_db)["audit_log"]
        crear(client)
        assert table_counts(tmp_db)["audit_log"] > antes
