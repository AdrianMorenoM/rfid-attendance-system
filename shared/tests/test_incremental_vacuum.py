"""test_incremental_vacuum.py — pruebas unitarias para shared/run_incremental_vacuum.py.

Cubre:
  - Rama de DB inexistente (sys.exit(1))
  - Rama de auto_vacuum no INCREMENTAL (warning + return)
  - Camino feliz sin --pages
  - Camino feliz con --pages N
  - Bloque if __name__ == '__main__': main()

Ejecutar:
    cd ~/rfid-system
    ~/rfid-system/venv/bin/pytest shared/tests/test_incremental_vacuum.py -v
"""

import os
import sqlite3
import sys

import pytest

import run_incremental_vacuum as riv


class TestIncrementalVacuum:

    # ── helpers ────────────────────────────────────────────────────────────

    def _crear_db_con_auto_vacuum(self, path: str, modo: int) -> None:
        """Crea una BD en `path` con PRAGMA auto_vacuum = `modo`.

        modo=0 (NONE)    -> para probar la rama de "no configurado"
        modo=2 (INCREMENTAL) -> para probar el camino feliz
        """
        conn = sqlite3.connect(path)
        try:
            conn.execute(f"PRAGMA auto_vacuum={modo}")
            conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
            for i in range(200):
                conn.execute("INSERT INTO t (x) VALUES (?)", (i,))
            conn.commit()
            # Eliminar filas para generar páginas libres que vacuum pueda liberar
            conn.execute("DELETE FROM t")
            conn.commit()
        finally:
            conn.close()

    # ── tests ──────────────────────────────────────────────────────────────

    def test_db_inexistente_sale_con_codigo_1(self, tmp_path, monkeypatch):
        """Si DB no existe, main() loguea error y llama sys.exit(1)."""
        fake_db = str(tmp_path / "no_existe.db")
        monkeypatch.setattr(riv, "DB", fake_db)
        monkeypatch.setattr(sys, "argv", ["run_incremental_vacuum.py"])

        with pytest.raises(SystemExit) as exc_info:
            riv.main()

        assert exc_info.value.code == 1

    def test_auto_vacuum_no_incremental_retorna_sin_procesar(
        self, tmp_path, monkeypatch
    ):
        """Si auto_vacuum != 2 (INCREMENTAL), main() loguea warning y retorna."""
        fake_db = str(tmp_path / "no_incremental.db")
        self._crear_db_con_auto_vacuum(fake_db, modo=0)  # NONE por defecto

        monkeypatch.setattr(riv, "DB", fake_db)
        monkeypatch.setattr(sys, "argv", ["run_incremental_vacuum.py"])

        # No debe lanzar ni modificar el archivo
        size_before = os.path.getsize(fake_db)
        riv.main()
        size_after = os.path.getsize(fake_db)

        assert size_after == size_before

    def test_vacuum_exitoso_sin_pages(self, tmp_path, monkeypatch):
        """Camino feliz: auto_vacuum=INCREMENTAL, sin --pages."""
        fake_db = str(tmp_path / "vacuum.db")
        self._crear_db_con_auto_vacuum(fake_db, modo=2)

        monkeypatch.setattr(riv, "DB", fake_db)
        monkeypatch.setattr(sys, "argv", ["run_incremental_vacuum.py"])

        riv.main()

        # La BD debe seguir íntegra y accesible
        conn = sqlite3.connect(fake_db)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
        finally:
            conn.close()

        assert integrity == "ok"
        # incremental_vacuum sin límite debe liberar todas las páginas
        assert freelist == 0

    def test_vacuum_exitoso_con_pages(self, tmp_path, monkeypatch):
        """Camino feliz con --pages N: ejecuta PRAGMA incremental_vacuum(N)."""
        fake_db = str(tmp_path / "vacuum_pages.db")
        self._crear_db_con_auto_vacuum(fake_db, modo=2)

        monkeypatch.setattr(riv, "DB", fake_db)
        monkeypatch.setattr(
            sys, "argv",
            ["run_incremental_vacuum.py", "--pages", "5"],
        )

        riv.main()

        conn = sqlite3.connect(fake_db)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()

        assert integrity == "ok"

    def test_main_block_ejecuta_main(self, tmp_path, monkeypatch):
        """Reejecuta el módulo como __main__ para cubrir el bloque.

        Se interceptan:
        - logging.FileHandler -> NullHandler (no ensucia shared/incremental_vacuum.log)
        - sqlite3.connect       -> dirige a una BD en tmp_path
        - os.path.exists/getsize -> responde para la ruta de DB calculada por el módulo
        - sys.argv               -> limpio, para que argparse no reciba args de pytest
        """
        import importlib.util
        import logging as _logging

        # 1) Silenciar FileHandler durante la reimportación
        monkeypatch.setattr(
            _logging, "FileHandler",
            lambda *a, **kw: _logging.NullHandler(),
        )

        # 2) BD real en tmp_path con auto_vacuum=INCREMENTAL
        fake_db = str(tmp_path / "main_block.db")
        setup = sqlite3.connect(fake_db)
        setup.execute("PRAGMA auto_vacuum=2")
        setup.execute("CREATE TABLE t (x INTEGER)")
        setup.commit()
        setup.close()

        # 3) Redirigir sqlite3.connect a fake_db
        real_connect = sqlite3.connect
        monkeypatch.setattr(
            sqlite3, "connect",
            lambda path, *a, **kw: real_connect(fake_db, *a, **kw),
        )

        # 4) os.path.exists/getsize: responder sólo para rutas terminadas en 'rfid.db'
        real_exists = os.path.exists
        real_getsize = os.path.getsize
        monkeypatch.setattr(
            os.path, "exists",
            lambda p: True if str(p).endswith("rfid.db") else real_exists(p),
        )
        monkeypatch.setattr(
            os.path, "getsize",
            lambda p: 1024 if str(p).endswith("rfid.db") else real_getsize(p),
        )

        # 5) argv limpio
        monkeypatch.setattr(sys, "argv", ["run_incremental_vacuum.py"])

        # 6) Reejecutar el módulo como __main__
        spec = importlib.util.spec_from_file_location("__main__", riv.__file__)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Verificación colateral: la BD en tmp_path quedó íntegra
        conn = real_connect(fake_db)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        assert integrity == "ok"
