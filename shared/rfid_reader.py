#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lector RFID para Raspberry Pi 4 + RC522 (SPI)."""

import sqlite3, os, time, signal, sys, logging, fcntl
from datetime import datetime

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reader.log')),
    ]
)
log = logging.getLogger('rfid-reader')

# Hardware
try:
    from mfrc522 import MFRC522
    import RPi.GPIO as GPIO
    RFID_OK = True
    log.info("Hardware RC522 detectado")
except ImportError:
    RFID_OK = False
    log.warning("mfrc522 / RPi.GPIO no disponibles — modo simulación")

# Configuración
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB         = os.path.join(BASE_DIR, "rfid.db")
DEBOUNCE_S = 2
SPI_SPEED  = 1_000_000
POLL_S     = 0.15
REINIT_TIMEOUT = 8  # segundos sin ninguna lectura antes de reiniciar el chip

# Archivos de señal para modo admin
ADMIN_FLAG     = "/run/rfid-shared/rfid_admin_mode"
ADMIN_UID_FILE = "/run/rfid-shared/rfid_admin_uid"

# Archivo de estado del lector (para que el dashboard lo pueda leer)
STATUS_FILE = "/run/rfid-shared/rfid_reader_status"

def _escribir_estado(estado: str) -> None:
    """Escribe el estado actual del lector para que el dashboard lo muestre."""
    try:
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w") as f:
            f.write(f"{estado}\t{datetime.now().isoformat()}\n")
    except Exception as exc:
        log.warning(f"No se pudo escribir status file: {exc}")

# DB helper
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

# Modo admin: verificar y notificar vía archivos
def _modo_admin_activo() -> bool:
    return os.path.exists(ADMIN_FLAG)

def _notificar_admin_scan(uid_s: str) -> None:
    """Escribe UID en archivo de señal para el CRUD (con bloqueo exclusivo)."""
    try:
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with open(ADMIN_UID_FILE, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(f"{ts}\t{uid_s}\n")
    except Exception as exc:
        log.warning(f"No se pudo escribir admin uid file: {exc}")

# Lectura de UID (Request + Anticollision, sin autenticar)
def leer_uid(reader) -> str | None:
    status, _ = reader.MFRC522_Request(reader.PICC_REQIDL)
    if status != reader.MI_OK:
        return None
    status, uid_bytes = reader.MFRC522_Anticoll()
    if status != reader.MI_OK or not uid_bytes:
        return None
    uid_int = 0
    for b in uid_bytes[:4]:
        uid_int = (uid_int << 8) | b
    return str(uid_int)

# Lógica de acceso (solo modo normal)
def procesar(uid_s: str) -> tuple[str, str, str]:
    hoy = datetime.now().strftime("%Y-%m-%d")
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT t.activa, t.id_estudiante,
                   e.nombre, e.apellido_paterno, e.estado
            FROM tarjetas t
            LEFT JOIN estudiantes e ON t.id_estudiante = e.id
            WHERE t.uid = ?
        """, (uid_s,))
        tarjeta = c.fetchone()

        if tarjeta is None:
            c.execute("""
                INSERT INTO registros_asistencia
                    (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje)
                VALUES (NULL, ?, ?, ?, 'rebote', 'UID no registrado')
            """, (uid_s, ts, hoy))
            conn.commit()
            return "rebote", "DESCONOCIDO", "UID no registrado"

        nombre = ((tarjeta["nombre"] or "") + " " + (tarjeta["apellido_paterno"] or "")).strip() or "Sin nombre"

        if not tarjeta["activa"] or tarjeta["estado"] != "activo":
            motivo = "Tarjeta inactiva" if not tarjeta["activa"] else "Estudiante inactivo"
            c.execute("""
                INSERT INTO registros_asistencia
                    (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje)
                VALUES (?, ?, ?, ?, 'rebote', ?)
            """, (tarjeta["id_estudiante"], uid_s, ts, hoy, motivo))
            conn.commit()
            return "rebote", nombre, motivo

        c.execute("""
            SELECT COUNT(*) as n FROM registros_asistencia
            WHERE uid = ? AND fecha_dia = ? AND tipo_evento = 'aceptado'
        """, (uid_s, hoy))
        veces = c.fetchone()["n"]

        tipo = "ya_escaneado" if veces > 0 else "aceptado"
        msg  = f"Ya registrado ({veces + 1}ª vez hoy)" if veces > 0 else "Acceso permitido"

        c.execute("""
            INSERT INTO registros_asistencia
                (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tarjeta["id_estudiante"], uid_s, ts, hoy, tipo, msg))
        conn.commit()
        return tipo, nombre, msg
    finally:
        conn.close()

# Signal handler
def cleanup(sig=None, _frame=None):
    log.info("Cerrando lector RFID…")
    for f in (ADMIN_FLAG, ADMIN_UID_FILE, STATUS_FILE):
        try: os.remove(f)
        except FileNotFoundError: pass
    if RFID_OK:
        try: GPIO.cleanup()
        except Exception: pass
    sys.exit(0)

# Main loop
def main():
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT,  cleanup)

    log.info("=== Lector RFID iniciado ===")
    log.info(f"DB: {DB}")
    log.info(f"Archivo señal admin: {ADMIN_FLAG}")

    if not RFID_OK:
        log.warning("Sin hardware RFID — proceso en espera (simulación).")
        while True:
            time.sleep(60)

    reader = MFRC522()
    ultimo_uid = None
    ultimo_t   = 0.0
    ultima_lectura_ok = time.time()
    reinicios = 0

    _escribir_estado("ok")
    log.info("Listo — acerca una tarjeta...")

    while True:
        try:
            uid_s = leer_uid(reader)
            if uid_s is None:
                if time.time() - ultima_lectura_ok > REINIT_TIMEOUT:
                    reinicios += 1
                    log.warning(f"Sin actividad del lector ({REINIT_TIMEOUT}s), "
                                f"reinicializando RC522… (reinicio #{reinicios})")
                    _escribir_estado("reiniciando")
                    reader.MFRC522_Init()
                    ultima_lectura_ok = time.time()
                    _escribir_estado("ok")
                time.sleep(POLL_S)
                continue

            ultima_lectura_ok = time.time()

            ahora = time.time()
            if uid_s == ultimo_uid and (ahora - ultimo_t) < DEBOUNCE_S:
                time.sleep(POLL_S)
                continue

            ultimo_uid = uid_s
            ultimo_t   = ahora

            if _modo_admin_activo():
                _notificar_admin_scan(uid_s)
                log.info(f"\033[94m[ADMIN-SCAN   ]\033[0m  UID: {uid_s}  → capturado (sin registro)")
                time.sleep(POLL_S)
                continue

            tipo, nombre, msg = procesar(uid_s)
            colores = {"aceptado": "\033[92m", "ya_escaneado": "\033[93m", "rebote": "\033[91m"}
            reset = "\033[0m"
            c = colores.get(tipo, "")
            log.info(f"{c}[{tipo.upper():13s}]{reset}  {nombre:<30s}  UID: {uid_s}")

        except Exception as exc:
            log.error(f"Error en loop: {exc}", exc_info=True)
            _escribir_estado("error")
            time.sleep(1)

if __name__ == "__main__":
    main()
