#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRUD Service — Puerto 5001
Sistema de Asistencia RFID — ITSOEH / ITIC's
"""
import sqlite3, os, csv, io, traceback, logging, threading, time, json, sys, ipaddress
import subprocess, shutil, hmac, fcntl
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, jsonify, request, Response, stream_with_context, abort
from werkzeug.utils import secure_filename
from PIL import Image

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from limits import parse as _parse_rate_limit
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

# Carga .env (solo desarrollo)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger('crud')

# ===== Autenticación básica =====
def _get_required_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        log.error("Variable obligatoria '%s' no definida.", var_name)
        sys.exit(f"ERROR: falta '{var_name}'.")
    return value

BASIC_AUTH_USER     = _get_required_env('ADMIN_USER')
BASIC_AUTH_PASSWORD = _get_required_env('ADMIN_PASSWORD')

def _check_credentials(username, password):
    try:
        user_ok = hmac.compare_digest((username or "").encode(), BASIC_AUTH_USER.encode())
        pass_ok = hmac.compare_digest((password or "").encode(), BASIC_AUTH_PASSWORD.encode())
    except (TypeError, UnicodeEncodeError):
        return False
    return user_ok and pass_ok

def _auth_required_response():
    return Response('Autenticación requerida.', 401,
                    {'WWW-Authenticate': 'Basic realm="RFID Admin"'})

def require_basic_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_credentials(auth.username, auth.password):
            return _auth_required_response()
        return f(*args, **kwargs)
    return wrapper

# ===== Allowlist de IP =====
ALLOWED_SUBNET = os.environ.get('ALLOWED_SUBNET', '').strip()

def _parse_allowed_networks(raw: str):
    if not raw or raw.lower() == 'disabled':
        return None
    networks = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError as e:
            log.error("ALLOWED_SUBNET inválido (%r): %s", part, e)
            sys.exit(f"ERROR: ALLOWED_SUBNET inválido: {part!r}")
    return networks or None

_ALLOWED_NETWORKS = _parse_allowed_networks(ALLOWED_SUBNET)

@app.before_request
def _enforce_ip_allowlist():
    if _ALLOWED_NETWORKS is None:
        return
    remote = request.remote_addr
    try:
        ip = ipaddress.ip_address(remote)
    except (TypeError, ValueError):
        return Response('Acceso denegado.', 403)
    if not any(ip in net for net in _ALLOWED_NETWORKS):
        return Response('Acceso denegado.', 403)

# ===== Rate limiting =====
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="memory://",
    default_limits=["60 per minute"],
    headers_enabled=True,
    swallow_errors=True,
)

@limiter.request_filter
def _exempt_authenticated_admin_from_global_limit():
    auth = request.authorization
    return bool(auth and _check_credentials(auth.username, auth.password))

@app.errorhandler(429)
def _rate_limit_exceeded(e):
    return jsonify({
        'success': False,
        'error': 'Demasiadas solicitudes. Intenta de nuevo en unos momentos.',
    }), 429

# Límite estricto de intentos fallidos de auth
_AUTH_FAIL_STORAGE      = MemoryStorage()
_AUTH_FAIL_RATE_LIMITER = FixedWindowRateLimiter(_AUTH_FAIL_STORAGE)
_AUTH_FAIL_SHORT_LIMIT  = _parse_rate_limit("5/minute")
_AUTH_FAIL_LONG_LIMIT   = _parse_rate_limit("20/15minutes")

def _auth_rate_limited(ip: str) -> bool:
    return not (
        _AUTH_FAIL_RATE_LIMITER.test(_AUTH_FAIL_SHORT_LIMIT, f"authfail-short:{ip}")
        and _AUTH_FAIL_RATE_LIMITER.test(_AUTH_FAIL_LONG_LIMIT, f"authfail-long:{ip}")
    )

def _register_auth_failure(ip: str) -> None:
    _AUTH_FAIL_RATE_LIMITER.hit(_AUTH_FAIL_SHORT_LIMIT, f"authfail-short:{ip}")
    _AUTH_FAIL_RATE_LIMITER.hit(_AUTH_FAIL_LONG_LIMIT, f"authfail-long:{ip}")

@app.before_request
def _enforce_basic_auth():
    ip = get_remote_address()
    if _auth_rate_limited(ip):
        _registrar_auditoria(
            'auth_rate_limited',
            f'IP {ip} bloqueada por exceso de intentos fallidos',
            'error',
            ip=ip,
        )
        return jsonify({
            'success': False,
            'error': 'Demasiados intentos fallidos. Intenta más tarde.',
        }), 429
    auth = request.authorization
    if not auth or not _check_credentials(auth.username, auth.password):
        _register_auth_failure(ip)
        return _auth_required_response()

# ===== Headers de seguridad =====
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

@app.after_request
def _set_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = CSP_POLICY
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    return response

# ===== CSRF defensa en rutas destructivas =====
_XHR_HEADER_NAME  = 'X-Requested-With'
_XHR_HEADER_VALUE = 'XMLHttpRequest'

def require_xhr_header(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.headers.get(_XHR_HEADER_NAME) != _XHR_HEADER_VALUE:
            return jsonify({'success': False, 'error': 'Falta encabezado requerido.'}), 403
        return f(*args, **kwargs)
    return wrapper

# ===== Rutas y directorios =====
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB         = os.path.join(BASE_DIR, "..", "shared", "rfid.db")
BACKUP_DIR = os.path.join(BASE_DIR, "..", "shared", "backups")
FOTOS      = os.path.join(BASE_DIR, "static", "fotos")
os.makedirs(FOTOS,      exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

def _eliminar_foto_disco(foto_url: str | None) -> None:
    if not foto_url:
        return
    try:
        nombre_archivo = os.path.basename(foto_url)
        if not nombre_archivo:
            return
        ruta = os.path.join(FOTOS, nombre_archivo)
        os.remove(ruta)
    except (FileNotFoundError, PermissionError):
        pass
    except Exception:
        log.exception(f"Error eliminando foto: {foto_url}")

CARRERA = "ITIC's"
RFID_SERVICES = ('rfid-crud.service', 'rfid-dashboard.service', 'rfid-reader.service')

_rfid_listen_state = {'active': False, 'uid': None, 'timestamp': None, 'expires': None}
_rfid_listen_lock  = threading.Lock()

ADMIN_FLAG     = "/run/rfid-shared/rfid_admin_mode"
ADMIN_UID_FILE = "/run/rfid-shared/rfid_admin_uid"
_admin_scan_state = {'active': False, 'uids': [], 'expires': None, 'ultimo_uid_ts': None}
_admin_scan_lock  = threading.Lock()

# ===== DB helpers =====
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

_schema_cache: dict = {}

def schema(conn) -> dict:
    if _schema_cache:
        return _schema_cache
    cols = {r[1] for r in conn.execute("PRAGMA table_info(registros_asistencia)").fetchall()}
    _schema_cache['col'] = ('tipo_evento' if 'tipo_evento' in cols
                            else 'estado' if 'estado' in cols else 'tipo_evento')
    _schema_cache['ff']  = ("fecha_dia = ?" if 'fecha_dia' in cols
                            else "strftime('%Y-%m-%d', timestamp) = ?")
    return _schema_cache

def api(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except sqlite3.IntegrityError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            log.exception(f"Error en {f.__name__}")
            return jsonify({'success': False, 'error': 'Error interno'}), 500
    return wrapper

# ===== Auditoría =====
def _registrar_auditoria(accion: str, detalle: str, resultado: str, ip: str | None = None) -> None:
    conn = None
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_log (timestamp, ip, accion, detalle, resultado) VALUES (?,?,?,?,?)",
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ip or get_remote_address(), accion, detalle, resultado),
        )
        conn.commit()
    except Exception:
        log.exception(f"Error registrando auditoría (accion={accion!r})")
    finally:
        if conn is not None:
            conn.close()

# ===== System helpers =====
def _run(cmd: list[str], timeout: int = 15) -> dict:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            'success':    res.returncode == 0,
            'returncode': res.returncode,
            'stdout':     (res.stdout or '').strip(),
            'stderr':     (res.stderr or '').strip(),
        }
    except FileNotFoundError:
        return {'success': False, 'error': f'Comando no encontrado: {cmd[0]}'}
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': f'Timeout ({timeout}s)'}
    except Exception as exc:
        return {'success': False, 'error': str(exc)}

def _systemctl(action: str, service: str) -> dict:
    result = _run(['systemctl', action, service])
    if not result.get('success'):
        sudo = _run(['sudo', '-n', 'systemctl', action, service])
        if sudo.get('success') or sudo.get('returncode') == 0:
            return sudo
        if action in ('enable', 'disable'):
            err = (sudo.get('stderr') or '').lower()
            if 'created symlink' in err or 'removed' in err:
                sudo['success'] = True
                return sudo
    return result

def _wifi_iface() -> str | None:
    r = _run(['nmcli', '-t', '-f', 'DEVICE,TYPE', 'dev', 'status'])
    if r.get('stdout'):
        for line in r['stdout'].splitlines():
            parts = line.split(':')
            if len(parts) >= 2 and parts[1] == 'wifi':
                return parts[0]
    return None

def _cpu_pct() -> float | None:
    try:
        def read():
            with open('/proc/stat') as f:
                p = f.readline().split()[1:]
            n = [int(x) for x in p]
            idle = n[3] + (n[4] if len(n) > 4 else 0)
            return sum(n), idle
        t1, i1 = read()
        time.sleep(0.08)
        t2, i2 = read()
        dt, di = t2 - t1, i2 - i1
        return round(100 * (1 - di / dt), 1) if dt > 0 else None
    except Exception:
        return None

def _mem_stats() -> dict:
    try:
        mem = {}
        with open('/proc/meminfo') as f:
            for line in f:
                if ':' not in line:
                    continue
                k, v = line.split(':', 1)
                mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get('MemTotal', 0)
        avail = mem.get('MemAvailable', mem.get('MemFree', 0))
        used  = max(total - avail, 0)
        if not total:
            return {'ram_total_mb': None, 'ram_used_mb': None, 'ram_pct': None}
        return {
            'ram_total_mb': round(total / 1024, 1),
            'ram_used_mb':  round(used  / 1024, 1),
            'ram_pct':      round(100 * used / total, 1),
        }
    except Exception:
        return {'ram_total_mb': None, 'ram_used_mb': None, 'ram_pct': None}

def _disk_stats() -> dict:
    try:
        u = shutil.disk_usage('/')
        return {
            'disk_total_gb': round(u.total / 1e9, 2),
            'disk_used_gb':  round(u.used  / 1e9, 2),
            'disk_pct':      round(100 * u.used / u.total, 1) if u.total else None,
        }
    except Exception:
        return {'disk_total_gb': None, 'disk_used_gb': None, 'disk_pct': None}

def _network_status() -> dict:
    status = {
        'available': [],
        'connected': None,
        'interface': None,
        'ip':        None,
        'gateway':   None,
        'dns':       [],
        'internet':  False,
    }
    wifi = _run(['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list'])
    if wifi.get('stdout'):
        seen: set[str] = set()
        for line in wifi['stdout'].splitlines():
            if not line:
                continue
            parts = line.split(':')
            if len(parts) < 2:
                continue
            active = parts[0] == 'yes'
            ssid   = parts[1] or ''
            signal = parts[2] if len(parts) > 2 else '0'
            if not ssid or (ssid in seen and not active):
                continue
            seen.add(ssid)
            status['available'].append({'active': active, 'ssid': ssid, 'signal': signal})
            if active:
                status['connected'] = ssid
    iface = _wifi_iface()
    if iface:
        status['interface'] = iface
        ip_r = _run(['nmcli', '-t', '-f', 'IP4.ADDRESS', 'dev', 'show', iface])
        if ip_r.get('stdout'):
            raw = ip_r['stdout'].splitlines()[0].split('/')[-2] if '/' in ip_r['stdout'] else ''
            if ':' in raw:
                raw = raw.split(':', 1)[1]
            status['ip'] = raw.strip() or None
    if not status['ip']:
        r = _run(['hostname', '-I'])
        if r.get('stdout'):
            ips = r['stdout'].strip().split()
            status['ip'] = ips[0] if ips else None
    gw = _run(['ip', 'route', 'show', 'default'])
    if gw.get('stdout'):
        parts = gw['stdout'].split()
        if 'via' in parts:
            status['gateway'] = parts[parts.index('via') + 1]
    dns_r = _run(['nmcli', '-t', '-f', 'IP4.DNS', 'dev', 'show'])
    if dns_r.get('stdout'):
        status['dns'] = [x.strip() for x in dns_r['stdout'].splitlines() if x.strip()]
    if not status['dns']:
        try:
            with open('/etc/resolv.conf') as f:
                status['dns'] = [ln.split()[1] for ln in f if ln.startswith('nameserver')]
        except Exception:
            pass
    ping = _run(['ping', '-c', '1', '-W', '2', '8.8.8.8'], timeout=5)
    status['internet'] = ping.get('success', False)
    return status

# ===== Páginas =====
@app.route('/')
def index():
    return render_template('crud_dashboard.html')

# ===== Estadísticas =====
@app.route('/api/estadisticas')
@api
def estadisticas():
    conn = get_db()
    try:
        s    = schema(conn)
        hoy  = datetime.now().strftime('%Y-%m-%d')
        def cnt(vals):
            ph = ','.join('?' * len(vals))
            return conn.execute(
                f"SELECT COUNT(*) AS t FROM registros_asistencia "
                f"WHERE {s['ff']} AND {s['col']} IN ({ph})", (hoy,) + vals
            ).fetchone()['t']
        data = {
            'total_estudiantes':   conn.execute("SELECT COUNT(*) AS t FROM estudiantes WHERE carrera=?", (CARRERA,)).fetchone()['t'],
            'estudiantes_activos': conn.execute("SELECT COUNT(*) AS t FROM estudiantes WHERE estado='activo' AND carrera=?", (CARRERA,)).fetchone()['t'],
            'total_tarjetas':      conn.execute("SELECT COUNT(*) AS t FROM tarjetas").fetchone()['t'],
            'tarjetas_activas':    conn.execute("SELECT COUNT(*) AS t FROM tarjetas WHERE activa=1").fetchone()['t'],
            'registros_hoy':       conn.execute(f"SELECT COUNT(*) AS t FROM registros_asistencia WHERE {s['ff']}", (hoy,)).fetchone()['t'],
            'total_registros':     conn.execute("SELECT COUNT(*) AS t FROM registros_asistencia").fetchone()['t'],
            'aceptados_hoy':       cnt(('aceptado', 'entrada')),
        }
    finally:
        conn.close()
    return jsonify({'success': True, 'stats': data})

# ===== Analítica =====
@app.route('/api/analytics')
@api
def analytics():
    conn = get_db()
    try:
        s    = schema(conn)
        col  = s['col']
        ff   = s['ff']
        hoy  = datetime.now().strftime('%Y-%m-%d')
        dias = []
        for i in range(6, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            t = conn.execute(
                f"SELECT COUNT(*) AS t FROM registros_asistencia ra "
                f"JOIN estudiantes e ON ra.id_estudiante=e.id "
                f"WHERE {ff} AND ra.{col} IN ('aceptado','entrada') AND e.carrera=?",
                (d, CARRERA)
            ).fetchone()['t']
            dias.append({'fecha': d, 'total': t})
        mes_inicio = datetime.now().strftime('%Y-%m-01')
        mes_total  = conn.execute(
            f"SELECT COUNT(*) AS t FROM registros_asistencia ra "
            f"JOIN estudiantes e ON ra.id_estudiante=e.id "
            f"WHERE fecha_dia >= ? AND ra.{col} IN ('aceptado','entrada') AND e.carrera=?",
            (mes_inicio, CARRERA)
        ).fetchone()['t']
        por_semestre_rows = conn.execute(
            "SELECT semestre, COUNT(*) AS alumnos FROM estudiantes "
            "WHERE estado='activo' AND carrera=? GROUP BY semestre ORDER BY CAST(semestre AS INTEGER)",
            (CARRERA,)
        ).fetchall()
        por_semestre = []
        for r in por_semestre_rows:
            sem = r['semestre']
            asis = conn.execute(
                f"SELECT COUNT(*) AS t FROM registros_asistencia ra "
                f"JOIN estudiantes e ON ra.id_estudiante=e.id "
                f"WHERE fecha_dia >= ? AND ra.{col} IN ('aceptado','entrada') AND e.carrera=? AND e.semestre=?",
                (mes_inicio, CARRERA, sem)
            ).fetchone()['t']
            por_semestre.append({'semestre': sem, 'alumnos': r['alumnos'], 'asistencias_mes': asis})
        por_hora = []
        for h in range(24):
            ac = conn.execute(
                f"SELECT COUNT(*) AS t FROM registros_asistencia ra "
                f"JOIN estudiantes e ON ra.id_estudiante=e.id "
                f"WHERE {ff} AND CAST(strftime('%H',ra.timestamp) AS INTEGER)=? "
                f"AND ra.{col} IN ('aceptado','entrada') AND e.carrera=?",
                (hoy, h, CARRERA)
            ).fetchone()['t']
            tot = conn.execute(
                f"SELECT COUNT(*) AS t FROM registros_asistencia ra "
                f"JOIN estudiantes e ON ra.id_estudiante=e.id "
                f"WHERE {ff} AND CAST(strftime('%H',ra.timestamp) AS INTEGER)=? AND e.carrera=?",
                (hoy, h, CARRERA)
            ).fetchone()['t']
            por_hora.append({'hora': h, 'aceptados': ac, 'total': tot})
        top = [dict(r) for r in conn.execute(
            f"SELECT e.nombre||' '||COALESCE(e.apellido_paterno,'') AS nombre, "
            f"e.matricula, e.semestre, e.grupo, COUNT(ra.id) AS visitas "
            f"FROM estudiantes e JOIN registros_asistencia ra ON ra.id_estudiante=e.id "
            f"WHERE ra.{col} IN ('aceptado','entrada') AND e.carrera=? "
            f"GROUP BY e.id ORDER BY visitas DESC LIMIT 10",
            (CARRERA,)
        ).fetchall()]
    finally:
        conn.close()
    return jsonify({'success': True, 'analytics': {
        'asistencia_7dias': dias,
        'mes_total':        mes_total,
        'por_semestre':     por_semestre,
        'por_hora':         por_hora,
        'top_estudiantes':  top,
    }})

# ===== Hardware status =====
@app.route('/api/hardware/status')
@api
def hardware_status():
    resultado = {
        'cpu_temp':    None,
        'cpu_temp_ok': None,
        'cpu_usage':   None,
        'rfid_status': 'desconocido',
        'rfid_ok':     False,
        'db_size_mb':  None,
        'db_records':  None,
        'uptime_s':    None,
        'timestamp':   datetime.now().isoformat(),
    }
    resultado.update(_mem_stats())
    resultado.update(_disk_stats())
    resultado['cpu_usage'] = _cpu_pct()
    try:
        thermal = '/sys/class/thermal/thermal_zone0/temp'
        if os.path.exists(thermal):
            with open(thermal) as f:
                resultado['cpu_temp'] = round(int(f.read().strip()) / 1000, 1)
            resultado['cpu_temp_ok'] = resultado['cpu_temp'] < 75
        else:
            r = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                resultado['cpu_temp'] = float(r.stdout.strip().split('=')[1].replace("'C", ''))
                resultado['cpu_temp_ok'] = resultado['cpu_temp'] < 75
    except Exception:
        pass
    try:
        with open('/proc/uptime') as f:
            resultado['uptime_s'] = int(float(f.read().split()[0]))
    except Exception:
        pass
    try:
        spi = [d for d in os.listdir('/dev') if d.startswith('spidev')]
        if spi:
            resultado['rfid_status'] = 'conectado'
            resultado['rfid_ok']     = True
        else:
            try:
                import mfrc522
                resultado['rfid_status'] = 'módulo_ok'
                resultado['rfid_ok']     = True
            except ImportError:
                resultado['rfid_status'] = 'spi_no_detectado'
                resultado['rfid_ok']     = False
    except Exception:
        resultado['rfid_status'] = 'error_check'
    try:
        if os.path.exists(DB):
            resultado['db_size_mb'] = round(os.path.getsize(DB) / (1024 * 1024), 2)
        conn = get_db()
        try:
            resultado['db_records'] = conn.execute("SELECT COUNT(*) AS t FROM registros_asistencia").fetchone()['t']
        finally:
            conn.close()
    except Exception:
        pass
    return jsonify({'success': True, 'hardware': resultado})

# ===== Servicios systemd =====
def _obtener_estado_servicios():
    items = []
    for svc in RFID_SERVICES:
        active  = _run(['systemctl', 'is-active',  svc])
        enabled = _run(['systemctl', 'is-enabled', svc])
        items.append({
            'name':         svc,
            'active':       active.get('stdout', '').strip() == 'active',
            'enabled':      enabled.get('stdout', '').strip() in ('enabled', 'static'),
            'active_text':  active.get('stdout', '').strip()  or 'unknown',
            'enabled_text': enabled.get('stdout', '').strip() or 'unknown',
        })
    return items

@app.route('/api/hardware/services')
@api
def hardware_services():
    return jsonify({'success': True, 'services': _obtener_estado_servicios()})

@app.route('/api/hardware/services/<service_name>/<action>', methods=['POST'])
@api
def hardware_service_action(service_name, action):
    if service_name not in RFID_SERVICES:
        return jsonify({'success': False, 'error': 'Servicio no permitido'}), 403
    if action not in {'start', 'stop', 'restart', 'enable', 'disable', 'status'}:
        return jsonify({'success': False, 'error': 'Acción no permitida'}), 400
    result = _systemctl(action, service_name)
    active_r  = _run(['systemctl', 'is-active',  service_name])
    enabled_r = _run(['systemctl', 'is-enabled', service_name])
    ok = result.get('success', False)
    if not ok and result.get('stderr'):
        err_low = result['stderr'].lower()
        if any(k in err_low for k in ('password', 'permission', 'access denied', 'interactive')):
            return jsonify({
                'success': False,
                'error': 'Permiso denegado. Configura sudo NOPASSWD.',
                'result': result,
            }), 403
    return jsonify({
        'success':      ok,
        'service':      service_name,
        'action':       action,
        'active':       active_r.get('stdout', '').strip() == 'active',
        'enabled':      enabled_r.get('stdout', '').strip() in ('enabled', 'static'),
        'active_text':  active_r.get('stdout', '').strip()  or 'unknown',
        'enabled_text': enabled_r.get('stdout', '').strip() or 'unknown',
        'result':       result,
    })

@app.route('/api/hardware/services/<service_name>/logs')
@api
def hardware_service_logs(service_name):
    if service_name not in RFID_SERVICES:
        return jsonify({'success': False, 'error': 'Servicio no permitido'}), 403
    lines = min(request.args.get('lines', 50, type=int), 500)
    result = _run(['journalctl', '-u', service_name, f'-n{lines}', '--no-pager', '--output=short'])
    return jsonify({
        'success': True,
        'service': service_name,
        'log':     result.get('stdout') or result.get('stderr') or '(sin salida)',
        'lines':   lines,
    })

# ===== Red Wi-Fi =====
@app.route('/api/hardware/network/status')
@api
def hardware_network_status():
    return jsonify({'success': True, 'network': _network_status()})

@app.route('/api/hardware/network/scan', methods=['POST'])
@api
def hardware_network_scan():
    iface = _wifi_iface()
    cmd = ['nmcli', 'dev', 'wifi', 'rescan']
    if iface:
        cmd += ['ifname', iface]
    _run(cmd, timeout=20)
    time.sleep(1.5)
    return jsonify({'success': True, 'network': _network_status()})

@app.route('/api/hardware/network/connect', methods=['POST'])
@api
def hardware_network_connect():
    data     = request.get_json(force=True, silent=True) or {}
    ssid     = (data.get('ssid') or '').strip()
    password = (data.get('password') or '').strip()
    if not ssid:
        return jsonify({'success': False, 'error': 'SSID requerido'}), 400
    existentes = _run(['nmcli', '-t', '-f', 'NAME', 'connection', 'show'], timeout=10)
    nombres = (existentes.get('stdout') or '').splitlines()
    if ssid in nombres:
        if password:
            _run(['nmcli', 'connection', 'modify', ssid, 'wifi-sec.key-mgmt', 'wpa-psk',
                  'wifi-sec.psk', password], timeout=10)
        result = _run(['nmcli', 'connection', 'up', ssid], timeout=30)
    else:
        if password:
            result = _run(['nmcli', 'dev', 'wifi', 'connect', ssid, 'password', password], timeout=30)
        else:
            result = _run(['nmcli', 'dev', 'wifi', 'connect', ssid], timeout=30)
    if not result.get('success'):
        err = result.get('stderr') or result.get('error') or 'No se pudo conectar'
        return jsonify({'success': False, 'error': err, 'result': result}), 400
    time.sleep(1)
    return jsonify({'success': True, 'result': result, 'network': _network_status()})

@app.route('/api/hardware/network/disconnect', methods=['POST'])
@api
def hardware_network_disconnect():
    iface = _wifi_iface()
    if not iface:
        return jsonify({'success': False, 'error': 'No se encontró interfaz Wi-Fi'}), 404
    result = _run(['nmcli', 'dev', 'disconnect', iface], timeout=15)
    if not result.get('success'):
        err = result.get('stderr') or result.get('error') or 'No se pudo desconectar'
        return jsonify({'success': False, 'error': err, 'result': result}), 400
    return jsonify({'success': True, 'result': result, 'network': _network_status()})

@app.route('/api/hardware/network/restart', methods=['POST'])
@api
def hardware_network_restart():
    result = _systemctl('restart', 'NetworkManager.service')
    if not result.get('success'):
        err = result.get('stderr') or result.get('error') or 'No se pudo reiniciar'
        return jsonify({'success': False, 'error': err, 'result': result}), 400
    return jsonify({'success': True, 'result': result})

# ===== Sistema (optimizar, reiniciar, apagar) =====
@app.route('/api/hardware/system/optimize', methods=['POST'])
@require_xhr_header
@api
def hardware_system_optimize():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get('confirm'):
        return jsonify({'success': False, 'error': 'Confirmación requerida'}), 400
    _run(['sync'])
    drop = _run(['sudo', '-n', '/usr/local/bin/rfid-drop-caches.sh'])
    if not drop.get('success'):
        try:
            with open('/proc/sys/vm/drop_caches', 'w') as f:
                f.write('3')
            drop = {'success': True, 'stdout': 'cache liberada (directo)'}
        except PermissionError:
            return jsonify({'success': False, 'error': 'Permiso denegado para liberar caché.', 'result': drop}), 403
    return jsonify({'success': True, 'result': drop})

@app.route('/api/hardware/system/reboot', methods=['POST'])
@require_xhr_header
@api
def hardware_system_reboot():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get('confirm'):
        return jsonify({'success': False, 'error': 'Confirmación requerida'}), 400
    result = _run(['sudo', '-n', 'systemctl', 'reboot'], timeout=5)
    if not result.get('success'):
        result = _run(['systemctl', 'reboot'], timeout=5)
    ok = result.get('success', False)
    _registrar_auditoria('hardware_system_reboot', '', 'éxito' if ok else 'error')
    return jsonify({'success': ok, 'result': result})

@app.route('/api/hardware/system/shutdown', methods=['POST'])
@require_xhr_header
@api
def hardware_system_shutdown():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get('confirm'):
        return jsonify({'success': False, 'error': 'Confirmación requerida'}), 400
    result = _run(['sudo', '-n', 'systemctl', 'poweroff'], timeout=5)
    if not result.get('success'):
        result = _run(['systemctl', 'poweroff'], timeout=5)
    ok = result.get('success', False)
    _registrar_auditoria('hardware_system_shutdown', '', 'éxito' if ok else 'error')
    return jsonify({'success': ok, 'result': result})

# ===== Software admin - servicios =====
@app.route('/api/software/services')
@api
def software_services_list():
    return jsonify({'success': True, 'services': _obtener_estado_servicios()})

@app.route('/api/software/services/<service_name>/<action>', methods=['POST'])
@api
def software_service_action(service_name, action):
    if service_name not in RFID_SERVICES:
        return jsonify({'success': False, 'error': 'Servicio no permitido'}), 403
    if action not in {'start', 'stop', 'restart', 'enable', 'disable', 'status'}:
        return jsonify({'success': False, 'error': 'Acción no permitida'}), 400
    result = _systemctl(action, service_name)
    ok = result.get('success', False)
    if not ok and result.get('stderr'):
        err_low = result['stderr'].lower()
        if any(k in err_low for k in ('password', 'permission', 'access denied', 'interactive')):
            return jsonify({
                'success': False,
                'error': 'Permiso denegado. Configura sudo NOPASSWD.',
                'result': result,
            }), 403
    active_r  = _run(['systemctl', 'is-active',  service_name])
    enabled_r = _run(['systemctl', 'is-enabled', service_name])
    return jsonify({
        'success':      ok,
        'service':      service_name,
        'action':       action,
        'active':       active_r.get('stdout', '').strip() == 'active',
        'enabled':      enabled_r.get('stdout', '').strip() in ('enabled', 'static'),
        'active_text':  active_r.get('stdout', '').strip()  or 'unknown',
        'enabled_text': enabled_r.get('stdout', '').strip() or 'unknown',
        'result':       result,
    })

@app.route('/api/software/services/<service_name>/logs')
@api
def software_service_logs(service_name):
    if service_name not in RFID_SERVICES:
        return jsonify({'success': False, 'error': 'Servicio no permitido'}), 403
    lines  = min(request.args.get('lines', 80, type=int), 500)
    result = _run(['journalctl', '-u', service_name, f'-n{lines}', '--no-pager', '--output=short'])
    return jsonify({
        'success': True,
        'service': service_name,
        'lines':   lines,
        'log':     result.get('stdout') or result.get('stderr') or '(sin salida)',
        'result':  result,
    })

# ===== Software admin - base de datos =====
import re as _re
_BACKUP_RE = _re.compile(r'^rfid_backup_\d{8}_\d{6}\.db$')

def _backup_path(filename: str) -> str:
    if not _BACKUP_RE.match(filename):
        raise ValueError('Nombre de respaldo no válido')
    return os.path.join(BACKUP_DIR, filename)

@app.route('/api/software/database/status')
@api
def software_database_status():
    size_mb = round(os.path.getsize(DB) / (1024 * 1024), 3) if os.path.exists(DB) else None
    conn = get_db()
    try:
        counts = {
            'estudiantes': conn.execute("SELECT COUNT(*) AS t FROM estudiantes").fetchone()['t'],
            'tarjetas':    conn.execute("SELECT COUNT(*) AS t FROM tarjetas").fetchone()['t'],
            'registros':   conn.execute("SELECT COUNT(*) AS t FROM registros_asistencia").fetchone()['t'],
        }
    finally:
        conn.close()
    backups = _list_backups()
    return jsonify({'success': True, 'database': {
        'db_path':       DB,
        'db_size_mb':    size_mb,
        'counts':        counts,
        'backups_count': len(backups),
    }})

def _list_backups() -> list[dict]:
    items = []
    if not os.path.isdir(BACKUP_DIR):
        return items
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not _BACKUP_RE.match(name):
            continue
        path = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(path):
            continue
        items.append({
            'filename':   name,
            'size_mb':    round(os.path.getsize(path) / (1024 * 1024), 3),
            'created_at': datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
        })
    return items

@app.route('/api/software/database/backups')
@api
def software_database_backups():
    return jsonify({'success': True, 'backups': _list_backups()})

def _crear_backup() -> dict:
    if not os.path.exists(DB):
        raise FileNotFoundError('Base de datos no encontrada')
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'rfid_backup_{ts}.db'
    dest     = os.path.join(BACKUP_DIR, filename)
    src_conn = sqlite3.connect(DB)
    try:
        dst_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return {
        'filename': filename,
        'dest':     dest,
        'size_mb':  round(os.path.getsize(dest) / (1024 * 1024), 3),
    }

@app.route('/api/software/database/backup', methods=['POST'])
@api
def software_database_backup():
    try:
        info = _crear_backup()
    except FileNotFoundError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    _registrar_auditoria('software_database_backup', f"filename={info['filename']}", 'éxito')
    return jsonify({
        'success':  True,
        'filename': info['filename'],
        'size_mb':  info['size_mb'],
        'mensaje':  f"Respaldo creado: {info['filename']}",
    })

@app.route('/api/software/database/restore', methods=['POST'])
@require_xhr_header
@api
def software_database_restore():
    data     = request.get_json(force=True, silent=True) or {}
    filename = (data.get('filename') or '').strip()
    if not data.get('confirm'):
        return jsonify({'success': False, 'error': 'Confirmación requerida'}), 400
    if not filename:
        return jsonify({'success': False, 'error': 'filename requerido'}), 400
    try:
        src = _backup_path(filename)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if not os.path.isfile(src):
        return jsonify({'success': False, 'error': 'Respaldo no encontrado'}), 404
    ts_pre    = datetime.now().strftime('%Y%m%d_%H%M%S')
    pre_file  = f'rfid_backup_{ts_pre}.db'
    pre_dest  = os.path.join(BACKUP_DIR, pre_file)
    shutil.copy2(DB, pre_dest)
    tmp = DB + '.restore_tmp'
    shutil.copy2(src, tmp)
    os.replace(tmp, DB)
    _schema_cache.clear()
    _registrar_auditoria('software_database_restore', f'filename={filename}', 'éxito')
    return jsonify({
        'success':        True,
        'mensaje':        f'Base restaurada desde {filename}',
        'safety_backup':  pre_file,
    })

@app.route('/api/software/database/backups/<filename>/download')
def software_database_download(filename):
    try:
        path = _backup_path(filename)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if not os.path.isfile(path):
        return jsonify({'success': False, 'error': 'No encontrado'}), 404
    def gen():
        with open(path, 'rb') as f:
            while chunk := f.read(65536):
                yield chunk
    return Response(gen(), mimetype='application/octet-stream',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/api/software/database/backups/<filename>', methods=['DELETE'])
@api
def software_database_delete_backup(filename):
    confirm = request.args.get('confirm') or (request.get_json(silent=True) or {}).get('confirm')
    if not confirm:
        return jsonify({'success': False, 'error': 'Confirmación requerida'}), 400
    try:
        path = _backup_path(filename)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if not os.path.isfile(path):
        return jsonify({'success': False, 'error': 'No encontrado'}), 404
    os.remove(path)
    _registrar_auditoria('software_database_backup_delete', f'filename={filename}', 'éxito')
    return jsonify({'success': True, 'mensaje': f'Respaldo {filename} eliminado'})

@app.route('/api/software/database/purge/preview', methods=['POST'])
@api
def software_database_purge_preview():
    data = request.get_json(force=True, silent=True) or {}
    try:
        count = _purge_count(data)
        return jsonify({'success': True, 'count': count})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/software/database/purge', methods=['POST'])
@require_xhr_header
@api
def software_database_purge():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get('confirm'):
        return jsonify({'success': False, 'error': 'Confirmación requerida'}), 400
    filtros = {k: v for k, v in data.items() if k != 'confirm'}
    try:
        resultado = _purge_execute(data)
    except _PurgeBackupError as e:
        _registrar_auditoria('software_database_purge', f'filtros={filtros}', 'error')
        return jsonify({'success': False, 'error': str(e)}), 500
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    deleted = resultado['deleted']
    _registrar_auditoria(
        'software_database_purge',
        f"filtros={filtros}; eliminados={deleted}; safety_backup={resultado['safety_backup']}",
        'éxito',
    )
    return jsonify({
        'success':       True,
        'deleted':       deleted,
        'safety_backup': resultado['safety_backup'],
        'mensaje':       f'{deleted} registro(s) eliminados',
    })

def _purge_build(data: dict) -> tuple[str, list]:
    clauses = ['1=1']
    params: list = []
    if data.get('fecha_desde'):
        clauses.append('datetime(ra.timestamp) >= datetime(?)')
        d = data['fecha_desde']
        params.append(d + ' 00:00:00' if len(d) == 10 else d)
    if data.get('fecha_hasta'):
        clauses.append('datetime(ra.timestamp) <= datetime(?)')
        d = data['fecha_hasta']
        params.append(d + ' 23:59:59' if len(d) == 10 else d)
    if data.get('carrera'):
        clauses.append('e.carrera = ?')
        params.append(data['carrera'])
    if data.get('semestre'):
        clauses.append('e.semestre = ?')
        params.append(str(data['semestre']))
    if data.get('grupo'):
        clauses.append("UPPER(COALESCE(e.grupo,'')) = ?")
        params.append(str(data['grupo']).upper())
    if data.get('matricula'):
        clauses.append('e.matricula = ?')
        params.append(str(data['matricula']).strip())
    if data.get('estudiante_id'):
        clauses.append('ra.id_estudiante = ?')
        params.append(int(data['estudiante_id']))
    where = ' AND '.join(clauses)
    return where, params

def _purge_count(data: dict) -> int:
    where, params = _purge_build(data)
    conn = get_db()
    try:
        return conn.execute(
            f"SELECT COUNT(*) AS t FROM registros_asistencia ra "
            f"LEFT JOIN estudiantes e ON ra.id_estudiante=e.id WHERE {where}",
            params
        ).fetchone()['t']
    finally:
        conn.close()

class _PurgeBackupError(RuntimeError):
    pass

def _purge_execute(data: dict) -> dict:
    where, params = _purge_build(data)
    try:
        backup_info = _crear_backup()
    except Exception as e:
        raise _PurgeBackupError(
            f'No se pudo crear respaldo previo; purga cancelada: {e}'
        ) from e
    conn = get_db()
    try:
        cur = conn.execute(
            f"DELETE FROM registros_asistencia WHERE id IN ("
            f"SELECT ra.id FROM registros_asistencia ra "
            f"LEFT JOIN estudiantes e ON ra.id_estudiante=e.id WHERE {where})",
            params
        )
        conn.commit()
        return {'deleted': cur.rowcount, 'safety_backup': backup_info['filename']}
    finally:
        conn.close()

# ===== RFID escucha activa =====
@app.route('/api/rfid/listen/start', methods=['POST'])
@api
def rfid_listen_start():
    data = request.get_json(force=True, silent=True) or {}
    timeout_s = data.get('timeout', 30)
    with _rfid_listen_lock:
        _rfid_listen_state.update({'active': True, 'uid': None, 'timestamp': None,
                                   'expires': time.time() + timeout_s})
    return jsonify({'success': True, 'mensaje': 'Modo escucha activo', 'timeout': timeout_s})

@app.route('/api/rfid/listen/status')
@api
def rfid_listen_status():
    with _rfid_listen_lock:
        state = dict(_rfid_listen_state)
    if state['expires'] and time.time() > state['expires']:
        with _rfid_listen_lock:
            _rfid_listen_state['active'] = False
        state['active'] = False
    return jsonify({'success': True, **state})

@app.route('/api/rfid/listen/stop', methods=['POST'])
@api
def rfid_listen_stop():
    with _rfid_listen_lock:
        _rfid_listen_state.update({'active': False, 'uid': None, 'expires': None})
    return jsonify({'success': True, 'mensaje': 'Escucha cancelada'})

@app.route('/api/rfid/listen/capture', methods=['POST'])
@api
def rfid_listen_capture():
    d   = request.get_json(force=True)
    uid = (d.get('uid') or '').strip()
    if not uid:
        return jsonify({'success': False, 'error': 'UID requerido'}), 400
    with _rfid_listen_lock:
        if not _rfid_listen_state['active']:
            return jsonify({'success': False, 'error': 'Modo escucha no activo'}), 409
        _rfid_listen_state.update({'uid': uid, 'timestamp': datetime.now().isoformat(), 'active': False})
    return jsonify({'success': True, 'uid': uid})

# ===== RFID escaneo masivo admin =====
def _enriquecer_uid(conn, uid: str) -> dict:
    tarjeta = conn.execute("""
        SELECT t.id, t.activa, t.id_estudiante,
               e.nombre, e.apellido_paterno, e.matricula, e.semestre, e.grupo, e.estado
        FROM tarjetas t LEFT JOIN estudiantes e ON t.id_estudiante=e.id
        WHERE t.uid=?
    """, (uid,)).fetchone()
    if not tarjeta:
        return {'uid': uid, 'estado_tarjeta': 'nueva', 'nombre': None,
                'matricula': None, 'semestre': None, 'grupo': None, 'tarjeta_id': None}
    nombre = ((tarjeta['nombre'] or '') + ' ' + (tarjeta['apellido_paterno'] or '')).strip() or None
    return {
        'uid': uid, 'tarjeta_id': tarjeta['id'],
        'estado_tarjeta': 'activa' if tarjeta['activa'] else 'inactiva',
        'nombre': nombre, 'matricula': tarjeta['matricula'],
        'semestre': tarjeta['semestre'], 'grupo': tarjeta['grupo'], 'est_estado': tarjeta['estado'],
    }

def _leer_uid_admin() -> tuple[str | None, str | None]:
    if not os.path.exists(ADMIN_UID_FILE):
        return None, None
    try:
        with open(ADMIN_UID_FILE, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                line = f.read().strip()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except FileNotFoundError:
        return None, None
    except Exception:
        log.exception("Error leyendo ADMIN_UID_FILE")
        return None, None
    try:
        os.remove(ADMIN_UID_FILE)
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("Error eliminando ADMIN_UID_FILE")
    if not line:
        return None, None
    parts = line.split('\t', 1)
    return (parts[1].strip(), parts[0].strip()) if len(parts) == 2 else (parts[0].strip(), datetime.now().isoformat())

@app.route('/api/rfid/admin-scan/start', methods=['POST'])
@api
def admin_scan_start():
    data = request.get_json(force=True, silent=True) or {}
    timeout_s = data.get('timeout', 300)
    try:
        with open(ADMIN_FLAG, 'w') as f:
            f.write(datetime.now().isoformat())
        if os.path.exists(ADMIN_UID_FILE):
            try:
                with open(ADMIN_UID_FILE, 'r') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                os.remove(ADMIN_UID_FILE)
            except FileNotFoundError:
                pass
    except Exception as e:
        return jsonify({'success': False, 'error': f'No se pudo crear señal admin: {e}'}), 500
    with _admin_scan_lock:
        _admin_scan_state.update({'active': True, 'uids': [], 'expires': time.time() + timeout_s, 'ultimo_uid_ts': None})
    return jsonify({'success': True, 'mensaje': 'Sesión admin iniciada', 'timeout': timeout_s})

@app.route('/api/rfid/admin-scan/status')
@api
def admin_scan_status():
    with _admin_scan_lock:
        if _admin_scan_state['expires'] and time.time() > _admin_scan_state['expires']:
            _admin_scan_state['active'] = False
            try: os.remove(ADMIN_FLAG)
            except FileNotFoundError: pass
        if not _admin_scan_state['active']:
            return jsonify({'success': True, 'active': False, 'uids': list(_admin_scan_state['uids'])})
        uid_nuevo, ts_nuevo = _leer_uid_admin()
        if uid_nuevo and not any(e['uid'] == uid_nuevo for e in _admin_scan_state['uids']):
            conn = get_db()
            try:
                info = _enriquecer_uid(conn, uid_nuevo)
            finally:
                conn.close()
            info['ts'] = ts_nuevo or datetime.now().isoformat()
            _admin_scan_state['uids'].append(info)
        return jsonify({'success': True, 'active': _admin_scan_state['active'], 'uids': list(_admin_scan_state['uids'])})

@app.route('/api/rfid/admin-scan/stop', methods=['POST'])
@api
def admin_scan_stop():
    for f in (ADMIN_FLAG, ADMIN_UID_FILE):
        try: os.remove(f)
        except FileNotFoundError: pass
    with _admin_scan_lock:
        _admin_scan_state.update({'active': False, 'expires': None})
    return jsonify({'success': True, 'mensaje': 'Sesión admin cerrada'})

@app.route('/api/rfid/admin-scan/guardar', methods=['POST'])
@api
def admin_scan_guardar():
    uids = [u.strip() for u in (request.get_json(force=True).get('uids', [])) if u and u.strip()]
    if not uids:
        return jsonify({'success': False, 'error': 'Sin UIDs'}), 400
    conn = get_db()
    try:
        resultados = []
        for uid in uids:
            if conn.execute("SELECT id FROM tarjetas WHERE uid=?", (uid,)).fetchone():
                resultados.append({'uid': uid, 'ok': False, 'msg': 'Ya existe en tarjetas'})
                continue
            try:
                conn.execute("INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES (?,NULL,1)", (uid,))
                conn.commit()
                resultados.append({'uid': uid, 'ok': True, 'msg': 'Guardada'})
            except Exception as e:
                resultados.append({'uid': uid, 'ok': False, 'msg': str(e)})
    finally:
        conn.close()
    ok = sum(1 for r in resultados if r['ok'])
    return jsonify({'success': True, 'resultados': resultados, 'guardadas': ok, 'total': len(uids)})

@app.route('/api/rfid/admin-scan/eliminar', methods=['POST'])
@api
def admin_scan_eliminar():
    d      = request.get_json(force=True)
    uids   = [u.strip() for u in d.get('uids', []) if u and u.strip()]
    forzar = bool(d.get('forzar', False))
    if not uids:
        return jsonify({'success': False, 'error': 'Sin UIDs'}), 400
    conn = get_db()
    try:
        resultados = []
        for uid in uids:
            tarjeta = conn.execute("SELECT id, id_estudiante FROM tarjetas WHERE uid=?", (uid,)).fetchone()
            if not tarjeta:
                resultados.append({'uid': uid, 'ok': False, 'msg': 'No existe en tarjetas'})
                continue
            if tarjeta['id_estudiante'] is not None and not forzar:
                resultados.append({'uid': uid, 'ok': False, 'msg': 'Tiene estudiante asignado (usa forzar=true)'})
                continue
            conn.execute("DELETE FROM tarjetas WHERE uid=?", (uid,))
            conn.commit()
            resultados.append({'uid': uid, 'ok': True, 'msg': 'Eliminada'})
    finally:
        conn.close()
    ok = sum(1 for r in resultados if r['ok'])
    return jsonify({'success': True, 'resultados': resultados, 'eliminadas': ok, 'total': len(uids)})

# ===== RFID helpers =====
@app.route('/api/rfid/desconocidos')
@api
def rfid_desconocidos():
    conn = get_db()
    try:
        s    = schema(conn)
        rows = conn.execute(f"""
            SELECT ra.uid, COUNT(*) AS veces, MAX(ra.timestamp) AS ultimo_scan
            FROM registros_asistencia ra
            WHERE ra.{s['col']} IN ('rebote','desconocido')
              AND NOT EXISTS (SELECT 1 FROM tarjetas t WHERE t.uid=ra.uid)
            GROUP BY ra.uid ORDER BY veces DESC LIMIT 50
        """).fetchall()
    finally:
        conn.close()
    return jsonify({'success': True, 'desconocidos': [dict(r) for r in rows]})

@app.route('/api/rfid/guardar-uid', methods=['POST'])
@api
def rfid_guardar_uid():
    d   = request.get_json(force=True)
    uid = (d.get('uid') or '').strip()
    if not uid:
        return jsonify({'success': False, 'error': 'UID vacío'}), 400
    conn = get_db()
    try:
        tarjeta = conn.execute("""
            SELECT t.id, t.id_estudiante, t.activa, e.estado
            FROM tarjetas t LEFT JOIN estudiantes e ON t.id_estudiante=e.id WHERE t.uid=?
        """, (uid,)).fetchone()
        if tarjeta:
            if tarjeta['id_estudiante'] is None:
                return jsonify({'success': False, 'error': 'UID existe pero sin alumno asignado'})
            if tarjeta['activa'] != 1 or tarjeta['estado'] != 'activo':
                return jsonify({'success': False, 'error': 'Tarjeta o estudiante inactivo'})
            return jsonify({'success': True, 'ya_existe': True, 'mensaje': 'UID ya registrado'})
        conn.execute("INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES (?,NULL,1)", (uid,))
        conn.commit()
        return jsonify({'success': True, 'ya_existe': False, 'mensaje': f'UID {uid} guardado'})
    finally:
        conn.close()

@app.route('/api/rfid/tarjetas-sin-asignar')
@api
def tarjetas_sin_asignar():
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, uid, asignada_en FROM tarjetas WHERE id_estudiante IS NULL ORDER BY asignada_en DESC LIMIT 100").fetchall()
    finally:
        conn.close()
    return jsonify({'success': True, 'tarjetas': [dict(r) for r in rows]})

@app.route('/api/rfid/alumnos-sin-tarjeta')
@api
def alumnos_sin_tarjeta():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT e.id, e.nombre, e.apellido_paterno, e.matricula, e.semestre, e.grupo
            FROM estudiantes e
            WHERE e.carrera=? AND e.estado='activo'
              AND NOT EXISTS (SELECT 1 FROM tarjetas t WHERE t.id_estudiante=e.id)
            ORDER BY CAST(e.semestre AS INTEGER), e.apellido_paterno
        """, (CARRERA,)).fetchall()
    finally:
        conn.close()
    return jsonify({'success': True, 'alumnos': [dict(r) for r in rows]})

@app.route('/api/rfid/historial/<path:uid>')
@api
def rfid_historial(uid):
    conn = get_db()
    try:
        s    = schema(conn)
        rows = conn.execute(f"""
            SELECT ra.*, ra.{s['col']} AS tipo_raw,
                   COALESCE(e.nombre||' '||COALESCE(e.apellido_paterno,''),'') AS nombre, e.matricula
            FROM registros_asistencia ra LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            WHERE ra.uid=? ORDER BY ra.timestamp DESC LIMIT 100
        """, (uid,)).fetchall()
    finally:
        conn.close()
    return jsonify({'success': True, 'historial': [dict(r) for r in rows], 'uid': uid})

@app.route('/api/rfid/ultimo-scan')
@api
def ultimo_scan():
    conn = get_db()
    try:
        s    = schema(conn)
        row  = conn.execute(f"""
            SELECT ra.uid, ra.timestamp, ra.{s['col']} AS tipo,
                   e.nombre, e.apellido_paterno, e.matricula, e.semestre, e.grupo, e.foto
            FROM registros_asistencia ra LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            ORDER BY ra.timestamp DESC LIMIT 1
        """).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({'success': True, 'scan': None})
    r = dict(row)
    r['estudiante_nombre'] = (f"{r.get('nombre') or ''} {r.get('apellido_paterno') or ''}".strip() or None)
    return jsonify({'success': True, 'scan': r})

# ===== Estudiantes =====
@app.route('/api/estudiantes', methods=['GET'])
@api
def get_estudiantes():
    conn = get_db()
    try:
        q = ("SELECT e.*, COUNT(DISTINCT t.id) AS tarjetas_asignadas, COUNT(DISTINCT ra.id) AS total_registros "
             "FROM estudiantes e LEFT JOIN tarjetas t ON e.id=t.id_estudiante "
             "LEFT JOIN registros_asistencia ra ON e.id=ra.id_estudiante WHERE e.carrera=?")
        p = [CARRERA]
        if (sem := request.args.get('semestre')): q += " AND e.semestre=?"; p.append(sem)
        if (grp := request.args.get('grupo', '').strip().upper()): q += " AND UPPER(COALESCE(e.grupo,''))=?"; p.append(grp)
        if (bus := request.args.get('buscar', '').strip()):
            q += " AND (e.nombre LIKE ? OR e.apellido_paterno LIKE ? OR e.matricula LIKE ? OR EXISTS (SELECT 1 FROM tarjetas t2 WHERE t2.id_estudiante=e.id AND t2.uid LIKE ?))"
            p += [f'%{bus}%'] * 4
        q += " GROUP BY e.id ORDER BY CAST(e.semestre AS INTEGER), e.apellido_paterno, e.nombre"
        rows = [dict(r) for r in conn.execute(q, p).fetchall()]
    finally:
        conn.close()
    return jsonify({'success': True, 'estudiantes': rows})

@app.route('/api/estudiantes/grupos')
@api
def grupos():
    conn = get_db()
    try:
        try:
            rows = conn.execute("""
                SELECT e.*, COUNT(DISTINCT t.id) AS tarjetas_asignadas
                FROM estudiantes e LEFT JOIN tarjetas t ON e.id=t.id_estudiante
                WHERE e.estado='activo' AND e.carrera=?
                GROUP BY e.id ORDER BY CAST(e.semestre AS INTEGER), COALESCE(e.grupo,''), e.apellido_paterno
            """, (CARRERA,)).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute("""
                SELECT e.*, COUNT(DISTINCT t.id) AS tarjetas_asignadas
                FROM estudiantes e LEFT JOIN tarjetas t ON e.id=t.id_estudiante
                WHERE e.estado='activo' AND e.carrera=? GROUP BY e.id
                ORDER BY CAST(e.semestre AS INTEGER), e.apellido_paterno
            """, (CARRERA,)).fetchall()
        grupos_dict: dict = {}
        for row in rows:
            e = dict(row)
            key = f"{e.get('semestre','')}-{e.get('grupo','')}"
            if key not in grupos_dict:
                grupos_dict[key] = {'carrera': CARRERA, 'semestre': str(e.get('semestre','')), 'grupo': e.get('grupo',''), 'estudiantes': []}
            grupos_dict[key]['estudiantes'].append(e)
    finally:
        conn.close()
    return jsonify({'success': True, 'grupos': list(grupos_dict.values())})

@app.route('/api/estudiantes/<int:est_id>', methods=['GET'])
@api
def get_estudiante(est_id):
    conn = get_db()
    try:
        row  = conn.execute("SELECT * FROM estudiantes WHERE id=? AND carrera=?", (est_id, CARRERA)).fetchone()
    finally:
        conn.close()
    if not row: return jsonify({'success': False, 'error': 'No encontrado'}), 404
    return jsonify({'success': True, 'estudiante': dict(row)})

@app.route('/api/estudiantes', methods=['POST'])
@api
def crear_estudiante():
    d    = request.get_json(force=True)
    conn = get_db()
    try:
        conn.execute("INSERT INTO estudiantes (nombre,apellido_paterno,apellido_materno,matricula,carrera,semestre,grupo,correo,estado,foto) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (d.get('nombre'), d.get('apellido_paterno'), d.get('apellido_materno'), d.get('matricula'), CARRERA, d.get('semestre'), d.get('grupo',''), d.get('correo'), d.get('estado','activo'), d.get('foto')))
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
    finally:
        conn.close()
    return jsonify({'success': True, 'id': new_id, 'mensaje': 'Estudiante creado'})

@app.route('/api/estudiantes/<int:est_id>', methods=['PUT'])
@api
def actualizar_estudiante(est_id):
    d    = request.get_json(force=True)
    conn = get_db()
    try:
        row_actual = conn.execute("SELECT foto FROM estudiantes WHERE id=? AND carrera=?", (est_id, CARRERA)).fetchone()
        foto_actual = row_actual['foto'] if row_actual else None
        foto_nueva  = d.get('foto')
        conn.execute("UPDATE estudiantes SET nombre=?,apellido_paterno=?,apellido_materno=?,matricula=?,carrera=?,semestre=?,grupo=?,correo=?,estado=?,foto=? WHERE id=? AND carrera=?",
                     (d.get('nombre'), d.get('apellido_paterno'), d.get('apellido_materno'), d.get('matricula'), CARRERA, d.get('semestre'), d.get('grupo',''), d.get('correo'), d.get('estado'), foto_nueva, est_id, CARRERA))
        conn.commit()
    finally:
        conn.close()
    if foto_nueva and foto_actual and foto_nueva != foto_actual:
        _eliminar_foto_disco(foto_actual)
    return jsonify({'success': True, 'mensaje': 'Estudiante actualizado'})

@app.route('/api/estudiantes/<int:est_id>', methods=['DELETE'])
@api
def eliminar_estudiante(est_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT foto FROM estudiantes WHERE id=? AND carrera=?", (est_id, CARRERA)).fetchone()
        foto_actual = row['foto'] if row else None
        conn.execute("DELETE FROM estudiantes WHERE id=? AND carrera=?", (est_id, CARRERA))
        conn.commit()
    finally:
        conn.close()
    if foto_actual:
        _eliminar_foto_disco(foto_actual)
    return jsonify({'success': True, 'mensaje': 'Estudiante eliminado'})

# ===== Configuraciones globales (promoción, baja, alta masiva) =====
@app.route('/api/estudiantes/promover', methods=['POST'])
@api
def promover_estudiantes():
    d = request.get_json(force=True) or {}
    ids = [int(i) for i in d.get('ids', []) if str(i).isdigit()]
    desde = d.get('desde_semestre')
    grupo = (d.get('grupo') or '').strip().upper()
    if ids:
        where = (f"carrera=? AND estado='activo' AND CAST(semestre AS INTEGER) < 9 "
                 f"AND id IN ({','.join('?' * len(ids))})")
        params: list = [CARRERA] + ids
    else:
        if not desde:
            return jsonify({'success': False, 'error': 'desde_semestre o ids es requerido'}), 400
        try:
            desde_i = int(desde)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'desde_semestre inválido'}), 400
        if desde_i >= 9:
            return jsonify({'success': False, 'error': 'El semestre 9 no se puede promover; da de baja manualmente.'}), 400
        where = "carrera=? AND estado='activo' AND semestre=?"
        params = [CARRERA, desde_i]
        if grupo:
            where += " AND UPPER(COALESCE(grupo,''))=?"
            params.append(grupo)
    conn = get_db()
    try:
        afectados = conn.execute(f"SELECT COUNT(*) AS t FROM estudiantes WHERE {where}", params).fetchone()['t']
        if d.get('confirmar'):
            conn.execute(f"UPDATE estudiantes SET semestre = CAST(semestre AS INTEGER) + 1 WHERE {where}", params)
            conn.commit()
    finally:
        conn.close()
    if d.get('confirmar'):
        detalle = f"ids={ids}" if ids else f"desde_semestre={desde}, grupo={grupo or '(todos)'}"
        _registrar_auditoria('estudiantes_promover', f'{detalle}; afectados={afectados}', 'éxito')
    return jsonify({'success': True, 'afectados': afectados, 'aplicado': bool(d.get('confirmar')),
                    'mensaje': f'{afectados} estudiante(s) {"promovidos" if d.get("confirmar") else "coinciden"}'})

@app.route('/api/estudiantes/baja-masiva', methods=['POST'])
@require_xhr_header
@api
def baja_masiva():
    d = request.get_json(force=True) or {}
    ids = [int(i) for i in d.get('ids', []) if str(i).isdigit()]
    semestre = d.get('semestre')
    grupo = (d.get('grupo') or '').strip().upper()
    if ids:
        where = f"carrera=? AND id IN ({','.join('?' * len(ids))})"
        params = [CARRERA] + ids
    elif semestre:
        where = "carrera=? AND estado='activo' AND semestre=?"
        params = [CARRERA, semestre]
        if grupo:
            where += " AND UPPER(COALESCE(grupo,''))=?"
            params.append(grupo)
    else:
        return jsonify({'success': False, 'error': 'Se requiere una lista de ids o un semestre'}), 400
    conn = get_db()
    try:
        afectados = conn.execute(f"SELECT COUNT(*) AS t FROM estudiantes WHERE {where}", params).fetchone()['t']
        if d.get('confirmar'):
            conn.execute(f"UPDATE estudiantes SET estado='inactivo' WHERE {where}", params)
            conn.commit()
    finally:
        conn.close()
    if d.get('confirmar'):
        detalle = f"ids={ids}" if ids else f"semestre={semestre}, grupo={grupo or '(todos)'}"
        _registrar_auditoria('estudiantes_baja_masiva', f'{detalle}; afectados={afectados}', 'éxito')
    return jsonify({'success': True, 'afectados': afectados, 'aplicado': bool(d.get('confirmar')),
                    'mensaje': f'{afectados} estudiante(s) {"dados de baja" if d.get("confirmar") else "coinciden"}'})

@app.route('/api/estudiantes/alta-masiva', methods=['POST'])
@api
def alta_masiva():
    d = request.get_json(force=True) or {}
    filas = d.get('estudiantes', [])
    if not isinstance(filas, list) or not filas:
        return jsonify({'success': False, 'error': 'Sin estudiantes para insertar'}), 400
    creados, errores = 0, []
    conn = get_db()
    try:
        for idx, f in enumerate(filas):
            nombre = (f.get('nombre') or '').strip()
            ap_p   = (f.get('apellido_paterno') or '').strip()
            mat    = (f.get('matricula') or '').strip()
            if not (nombre and ap_p and mat):
                errores.append({'fila': idx + 1, 'error': 'Faltan nombre, apellido paterno o matrícula'})
                continue
            try:
                conn.execute(
                    "INSERT INTO estudiantes (nombre,apellido_paterno,apellido_materno,matricula,carrera,semestre,grupo,correo,estado) VALUES (?,?,?,?,?,?,?,?,?)",
                    (nombre, ap_p, (f.get('apellido_materno') or '').strip(), mat, CARRERA,
                     f.get('semestre') or 1, (f.get('grupo') or '').strip(), (f.get('correo') or '').strip(), 'activo'))
                creados += 1
            except sqlite3.IntegrityError as e:
                errores.append({'fila': idx + 1, 'error': str(e)})
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'creados': creados, 'errores': errores,
                    'mensaje': f'{creados} estudiante(s) creados' + (f', {len(errores)} con error' if errores else '')})

@app.route('/api/estudiantes/<int:est_id>/perfil')
@api
def perfil_estudiante(est_id):
    conn = get_db()
    try:
        s    = schema(conn)
        est  = conn.execute("SELECT * FROM estudiantes WHERE id=? AND carrera=?", (est_id, CARRERA)).fetchone()
        if not est: return jsonify({'success': False, 'error': 'No encontrado'}), 404
        tarjetas  = [dict(r) for r in conn.execute("SELECT * FROM tarjetas WHERE id_estudiante=?", (est_id,)).fetchall()]
        registros = [dict(r) for r in conn.execute(f"SELECT fecha_dia, {s['col']} AS tipo, timestamp, uid FROM registros_asistencia WHERE id_estudiante=? ORDER BY timestamp DESC LIMIT 90", (est_id,)).fetchall()]
        total_acc = conn.execute(f"SELECT COUNT(*) AS t FROM registros_asistencia WHERE id_estudiante=? AND {s['col']} IN ('aceptado','entrada')", (est_id,)).fetchone()['t']
        ultimo    = conn.execute(f"SELECT timestamp FROM registros_asistencia WHERE id_estudiante=? ORDER BY timestamp DESC LIMIT 1", (est_id,)).fetchone()
    finally:
        conn.close()
    return jsonify({'success': True, 'estudiante': dict(est), 'tarjetas': tarjetas, 'registros': registros,
                    'total_asistencias': total_acc, 'ultimo_acceso': dict(ultimo)['timestamp'] if ultimo else None})

# ===== Tarjetas =====
@app.route('/api/tarjetas', methods=['GET'])
@api
def get_tarjetas():
    conn   = get_db()
    limit  = min(request.args.get('limit', 50, type=int), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)
    try:
        total = conn.execute("""
            SELECT COUNT(*) AS t
            FROM tarjetas t LEFT JOIN estudiantes e ON t.id_estudiante=e.id
            WHERE e.id IS NULL OR e.carrera=?
        """, (CARRERA,)).fetchone()['t']
        rows = conn.execute("""
            SELECT t.*, e.nombre, e.apellido_paterno, e.matricula, e.semestre, e.grupo, e.estado AS est_estado
            FROM tarjetas t LEFT JOIN estudiantes e ON t.id_estudiante=e.id
            WHERE e.id IS NULL OR e.carrera=? ORDER BY t.asignada_en DESC LIMIT ? OFFSET ?
        """, (CARRERA, limit, offset)).fetchall()
        tarjetas = []
        for r in rows:
            t = dict(r)
            t['estudiante_nombre'] = ((t.get('nombre','') or '') + ' ' + (t.get('apellido_paterno','') or '')).strip() or None
            tarjetas.append(t)
    finally:
        conn.close()
    return jsonify({'success': True, 'tarjetas': tarjetas, 'total': total, 'limit': limit, 'offset': offset})

@app.route('/api/tarjetas', methods=['POST'])
@api
def crear_tarjeta():
    d   = request.get_json(force=True)
    uid = (d.get('uid') or '').strip()
    if not uid: return jsonify({'success': False, 'error': 'UID requerido'}), 400
    conn = get_db()
    try:
        conn.execute("INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES (?,?,?)", (uid, d.get('id_estudiante') or None, int(d.get('activa', 1))))
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
    finally:
        conn.close()
    return jsonify({'success': True, 'id': new_id, 'mensaje': 'Tarjeta asignada'})

@app.route('/api/tarjetas/<int:tarj_id>', methods=['PUT'])
@api
def actualizar_tarjeta(tarj_id):
    d = request.get_json(force=True)
    conn = get_db()
    try:
        conn.execute("UPDATE tarjetas SET uid=?, id_estudiante=?, activa=? WHERE id=?", (d.get('uid'), d.get('id_estudiante') or None, int(d.get('activa', 1)), tarj_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'mensaje': 'Tarjeta actualizada'})

@app.route('/api/tarjetas/<int:tarj_id>', methods=['DELETE'])
@api
def eliminar_tarjeta(tarj_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM tarjetas WHERE id=?", (tarj_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'mensaje': 'Tarjeta eliminada'})

@app.route('/api/tarjetas/bulk-toggle', methods=['POST'])
@api
def bulk_toggle():
    d      = request.get_json(force=True)
    ids    = [int(i) for i in d.get('ids', []) if str(i).isdigit()]
    activa = int(bool(d.get('activa', 1)))
    if not ids: return jsonify({'success': False, 'error': 'Sin IDs válidos'}), 400
    conn = get_db()
    try:
        conn.execute(f"UPDATE tarjetas SET activa=? WHERE id IN ({','.join('?'*len(ids))})", [activa]+ids)
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'mensaje': f'{len(ids)} tarjeta(s) actualizadas'})

# ===== Registros =====
@app.route('/api/registros')
@api
def get_registros():
    conn   = get_db()
    limit  = min(request.args.get('limit', 25, type=int), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)
    fecha  = request.args.get('fecha')
    tipo   = request.args.get('estado')
    uid    = request.args.get('uid', '').strip()
    try:
        s      = schema(conn)
        where  = "WHERE (e.carrera=? OR e.id IS NULL)"
        p: list = [CARRERA]
        if fecha:
            where += f" AND {s['ff']}"; p.append(fecha)
        if tipo:
            vals = ('aceptado','entrada') if tipo == 'aceptado' else (tipo,)
            where += f" AND ra.{s['col']} IN ({','.join('?'*len(vals))})"; p += list(vals)
        if uid:
            where += " AND ra.uid LIKE ?"; p.append(f'%{uid}%')
        total = conn.execute(f"SELECT COUNT(*) AS t FROM registros_asistencia ra LEFT JOIN estudiantes e ON ra.id_estudiante=e.id {where}", p).fetchone()['t']
        rows  = conn.execute(f"""
            SELECT ra.*, ra.{s['col']} AS tipo_raw,
                   COALESCE(e.nombre||' '||COALESCE(e.apellido_paterno,''),'DESCONOCIDO') AS estudiante_nombre,
                   e.matricula, e.foto, e.semestre, e.grupo
            FROM registros_asistencia ra LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            {where} ORDER BY ra.timestamp DESC LIMIT ? OFFSET ?
        """, p + [limit, offset]).fetchall()
    finally:
        conn.close()
    return jsonify({'success': True, 'registros': [dict(r) for r in rows], 'total': total, 'limit': limit, 'offset': offset})

# ===== Audit log =====
@app.route('/api/audit-log')
@api
def get_audit_log():
    conn   = get_db()
    limit  = min(request.args.get('limit', 25, type=int), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)
    accion = request.args.get('accion', '').strip()
    ip     = request.args.get('ip', '').strip()
    where  = "WHERE 1=1"
    p: list = []
    if accion:
        where += " AND accion=?"; p.append(accion)
    if ip:
        where += " AND ip LIKE ?"; p.append(f'%{ip}%')
    try:
        try:
            total = conn.execute(f"SELECT COUNT(*) AS t FROM audit_log {where}", p).fetchone()['t']
            rows  = conn.execute(
                f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                p + [limit, offset]
            ).fetchall()
        except sqlite3.OperationalError as e:
            return jsonify({'success': False, 'error': f'Tabla audit_log no disponible (¿corriste /api/migrate?): {e}'}), 400
    finally:
        conn.close()
    return jsonify({'success': True, 'registros': [dict(r) for r in rows], 'total': total, 'limit': limit, 'offset': offset})

# ===== Asistencia hoy =====
@app.route('/api/asistencia/hoy')
@api
def asistencia_hoy():
    conn = get_db()
    try:
        s = schema(conn); hoy = datetime.now().strftime('%Y-%m-%d')
        rows = conn.execute(f"SELECT DISTINCT ra.id_estudiante FROM registros_asistencia ra JOIN estudiantes e ON ra.id_estudiante=e.id WHERE {s['ff']} AND ra.{s['col']} IN ('aceptado','entrada') AND e.carrera=?", (hoy, CARRERA)).fetchall()
    finally:
        conn.close()
    return jsonify({'success': True, 'presentes': [r['id_estudiante'] for r in rows]})

# ===== Upload foto =====
EXTS_PERMITIDAS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_DIMENSION_FOTO = 2000

@app.route('/api/upload-foto', methods=['POST'])
@api
def upload_foto():
    if 'foto' not in request.files: return jsonify({'success': False, 'error': 'No se envió archivo'}), 400
    file = request.files['foto']
    if not file.filename: return jsonify({'success': False, 'error': 'Archivo vacío'}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in EXTS_PERMITIDAS: return jsonify({'success': False, 'error': f'Tipo no permitido: {ext}'}), 400
    try:
        Image.open(file.stream).verify()
    except Exception:
        return jsonify({'success': False, 'error': 'El archivo no es una imagen válida'}), 400
    file.stream.seek(0)
    try:
        img = Image.open(file.stream)
        img.load()
    except Exception:
        return jsonify({'success': False, 'error': 'El archivo no es una imagen válida'}), 400
    if img.mode != 'RGB':
        img = img.convert('RGB')
    if img.width > MAX_DIMENSION_FOTO or img.height > MAX_DIMENSION_FOTO:
        img.thumbnail((MAX_DIMENSION_FOTO, MAX_DIMENSION_FOTO), Image.LANCZOS)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{secure_filename(file.filename)}"
    base, _ = os.path.splitext(filename)
    filename = base + '.jpg'
    try:
        img.save(os.path.join(FOTOS, filename), format='JPEG', quality=85)
    except Exception:
        return jsonify({'success': False, 'error': 'No se pudo guardar la imagen'}), 400
    return jsonify({'success': True, 'foto_url': f'/static/fotos/{filename}'})

# ===== Exportación =====
def _csv_line(campos):
    buf = io.StringIO()
    csv.writer(buf).writerow(campos)
    return buf.getvalue()

def _csv_safe(value):
    if value is None:
        return value
    s = str(value)
    if s and s[0] in ('=', '+', '-', '@'):
        return "'" + s
    return value

@app.route('/api/export/estudiantes')
def export_estudiantes():
    conn = get_db()
    cur  = conn.execute("SELECT id,nombre,apellido_paterno,apellido_materno,matricula,semestre,COALESCE(grupo,'') AS grupo,correo,estado FROM estudiantes WHERE carrera=? ORDER BY CAST(semestre AS INTEGER), apellido_paterno", (CARRERA,))
    def generar():
        try:
            yield '\ufeff'
            yield _csv_line(['ID','Nombre','Ap. Paterno','Ap. Materno','Matrícula','Semestre','Grupo','Correo','Estado'])
            while True:
                lote = cur.fetchmany(100)
                if not lote:
                    break
                for r in lote:
                    yield _csv_line([
                        r['id'],
                        _csv_safe(r['nombre']),
                        _csv_safe(r['apellido_paterno']),
                        _csv_safe(r['apellido_materno']),
                        r['matricula'],
                        r['semestre'],
                        _csv_safe(r['grupo']),
                        _csv_safe(r['correo']),
                        r['estado'],
                    ])
        finally:
            conn.close()
    return Response(stream_with_context(generar()), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=estudiantes_itics.csv'})

@app.route('/api/export/registros')
def export_registros():
    conn = get_db(); s = schema(conn)
    fecha = request.args.get('fecha', datetime.now().strftime('%Y-%m-%d'))
    cur = conn.execute(f"""
        SELECT ra.id, ra.timestamp, ra.{s['col']} AS tipo, ra.uid, COALESCE(ra.mensaje,'') AS mensaje,
               COALESCE(e.nombre||' '||COALESCE(e.apellido_paterno,''),'DESCONOCIDO') AS nombre,
               COALESCE(e.matricula,'') AS matricula, COALESCE(CAST(e.semestre AS TEXT),'') AS semestre, COALESCE(e.grupo,'') AS grupo
        FROM registros_asistencia ra LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
        WHERE {s['ff']} AND (e.carrera=? OR e.id IS NULL) ORDER BY ra.timestamp
    """, (fecha, CARRERA))
    def generar():
        try:
            yield '\ufeff'
            yield _csv_line(['ID','Timestamp','Tipo','UID','Nombre','Matrícula','Semestre','Grupo','Mensaje'])
            while True:
                lote = cur.fetchmany(100)
                if not lote:
                    break
                for r in lote:
                    yield _csv_line([
                        r['id'], r['timestamp'], r['tipo'], r['uid'],
                        _csv_safe(r['nombre']),
                        r['matricula'], r['semestre'],
                        _csv_safe(r['grupo']),
                        r['mensaje'],
                    ])
        finally:
            conn.close()
    return Response(stream_with_context(generar()), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=registros_itics_{fecha}.csv'})

# ===== Migración =====
ALLOW_HTTP_MIGRATIONS = os.environ.get('ALLOW_HTTP_MIGRATIONS', '').strip().lower() in ('1', 'true')

@app.route('/api/migrate', methods=['POST'])
@api
def migrate():
    if not ALLOW_HTTP_MIGRATIONS:
        log.warning("Intento de acceso a /api/migrate con ALLOW_HTTP_MIGRATIONS deshabilitada.")
        abort(404)
    conn = get_db(); results = []
    try:
        for sql in ["ALTER TABLE estudiantes ADD COLUMN grupo TEXT DEFAULT ''",
                    "ALTER TABLE registros_asistencia ADD COLUMN fecha_dia TEXT",
                    """CREATE TABLE IF NOT EXISTS audit_log (
                           id        INTEGER PRIMARY KEY AUTOINCREMENT,
                           timestamp TEXT    NOT NULL,
                           ip        TEXT,
                           accion    TEXT    NOT NULL,
                           detalle   TEXT,
                           resultado TEXT    NOT NULL
                       )""",
                    "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp)"]:
            try:
                conn.execute(sql); results.append({'sql': sql, 'ok': True})
            except sqlite3.OperationalError as e:
                results.append({'sql': sql, 'ok': False, 'msg': str(e)})
        conn.commit()
        _schema_cache.clear()
    finally:
        conn.close()
    return jsonify({'success': True, 'results': results})

# ===== Main =====
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)