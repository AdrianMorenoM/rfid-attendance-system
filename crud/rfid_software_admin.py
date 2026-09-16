#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Administracion de servicios systemd y base de datos SQLite."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sqlite3
import subprocess
from datetime import datetime
from typing import Any

# SSH / ejecucion remota — configurar con variables de entorno en produccion.
SSH_HOST     = os.environ.get('RFID_SSH_HOST', '127.0.0.1')
SSH_USER     = os.environ.get('RFID_SSH_USER', 'admin')
SSH_PASSWORD = os.environ.get('RFID_SSH_PASSWORD')  # sin default — obligatorio si se usa SSH
SSH_PORT     = int(os.environ.get('RFID_SSH_PORT', '22'))
USE_SSH      = os.environ.get('RFID_USE_SSH', 'auto').lower()
LOCAL_HOSTS  = frozenset({'127.0.0.1', 'localhost', '::1'})


def _should_use_ssh() -> bool:
    if USE_SSH in ('0', 'false', 'no', 'never'):
        return False
    if USE_SSH in ('1', 'true', 'yes', 'always'):
        return True
    return SSH_HOST.strip().lower() not in LOCAL_HOSTS


if _should_use_ssh() and not SSH_PASSWORD:
    raise RuntimeError(
        "RFID_SSH_PASSWORD no está definida. Configúrala como variable de "
        "entorno antes de usar el modo SSH remoto."
    )

def _run_local(cmd: str, timeout: int = 30) -> dict:
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {
            'success': res.returncode == 0,
            'returncode': res.returncode,
            'stdout': (res.stdout or '').strip(),
            'stderr': (res.stderr or '').strip(),
            'mode': 'local',
        }
    except Exception as exc:
        return {'success': False, 'error': str(exc), 'mode': 'local'}


def _run_ssh(cmd: str, timeout: int = 30) -> dict:
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASSWORD,
            timeout=15, allow_agent=False, look_for_keys=False,
        )
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        code = stdout.channel.recv_exit_status()
        client.close()
        return {'success': code == 0, 'returncode': code, 'stdout': out, 'stderr': err, 'mode': 'ssh'}
    except ImportError:
        pass
    except Exception as exc:
        return {'success': False, 'error': str(exc), 'mode': 'ssh'}
    try:
        wrapped = [
            'sshpass', '-p', SSH_PASSWORD, 'ssh',
            '-o', 'StrictHostKeyChecking=no', '-p', str(SSH_PORT),
            f'{SSH_USER}@{SSH_HOST}', cmd,
        ]
        res = subprocess.run(wrapped, capture_output=True, text=True, timeout=timeout)
        return {
            'success': res.returncode == 0,
            'stdout': (res.stdout or '').strip(),
            'stderr': (res.stderr or '').strip(),
            'mode': 'ssh-sshpass',
        }
    except Exception as exc:
        return {'success': False, 'error': str(exc), 'mode': 'ssh'}


def run_shell(cmd: str, timeout: int = 30) -> dict:
    if not _should_use_ssh():
        return _run_local(cmd, timeout=timeout)
    return _run_ssh(cmd, timeout=timeout)


def run_systemctl(action: str, service: str, timeout: int = 30) -> dict:
    q = shlex.quote(service)
    result = run_shell(f'systemctl {shlex.quote(action)} {q}', timeout=timeout)
    if not result.get('success'):
        sudo = run_shell(f'sudo -n systemctl {shlex.quote(action)} {q}', timeout=timeout)
        if sudo.get('success') or sudo.get('stdout') or sudo.get('stderr'):
            return sudo
    return result


def service_active(service: str) -> bool:
    return run_shell(f'systemctl is-active {shlex.quote(service)}').get('stdout', '').strip() == 'active'


def service_enabled(service: str) -> bool:
    return run_shell(f'systemctl is-enabled {shlex.quote(service)}').get('stdout', '').strip() in ('enabled', 'static')


def service_logs(service: str, lines: int = 50) -> dict:
    n = max(10, min(int(lines), 500))
    return run_shell(f'journalctl -u {shlex.quote(service)} -n {n} --no-pager', timeout=30)


RFID_SERVICES = (
    'rfid-crud.service',
    'rfid-dashboard.service',
    'rfid-reader.service',
)

ALLOWED_ACTIONS = frozenset({'start', 'stop', 'restart', 'enable', 'disable', 'status'})
BACKUP_PREFIX = 'rfid_backup_'
BACKUP_SUFFIX = '.db'
SAFE_BACKUP_RE = re.compile(r'^rfid_backup_[0-9]{8}_[0-9]{6}\.db$')


class ServiceManager:
    def list_services(self) -> list[dict]:
        items = []
        for name in RFID_SERVICES:
            active = service_active(name)
            enabled = service_enabled(name)
            active_r = run_systemctl('is-active', name)
            enabled_r = run_systemctl('is-enabled', name)
            items.append({
                'name': name,
                'active': active,
                'enabled': enabled,
                'active_text': active_r.get('stdout') or ('active' if active else 'inactive'),
                'enabled_text': enabled_r.get('stdout') or ('enabled' if enabled else 'disabled'),
            })
        return items

    def action(self, service_name: str, action: str) -> dict:
        if service_name not in RFID_SERVICES:
            return {'success': False, 'error': 'Servicio no permitido'}
        if action not in ALLOWED_ACTIONS:
            return {'success': False, 'error': 'Accion no permitida'}
        result = run_systemctl(action, service_name)
        ok = result.get('success', False)
        if action in ('enable', 'disable') and not ok:
            err = (result.get('stderr') or result.get('error') or '').lower()
            if 'created symlink' in err or 'removed' in err:
                ok = True
        if not ok and result.get('stderr'):
            low = result['stderr'].lower()
            if 'password' in low or 'permission' in low or 'access denied' in low:
                return {
                    'success': False,
                    'error': 'Permiso denegado para systemctl (configure sudo NOPASSWD o SSH admin)',
                    'result': result,
                }
        return {'success': ok, 'result': result}

    def logs(self, service_name: str, lines: int = 50) -> dict:
        if service_name not in RFID_SERVICES:
            return {'success': False, 'error': 'Servicio no permitido'}
        result = service_logs(service_name, lines)
        return {
            'success': True,
            'service': service_name,
            'lines': lines,
            'log': result.get('stdout') or result.get('stderr') or '',
            'result': result,
        }


class DatabaseManager:
    def __init__(self, db_path: str, backup_dir: str, carrera_default: str = "ITIC's"):
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.carrera_default = carrera_default
        os.makedirs(self.backup_dir, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def status(self) -> dict:
        size_mb = None
        if os.path.exists(self.db_path):
            size_mb = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)
        conn = self._connect()
        try:
            counts = {
                'estudiantes': conn.execute('SELECT COUNT(*) AS t FROM estudiantes').fetchone()['t'],
                'tarjetas': conn.execute('SELECT COUNT(*) AS t FROM tarjetas').fetchone()['t'],
                'registros': conn.execute('SELECT COUNT(*) AS t FROM registros_asistencia').fetchone()['t'],
            }
        finally:
            conn.close()
        backups = self.list_backups()
        return {
            'db_path': self.db_path,
            'db_size_mb': size_mb,
            'counts': counts,
            'backups_count': len(backups),
        }

    def list_backups(self) -> list[dict]:
        items = []
        if not os.path.isdir(self.backup_dir):
            return items
        for name in sorted(os.listdir(self.backup_dir), reverse=True):
            if not SAFE_BACKUP_RE.match(name):
                continue
            path = os.path.join(self.backup_dir, name)
            if not os.path.isfile(path):
                continue
            items.append({
                'filename': name,
                'size_mb': round(os.path.getsize(path) / (1024 * 1024), 2),
                'created_at': datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
            })
        return items

    def _backup_path(self, filename: str) -> str:
        if not SAFE_BACKUP_RE.match(filename):
            raise ValueError('Nombre de respaldo no valido')
        return os.path.join(self.backup_dir, filename)

    def create_backup(self) -> dict:
        if not os.path.exists(self.db_path):
            return {'success': False, 'error': 'Base de datos no encontrada'}
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{BACKUP_PREFIX}{ts}{BACKUP_SUFFIX}'
        dest = os.path.join(self.backup_dir, filename)
        src = sqlite3.connect(self.db_path)
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return {
            'success': True,
            'filename': filename,
            'size_mb': round(os.path.getsize(dest) / (1024 * 1024), 2),
            'mensaje': f'Respaldo creado: {filename}',
        }

    def restore(self, filename: str) -> dict:
        src_path = self._backup_path(filename)
        if not os.path.isfile(src_path):
            return {'success': False, 'error': 'Respaldo no encontrado'}
        pre = self.create_backup()
        if not pre.get('success'):
            return {'success': False, 'error': 'No se pudo crear respaldo de seguridad previo a restaurar'}
        tmp = self.db_path + '.restore_tmp'
        shutil.copy2(src_path, tmp)
        os.replace(tmp, self.db_path)
        return {
            'success': True,
            'mensaje': f'Base restaurada desde {filename}',
            'safety_backup': pre.get('filename'),
        }

    def delete_backup(self, filename: str) -> dict:
        path = self._backup_path(filename)
        if not os.path.isfile(path):
            return {'success': False, 'error': 'Respaldo no encontrado'}
        os.remove(path)
        return {'success': True, 'mensaje': f'Respaldo {filename} eliminado'}

    def _purge_filters(self, data: dict) -> tuple[str, list, dict]:
        target = (data.get('target') or 'registros').strip().lower()
        params: list[Any] = []
        meta: dict = {'target': target, 'filters': {}}

        if target == 'registros':
            clauses = ['1=1']
            join = 'FROM registros_asistencia ra LEFT JOIN estudiantes e ON ra.id_estudiante = e.id'

            if data.get('fecha_desde'):
                clauses.append('datetime(ra.timestamp) >= datetime(?)')
                params.append(data['fecha_desde'] + (' 00:00:00' if len(data['fecha_desde']) == 10 else ''))
                meta['filters']['fecha_desde'] = data['fecha_desde']
            if data.get('fecha_hasta'):
                clauses.append('datetime(ra.timestamp) <= datetime(?)')
                params.append(data['fecha_hasta'] + (' 23:59:59' if len(data['fecha_hasta']) == 10 else ''))
                meta['filters']['fecha_hasta'] = data['fecha_hasta']
            if data.get('carrera'):
                clauses.append('e.carrera = ?')
                params.append(data['carrera'])
                meta['filters']['carrera'] = data['carrera']
            if data.get('semestre'):
                clauses.append('e.semestre = ?')
                params.append(str(data['semestre']))
                meta['filters']['semestre'] = data['semestre']
            if data.get('grupo'):
                clauses.append("UPPER(COALESCE(e.grupo,'')) = ?")
                params.append(str(data['grupo']).upper())
                meta['filters']['grupo'] = data['grupo']
            if data.get('estudiante_id'):
                clauses.append('ra.id_estudiante = ?')
                params.append(int(data['estudiante_id']))
                meta['filters']['estudiante_id'] = data['estudiante_id']
            if data.get('matricula'):
                clauses.append('e.matricula = ?')
                params.append(str(data['matricula']).strip())
                meta['filters']['matricula'] = data['matricula']

            where = ' AND '.join(clauses)
            count_sql = f'SELECT COUNT(*) AS t {join} WHERE {where}'
            delete_sql = f'DELETE FROM registros_asistencia WHERE id IN (SELECT ra.id {join} WHERE {where})'
            meta['count_sql'] = count_sql
            return delete_sql, params, meta

        if target == 'estudiantes':
            clauses = ['1=1']
            if data.get('carrera'):
                clauses.append('carrera = ?')
                params.append(data['carrera'])
            else:
                clauses.append('carrera = ?')
                params.append(self.carrera_default)
            if data.get('semestre'):
                clauses.append('semestre = ?')
                params.append(str(data['semestre']))
            if data.get('grupo'):
                clauses.append("UPPER(COALESCE(grupo,'')) = ?")
                params.append(str(data['grupo']).upper())
            if data.get('estudiante_id'):
                clauses.append('id = ?')
                params.append(int(data['estudiante_id']))
            if data.get('matricula'):
                clauses.append('matricula = ?')
                params.append(str(data['matricula']).strip())
            where = ' AND '.join(clauses)
            count_sql = f'SELECT COUNT(*) AS t FROM estudiantes WHERE {where}'
            delete_sql = f'DELETE FROM estudiantes WHERE {where}'
            meta['count_sql'] = count_sql
            meta['cascade'] = True
            return delete_sql, params, meta

        if target == 'tarjetas':
            clauses = ['1=1']
            join = 'FROM tarjetas t LEFT JOIN estudiantes e ON t.id_estudiante = e.id'
            if data.get('carrera'):
                clauses.append('(e.carrera = ? OR e.id IS NULL)')
                params.append(data['carrera'])
            if data.get('semestre'):
                clauses.append('e.semestre = ?')
                params.append(str(data['semestre']))
            if data.get('grupo'):
                clauses.append("UPPER(COALESCE(e.grupo,'')) = ?")
                params.append(str(data['grupo']).upper())
            if data.get('estudiante_id'):
                clauses.append('t.id_estudiante = ?')
                params.append(int(data['estudiante_id']))
            if data.get('matricula'):
                clauses.append('e.matricula = ?')
                params.append(str(data['matricula']).strip())
            where = ' AND '.join(clauses)
            delete_sql = f'DELETE FROM tarjetas WHERE id IN (SELECT t.id {join} WHERE {where})'
            meta['count_sql'] = f'SELECT COUNT(*) AS t {join} WHERE {where}'
            return delete_sql, params, meta

        raise ValueError('target no valido (registros, estudiantes, tarjetas)')

    def purge_preview(self, data: dict) -> dict:
        try:
            _delete_sql, params, meta = self._purge_filters(data)
        except ValueError as e:
            return {'success': False, 'error': str(e)}

        conn = self._connect()
        try:
            count = conn.execute(meta['count_sql'], params).fetchone()['t']
            return {'success': True, 'count': count, 'meta': meta}
        finally:
            conn.close()

    def purge(self, data: dict) -> dict:
        if not data.get('confirm'):
            return {'success': False, 'error': 'Confirmacion requerida'}
        preview = self.purge_preview(data)
        if not preview.get('success'):
            return preview
        count = preview.get('count', 0)
        if count == 0:
            return {'success': True, 'deleted': 0, 'mensaje': 'Nada que eliminar con esos filtros'}

        delete_sql, params, meta = self._purge_filters(data)
        conn = self._connect()
        try:
            if meta.get('cascade') and meta['target'] == 'estudiantes':
                sub = meta['count_sql'].replace('SELECT COUNT(*) AS t FROM estudiantes', 'SELECT id FROM estudiantes')
                conn.execute(f'DELETE FROM registros_asistencia WHERE id_estudiante IN ({sub})', params)
                conn.execute(f'DELETE FROM tarjetas WHERE id_estudiante IN ({sub})', params)
            cur = conn.execute(delete_sql, params)
            conn.commit()
            return {
                'success': True,
                'deleted': cur.rowcount,
                'meta': meta,
                'mensaje': f'{cur.rowcount} registro(s) eliminados',
            }
        finally:
            conn.close()
