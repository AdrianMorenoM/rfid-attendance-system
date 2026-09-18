#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RFID Dashboard Service - Puerto 5000"""

from flask import Flask, render_template, jsonify, send_from_directory, request, Response
import sqlite3, os, traceback, hmac
from datetime import datetime
from functools import wraps

from werkzeug.middleware.proxy_fix import ProxyFix

# Carga .env (solo desarrollo)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DB        = os.path.join(BASE_DIR, "..", "shared", "rfid.db")
FOTOS_DIR = os.path.join(BASE_DIR, "..", "crud", "static", "fotos")

# ===== Auth =====
def _check_credentials(username, password):
    user_ok = hmac.compare_digest((username or "").encode(), os.environ.get('ADMIN_USER', '').encode())
    pass_ok = hmac.compare_digest((password or "").encode(), os.environ.get('ADMIN_PASSWORD', '').encode())
    return user_ok and pass_ok

def require_basic_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_credentials(auth.username, auth.password):
            return Response('Autenticación requerida.', 401,
                            {'WWW-Authenticate': 'Basic realm="RFID Dashboard"'})
        return f(*args, **kwargs)
    return wrapper

# ===== Rutas =====
@app.route('/fotos/<path:filename>')
def serve_foto(filename):
    return send_from_directory(FOTOS_DIR, filename)

def get_db():
    conn = sqlite3.connect(DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

_schema = {}
def schema(conn):
    if _schema: return _schema
    cols = {r[1] for r in conn.execute("PRAGMA table_info(registros_asistencia)").fetchall()}
    _schema['col'] = 'tipo_evento' if 'tipo_evento' in cols else 'estado' if 'estado' in cols else 'tipo_evento'
    _schema['ff']  = "fecha_dia = ?" if 'fecha_dia' in cols else "strftime('%Y-%m-%d',timestamp) = ?"
    return _schema

def norm(v):
    if not v: return 'rebote'
    v = v.lower()
    if v in ('aceptado','entrada'): return 'aceptado'
    if v == 'ya_escaneado':         return 'ya_escaneado'
    return 'rebote'

def normalizar_foto(foto):
    if not foto: return None
    if foto.startswith('http'): return foto
    filename = foto.replace('\\', '/').rstrip('/').split('/')[-1]
    return f'/fotos/{filename}'

@app.route('/')
@app.route('/dashboard')
@require_basic_auth
def index():
    return render_template('dashboard.html')

@app.route('/api/estado')
@require_basic_auth
def api_estado():
    try:
        conn = get_db()
        s    = schema(conn)
        col  = s['col']
        ff   = s['ff']
        hoy  = datetime.now().strftime('%Y-%m-%d')

        def cnt(*vals):
            ph = ','.join('?'*len(vals))
            return conn.execute(
                f"SELECT COUNT(*) as t FROM registros_asistencia WHERE {ff} AND {col} IN ({ph})",
                (hoy,)+vals).fetchone()['t']

        stats = {
            'entradas_hoy':     cnt('aceptado','entrada'),
            'ya_escaneados':    cnt('ya_escaneado'),
            'rebotes_hoy':      cnt('rebote','desconocido'),
            'tarjetas_activas': conn.execute("SELECT COUNT(*) as t FROM tarjetas WHERE activa=1").fetchone()['t'],
        }

        reps = conn.execute(f"""
            SELECT ra.uid, COUNT(*) as veces,
                   COALESCE(e.nombre||' '||COALESCE(e.apellido_paterno,''),'') as nombre
            FROM registros_asistencia ra
            LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            WHERE {ff} AND ra.{col} IN ('aceptado','entrada')
            GROUP BY ra.uid HAVING COUNT(*)>1 ORDER BY veces DESC LIMIT 10
        """, (hoy,)).fetchall()

        evs = conn.execute(f"""
            SELECT ra.id, ra.uid, ra.timestamp, ra.{col} as tr,
                   COALESCE(ra.mensaje,'') as mensaje,
                   e.nombre, e.apellido_paterno, e.matricula, e.carrera, e.foto
            FROM registros_asistencia ra
            LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            WHERE {ff}
            ORDER BY ra.timestamp DESC, ra.id DESC
            LIMIT 30
        """, (hoy,)).fetchall()

        eventos = []
        for r in evs:
            r = dict(r)
            nombre = f"{r.get('nombre') or ''} {r.get('apellido_paterno') or ''}".strip() or 'DESCONOCIDO'
            eventos.append({
                'id':        r['id'],
                'uid':       r['uid'],
                'timestamp': r['timestamp'],
                'estado':    norm(r['tr']),
                'mensaje':   r['mensaje'],
                'nombre':    nombre,
                'matricula': r.get('matricula') or 'N/A',
                'carrera':   r.get('carrera')   or 'N/A',
                'foto':      normalizar_foto(r.get('foto')),
            })

        horas_raw = conn.execute(f"""
            SELECT CAST(strftime('%H', timestamp) AS INTEGER) as h, COUNT(*) as cnt
            FROM registros_asistencia
            WHERE {ff} AND {col} IN ('aceptado','entrada')
            GROUP BY h
        """, (hoy,)).fetchall()
        horas_map = {r['h']: r['cnt'] for r in horas_raw}
        hourly = [horas_map.get(h, 0) for h in range(24)]

        try:
            import subprocess
            res = subprocess.run(['systemctl','is-active','rfid-reader'],
                                 capture_output=True, text=True, timeout=2)
            reader_ok = res.stdout.strip() == 'active'
        except Exception:
            reader_ok = False

        conn.close()
        return jsonify({
            'success': True, 'stats': stats,
            'uid_repetidos': [dict(r) for r in reps],
            'eventos': eventos,
            'hourly': hourly,
            'reader_ok': reader_ok,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/api/ultimo-evento')
@require_basic_auth
def ultimo_evento():
    try:
        conn = get_db()
        s    = schema(conn)
        hoy  = datetime.now().strftime('%Y-%m-%d')
        row  = conn.execute(f"""
            SELECT ra.id,ra.uid,ra.timestamp,ra.{s['col']} as tr,
                   COALESCE(ra.mensaje,'') as mensaje,
                   e.nombre,e.apellido_paterno,e.matricula,e.carrera,e.foto
            FROM registros_asistencia ra
            LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            WHERE {s['ff']} ORDER BY ra.timestamp DESC LIMIT 1
        """, (hoy,)).fetchone()
        conn.close()
        if not row:
            return jsonify({'success': True, 'evento': None})
        r = dict(row)
        nombre = f"{r.get('nombre') or ''} {r.get('apellido_paterno') or ''}".strip() or 'DESCONOCIDO'
        return jsonify({'success': True, 'evento': {
            'id':        r['id'],
            'uid':       r['uid'],
            'timestamp': r['timestamp'],
            'estado':    norm(r['tr']),
            'mensaje':   r['mensaje'],
            'nombre':    nombre,
            'matricula': r.get('matricula') or 'N/A',
            'carrera':   r.get('carrera')   or 'N/A',
            'foto':      normalizar_foto(r.get('foto')),
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
