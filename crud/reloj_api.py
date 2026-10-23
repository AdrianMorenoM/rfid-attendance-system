"""Fijar la hora desde el panel cuando el reloj no esta sincronizado.

El CRUD no tiene privilegios (NoNewPrivileges): deja una peticion en el buzon
/run/rfid-shared y una unidad de root (rfid-fijar-hora.path) la valida y aplica.
"""
import os
import tempfile
import threading
import time

from flask import jsonify, request

DIR = '/run/rfid-shared'
DIR_ROOT = '/run/rfid-reloj'
SYNC_MARCA = '/run/systemd/timesync/synchronized'
MANUAL_MARCA = os.path.join(DIR_ROOT, 'reloj_manual_ok')
MIN_EPOCH = 1767225600   # 2026-01-01 UTC
MAX_EPOCH = 2082758400   # 2036-01-01 UTC
ESPERA_S = 6.0
ENFRIAMIENTO_S = 5.0

_lock = threading.Lock()
_ultimo = 0.0


def estado():
    sync = os.path.exists(SYNC_MARCA)
    manual = os.path.exists(MANUAL_MARCA)
    return {'sincronizado': sync, 'manual': manual,
            'confiable': sync or manual, 'hora_servidor': int(time.time())}


def _firma(path):
    try:
        st = os.stat(path)
        return (st.st_ino, st.st_mtime_ns)
    except OSError:
        return None


def _esperar_respuesta(res_path, firma_previa):
    limite = time.monotonic() + ESPERA_S
    while time.monotonic() < limite:
        firma = _firma(res_path)
        if firma is not None and firma != firma_previa:
            try:
                with open(res_path, encoding='utf-8', errors='replace') as fh:
                    texto = fh.read(300).strip()
            except OSError:
                time.sleep(0.2)
                continue
            codigo, _, msg = texto.partition(' ')
            return (int(codigo) if codigo.isdigit() else 99), msg
        time.sleep(0.2)
    return None, ''


def registrar(app, require_xhr_header, api, auditar):
    @app.route('/api/hardware/system/clock-status')
    @api
    def hardware_clock_status():
        return jsonify({'success': True, **estado()})

    @app.route('/api/hardware/system/set-time', methods=['POST'])
    @require_xhr_header
    @api
    def hardware_set_time():
        global _ultimo
        data = request.get_json(force=True, silent=True) or {}
        if not data.get('confirm'):
            return jsonify({'success': False, 'error': 'Confirmación requerida'}), 400
        epoch = data.get('epoch')
        if isinstance(epoch, bool) or not isinstance(epoch, int) \
                or not (MIN_EPOCH <= epoch <= MAX_EPOCH):
            return jsonify({'success': False, 'error': 'Hora inválida o fuera de rango'}), 400
        if os.path.exists(SYNC_MARCA):
            return jsonify({'success': False,
                            'error': 'El reloj ya está sincronizado con NTP'}), 409
        if not _lock.acquire(blocking=False):
            return jsonify({'success': False, 'error': 'Operación en curso'}), 429
        try:
            if time.monotonic() - _ultimo < ENFRIAMIENTO_S:
                return jsonify({'success': False, 'error': 'Espera unos segundos'}), 429
            _ultimo = time.monotonic()
            req = os.path.join(DIR, 'fijar_hora.req')
            res = os.path.join(DIR_ROOT, 'fijar_hora.res')
            previa = _firma(res)
            fd, tmp = tempfile.mkstemp(dir=DIR, prefix='.req.')
            with os.fdopen(fd, 'w') as fh:
                fh.write(str(epoch))
            os.replace(tmp, req)
            codigo, msg = _esperar_respuesta(res, previa)
        finally:
            _lock.release()
        if codigo is None:
            try:
                os.remove(req)
            except OSError:
                pass
            auditar('hardware_system_set_time', f'epoch={epoch}', 'error: sin respuesta')
            return jsonify({'success': False,
                            'error': 'Sin respuesta del servicio de root '
                                     '(¿activo rfid-fijar-hora.path?)'}), 504
        ok = codigo == 0
        auditar('hardware_system_set_time', f'epoch={epoch}',
                'éxito' if ok else f'error {codigo}')
        if ok:
            return jsonify({'success': True, **estado()})
        return jsonify({'success': False, 'error': msg or 'Error al fijar la hora'}), \
            (409 if codigo == 2 else 400)
