"""test_init_db.py — pruebas unitarias para shared/init_db.py.

Cubre:
  - Creación del esquema (tablas e índices)
  - Idempotencia de init()
  - Bloque if __name__ == '__main__': init()

Ejecutar:
    cd ~/rfid-system
    ~/rfid-system/venv/bin/pytest shared/tests/test_init_db.py -v
"""

import os
import sqlite3

import pytest

import init_db


TABLAS_ESPERADAS = {
    'estudiantes',
    'tarjetas',
    'registros_asistencia',
    'auth_fail_log',
}

INDICES_ESPERADOS = {
    'idx_reg_fecha',
    'idx_reg_uid',
    'idx_reg_evento',
    'idx_tarj_uid',
    'idx_est_estado',
    'idx_est_semestre',
    'idx_reg_fecha_evento',
    'idx_reg_est_evento',
    'idx_tarj_est_activa',
    'idx_auth_fail_ip_ts',
}


class TestInitDb:

    def test_init_crea_todas_las_tablas(self, tmp_path, monkeypatch):
        """init() crea las 4 tablas definidas en SQL."""
        fake_db = str(tmp_path / 'rfid_test.db')
        monkeypatch.setattr(init_db, 'DB', fake_db)

        init_db.init()

        conn = sqlite3.connect(fake_db)
        try:
            tablas = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()

        assert TABLAS_ESPERADAS.issubset(tablas)

    def test_init_crea_todos_los_indices(self, tmp_path, monkeypatch):
        """init() crea los 10 índices definidos en SQL."""
        fake_db = str(tmp_path / 'rfid_test.db')
        monkeypatch.setattr(init_db, 'DB', fake_db)

        init_db.init()

        conn = sqlite3.connect(fake_db)
        try:
            indices = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        finally:
            conn.close()

        assert INDICES_ESPERADOS.issubset(indices)

    def test_init_es_idempotente(self, tmp_path, monkeypatch):
        """Llamar init() dos veces no debe fallar (CREATE ... IF NOT EXISTS)."""
        fake_db = str(tmp_path / 'rfid_test.db')
        monkeypatch.setattr(init_db, 'DB', fake_db)

        init_db.init()
        init_db.init()

        conn = sqlite3.connect(fake_db)
        try:
            tablas = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()

        assert TABLAS_ESPERADAS.issubset(tablas)

    def test_main_block_ejecuta_init(self, tmp_path, monkeypatch):
        """Cubre el bloque if __name__ == '__main__': init()."""
        import importlib.util

        fake_db = str(tmp_path / 'rfid_main.db')
        real_connect = sqlite3.connect

        def fake_connect(path, *args, **kwargs):
            return real_connect(fake_db, *args, **kwargs)

        monkeypatch.setattr(sqlite3, 'connect', fake_connect)

        spec = importlib.util.spec_from_file_location(
            '__main__', init_db.__file__
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert os.path.exists(fake_db)

        conn = real_connect(fake_db)
        try:
            tablas = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()

        assert TABLAS_ESPERADAS.issubset(tablas)
