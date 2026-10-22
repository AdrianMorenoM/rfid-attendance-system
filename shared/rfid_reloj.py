#!/usr/bin/env python3
"""Corrección de horas tras un arranque sin reloj sincronizado (la Pi no tiene RTC).

El lector guarda boot_id, uptime_s y reloj_confiable en cada lectura. Cuando el reloj de un
arranque pasa a ser confiable, este script:
  1. guarda un ancla (boot_id, uptime_s, hora real) para ese arranque,
  2. recalcula timestamp y fecha_dia de sus lecturas con reloj_confiable = 0:
         hora_real = hora_ancla - (uptime_ancla - uptime_lectura)
  3. conserva la hora original en timestamp_original y marca reloj_confiable = 2,
  4. vuelve a aplicar "una aceptada por alumno y día".
Es idempotente: se ejecuta cada minuto desde un timer de systemd.
"""
import os, sys, time, sqlite3
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("RFID_DB") or os.path.join(BASE, "rfid.db")
BOOT_ID_FILE = "/proc/sys/kernel/random/boot_id"
MARCAS_RELOJ_OK = tuple(os.environ.get(
    "RFID_MARCAS_RELOJ",
    "/run/systemd/timesync/synchronized:"
    "/run/rfid-shared/reloj_manual_ok",
).split(":"))
FMT = "%Y-%m-%d %H:%M:%S"
COLUMNAS = (("boot_id", "TEXT"), ("uptime_s", "REAL"),
            ("reloj_confiable", "INTEGER"), ("timestamp_original", "TEXT"))


def asegurar_esquema(conn):
    """Crea columnas y tabla de anclas si faltan (idempotente)."""
    existentes = {f[1] for f in conn.execute("PRAGMA table_info(registros_asistencia)")}
    for nombre, tipo in COLUMNAS:
        if nombre not in existentes:
            try:
                conn.execute(f"ALTER TABLE registros_asistencia ADD COLUMN {nombre} {tipo}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reloj_anclas (
            boot_id   TEXT PRIMARY KEY,
            uptime_s  REAL NOT NULL,
            hora_real TEXT NOT NULL,
            creada_en TEXT NOT NULL
        )""")
    conn.commit()


def _boot_id():
    try:
        with open(BOOT_ID_FILE) as f:
            return f.read().strip()
    except OSError:
        return None


def reloj_confiable():
    return any(os.path.exists(p) for p in MARCAS_RELOJ_OK)


_SQL_PENDIENTES = (
    "SELECT id, uid, uptime_s FROM registros_asistencia "
    "WHERE boot_id = ? AND reloj_confiable = 0 AND uptime_s IS NOT NULL ORDER BY id")


def reparar(conn, boot_id, uptime_ahora, ahora, confiable):
    """Corrige las lecturas no confiables de este arranque. Devuelve un resumen."""
    res = {"ancla_creada": False, "corregidas": 0, "reclasificadas": 0,
           "pendientes_otros_arranques": 0}
    if not confiable or not boot_id:
        return res
    asegurar_esquema(conn)
    if not conn.execute(_SQL_PENDIENTES, (boot_id,)).fetchall():
        return res  # nada que hacer: sin bloquear la base

    conn.execute("BEGIN IMMEDIATE")
    try:
        pendientes = conn.execute(_SQL_PENDIENTES, (boot_id,)).fetchall()
        res["pendientes_otros_arranques"] = conn.execute(
            "SELECT COUNT(*) FROM registros_asistencia "
            "WHERE reloj_confiable = 0 AND boot_id IS NOT NULL AND boot_id != ?",
            (boot_id,)).fetchone()[0]

        ancla = conn.execute(
            "SELECT uptime_s, hora_real FROM reloj_anclas WHERE boot_id = ?", (boot_id,)).fetchone()
        if ancla is None:
            hora = ahora.strftime(FMT)
            conn.execute(
                "INSERT INTO reloj_anclas (boot_id, uptime_s, hora_real, creada_en) VALUES (?,?,?,?)",
                (boot_id, uptime_ahora, hora, hora))
            ancla = (uptime_ahora, hora)
            res["ancla_creada"] = True
        ancla_uptime, ancla_hora = ancla[0], datetime.strptime(ancla[1], FMT)

        grupos = set()
        for rid, uid, up in pendientes:
            if up > ancla_uptime:
                continue  # posterior al ancla: no se puede situar con esta
            real = ancla_hora - timedelta(seconds=ancla_uptime - up)
            fecha = real.strftime("%Y-%m-%d")
            conn.execute(
                "UPDATE registros_asistencia SET "
                "timestamp_original = COALESCE(timestamp_original, timestamp), "
                "timestamp = ?, fecha_dia = ?, reloj_confiable = 2 WHERE id = ?",
                (real.strftime(FMT), fecha, rid))
            grupos.add((uid, fecha))
            res["corregidas"] += 1

        # Reconciliación: la primera lectura del día es 'aceptado', las demás 'ya_escaneado'
        for uid, fecha in grupos:
            filas = conn.execute(
                "SELECT id, tipo_evento, mensaje FROM registros_asistencia "
                "WHERE uid = ? AND fecha_dia = ? AND tipo_evento IN ('aceptado', 'ya_escaneado') "
                "ORDER BY timestamp, id", (uid, fecha)).fetchall()
            for k, (rid, tipo, msg) in enumerate(filas, 1):
                tipo_ok = "aceptado" if k == 1 else "ya_escaneado"
                msg_ok = "Acceso permitido" if k == 1 else f"Ya registrado ({k}ª vez hoy)"
                if tipo != tipo_ok:
                    conn.execute("UPDATE registros_asistencia SET tipo_evento = ?, mensaje = ? WHERE id = ?",
                                 (tipo_ok, msg_ok, rid))
                    res["reclasificadas"] += 1
                elif tipo == "ya_escaneado" and msg != msg_ok:
                    conn.execute("UPDATE registros_asistencia SET mensaje = ? WHERE id = ?", (msg_ok, rid))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return res


def main():
    if not reloj_confiable():
        return 0
    if not os.path.exists(DB):
        print(f"[reloj] no existe la base de datos: {DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{DB}?mode=rw", uri=True, timeout=10)
    try:
        res = reparar(conn, _boot_id(), time.clock_gettime(time.CLOCK_BOOTTIME), datetime.now(), True)
    finally:
        conn.close()
    if res["ancla_creada"] or res["corregidas"] or res["reclasificadas"]:
        print("[reloj] ancla_creada={ancla_creada} corregidas={corregidas} "
              "reclasificadas={reclasificadas} pendientes_otros_arranques={pendientes_otros_arranques}"
              .format(**res), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
