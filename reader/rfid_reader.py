#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lector RFID para Raspberry Pi 4 + RC522 (SPI)."""

import sqlite3, os, time, signal, sys, logging, fcntl, socket
from datetime import datetime

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reader.log'),
            delay=True
        )
        #logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reader.log')),
    ]
)
log = logging.getLogger('rfid-reader')

# Hardware
try:  # pragma: no cover
    from mfrc522 import MFRC522
    import RPi.GPIO as GPIO
    RFID_OK = True
    log.info("Hardware RC522 detectado")
except ImportError:  # pragma: no cover
    RFID_OK = False
    log.warning("mfrc522 / RPi.GPIO no disponibles — modo simulación")

# Configuración
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB         = os.environ.get("RFID_DB") or os.path.join(BASE_DIR, "..", "data", "rfid.db")
DEBOUNCE_S = 2
SPI_SPEED  = 1_000_000
POLL_S     = 0.15

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
    except Exception as exc:  # pragma: no cover
        log.warning(f"No se pudo escribir status file: {exc}")

# DB helper
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30.0, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        conn.close()   # con una BD corrupta o bloqueada el PRAGMA falla antes del return: no dejar la conexion abierta
        raise
    return conn

# Modo admin: verificar y notificar vía archivos
ADMIN_FLAG_MAX_AGE = 600  # s: el doble de lo que dura una sesión normal (300 s); más viejo = abandonada

def _modo_admin_activo() -> bool:
    try:
        edad = time.time() - os.path.getmtime(ADMIN_FLAG)
    except FileNotFoundError:
        return False
    if edad > ADMIN_FLAG_MAX_AGE:
        # la web se cerró sin terminar la sesión: sin esto el lector dejaría de registrar asistencia
        log.warning("Señal de modo admin abandonada (%d s): se ignora y se elimina", edad)
        try:
            os.remove(ADMIN_FLAG)
        except OSError:
            pass
        return False
    return True

def _notificar_admin_scan(uid_s: str) -> None:
    """Escribe UID en archivo de señal para el CRUD (con bloqueo exclusivo)."""
    try:
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with open(ADMIN_UID_FILE, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(f"{ts}\t{uid_s}\n")
    except Exception as exc:  # pragma: no cover
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

# ── Estado del reloj (la Pi no tiene RTC) ─────────────────────────────────
BOOT_ID_FILE = "/proc/sys/kernel/random/boot_id"
MARCAS_RELOJ_OK = tuple(os.environ.get(
    "RFID_MARCAS_RELOJ",
    "/run/systemd/timesync/synchronized:"  # lo crea systemd-timesyncd al sincronizar
    "/run/rfid-reloj/reloj_manual_ok",    # lo creará el panel al fijar la hora a mano
).split(":"))
COLUMNAS_RELOJ = (("boot_id", "TEXT"), ("uptime_s", "REAL"), ("reloj_confiable", "INTEGER"))
_boot_id_cache = None


def _boot_id() -> str:
    global _boot_id_cache
    if _boot_id_cache is None:
        try:
            with open(BOOT_ID_FILE) as f:
                _boot_id_cache = f.read().strip()
        except OSError:
            _boot_id_cache = "desconocido"
    return _boot_id_cache


def _meta_reloj() -> tuple:
    """(boot_id, segundos desde el arranque, 1 si la hora es confiable)."""
    confiable = 1 if any(os.path.exists(p) for p in MARCAS_RELOJ_OK) else 0
    return _boot_id(), round(time.clock_gettime(time.CLOCK_BOOTTIME), 3), confiable


def asegurar_columnas_reloj(conn: sqlite3.Connection) -> None:
    """Añade las columnas de reloj si faltan (idempotente)."""
    existentes = {fila[1] for fila in conn.execute("PRAGMA table_info(registros_asistencia)")}
    for nombre, tipo in COLUMNAS_RELOJ:
        if nombre not in existentes:
            try:
                conn.execute(f"ALTER TABLE registros_asistencia ADD COLUMN {nombre} {tipo}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
    conn.commit()


_SQL_REGISTRO = """
    INSERT INTO registros_asistencia
        (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje,
         boot_id, uptime_s, reloj_confiable)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _registrar(conn, id_estudiante, uid_s, ts, hoy, tipo, mensaje, meta) -> None:
    params = (id_estudiante, uid_s, ts, hoy, tipo, mensaje, *meta)
    try:
        conn.execute(_SQL_REGISTRO, params)
    except sqlite3.OperationalError as exc:
        texto = str(exc).lower()
        if "no column named" not in texto and "no such column" not in texto:
            raise
        asegurar_columnas_reloj(conn)  # BD antigua o backup restaurado: migrar y reintentar
        conn.execute(_SQL_REGISTRO, params)
    conn.commit()


# Lógica de acceso (solo modo normal)
def procesar(uid_s: str) -> tuple[str, str, str]:
    hoy = datetime.now().strftime("%Y-%m-%d")
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = _meta_reloj()
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
            _registrar(conn, None, uid_s, ts, hoy, "rebote", "UID no registrado", meta)
            return "rebote", "DESCONOCIDO", "UID no registrado"

        nombre = ((tarjeta["nombre"] or "") + " " + (tarjeta["apellido_paterno"] or "")).strip() or "Sin nombre"

        if not tarjeta["activa"] or tarjeta["estado"] != "activo":
            motivo = "Tarjeta inactiva" if not tarjeta["activa"] else "Estudiante inactivo"
            _registrar(conn, tarjeta["id_estudiante"], uid_s, ts, hoy, "rebote", motivo, meta)
            return "rebote", nombre, motivo

        if meta[2]:
            filtro, args = "fecha_dia = ?", (hoy,)
        else:  # reloj sin sincronizar: la fecha no es fiable, se agrupa por arranque
            asegurar_columnas_reloj(conn)
            filtro, args = "boot_id = ? AND reloj_confiable = 0", (meta[0],)
        c.execute(f"""
            SELECT COUNT(*) as n FROM registros_asistencia
            WHERE uid = ? AND {filtro} AND tipo_evento = 'aceptado'
        """, (uid_s, *args))
        veces = c.fetchone()["n"]

        tipo = "ya_escaneado" if veces > 0 else "aceptado"
        if veces > 0:
            # Numera el reintento contando todos los escaneos validos de hoy (aceptado + ya_escaneado)
            c.execute(f"""
                SELECT COUNT(*) as n FROM registros_asistencia
                WHERE uid = ? AND {filtro}
                  AND tipo_evento IN ('aceptado', 'ya_escaneado')
            """, (uid_s, *args))
            msg = f"Ya registrado ({c.fetchone()['n'] + 1}ª vez hoy)"
        else:
            msg = "Acceso permitido"

        _registrar(conn, tarjeta["id_estudiante"], uid_s, ts, hoy, tipo, msg, meta)
        return tipo, nombre, msg
    finally:
        conn.close()

# Signal handler
HB_S = 5
HB_REINIT = 3    # fallos seguidos (15 s): recrear el lector
HB_SALIR  = 12   # fallos seguidos (60 s): salir y que systemd lo relance
_hb_fallos = 0

def _sd_notify(msg: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr[0] == "@":
        addr = "\0" + addr[1:]
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        s.connect(addr)
        s.sendall(msg.encode())
    except OSError:
        pass
    finally:
        s.close()

TXCONTROL = 0x14

def rc522_vivo(reader) -> bool:
    try:
        v = reader.Read_MFRC522(0x37)      # VersionReg
        if v in (0x00, 0xFF):              # bus desconectado
            return False
        tx = reader.Read_MFRC522(TXCONTROL)
        if (tx & 0x03) != 0x03:            # antena apagada: el chip perdió su configuración
            log.warning("RC522: antena apagada (TxControlReg=0x%02X), reinicializando chip", tx)
            reader.MFRC522_Init()
            tx = reader.Read_MFRC522(TXCONTROL)
            if (tx & 0x03) != 0x03:
                log.error("RC522: sigue sin antena tras reinicializar (0x%02X)", tx)
                return False
        return True
    except Exception:
        return False

def _heartbeat(reader, ultimo: float) -> float:
    global _hb_fallos
    ahora = time.time()
    if ahora - ultimo < HB_S:
        return ultimo
    if rc522_vivo(reader):
        _hb_fallos = 0
        _escribir_estado("ok")
        _sd_notify("WATCHDOG=1")
    else:
        _hb_fallos += 1
        _escribir_estado("error")
        if _hb_fallos == 1 or _hb_fallos % 12 == 0:
            log.error("RC522 no responde (VersionReg 0x00/0xFF): revisa el cableado SPI")
    return ahora

def cleanup(sig=None, _frame=None):
    log.info("Cerrando lector RFID…")
    for f in (ADMIN_FLAG, ADMIN_UID_FILE, STATUS_FILE):
        try: os.remove(f)
        except FileNotFoundError: pass
    if RFID_OK:
        try: GPIO.cleanup()  # pragma: no cover
        except Exception: pass  # pragma: no cover
    sys.exit(0)

# Main loop
def main():  # pragma: no cover
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
    ultimo_hb  = 0.0
    try:
        log.info("RC522 VersionReg=0x%02X", reader.Read_MFRC522(0x37))
    except Exception:
        log.warning("No se pudo leer VersionReg")
    _escribir_estado("ok")
    log.info("Listo — acerca una tarjeta...")

    while True:
        try:
            fallos_antes = _hb_fallos
            ultimo_hb = _heartbeat(reader, ultimo_hb)
            if _hb_fallos != fallos_antes:   # el heartbeat acaba de correr
                if _hb_fallos == 0:
                    log.warning("RC522 recuperado tras %d fallos seguidos", fallos_antes)
                elif _hb_fallos == HB_REINIT:
                    log.warning("RC522: %d fallos seguidos, reinicializando", _hb_fallos)
                    try: reader.spi.close()
                    except Exception: pass
                    reader = MFRC522()
                elif _hb_fallos >= HB_SALIR:
                    log.critical("RC522 sin respuesta %d veces seguidas: saliendo para que systemd relance", _hb_fallos)
                    cleanup()
            uid_s = leer_uid(reader)
            if uid_s is None:
                time.sleep(POLL_S)
                continue

            ahora = time.time()
            if uid_s == ultimo_uid and (ahora - ultimo_t) < DEBOUNCE_S:
                ultimo_t = ahora  # tarjeta aun presente: renueva la ventana
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

if __name__ == "__main__":  # pragma: no cover
    main()
