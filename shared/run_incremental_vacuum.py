#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejecuta PRAGMA incremental_vacuum sobre rfid.db.
Pensado para ser llamado periódicamente por un systemd timer (o cron).

Uso manual:
    ./venv/bin/python shared/run_incremental_vacuum.py
    ./venv/bin/python shared/run_incremental_vacuum.py --pages 500   # limitar páginas por corrida
"""

import sqlite3, os, sys, argparse, logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB       = os.path.join(BASE_DIR, "rfid.db")
LOG_FILE = os.path.join(BASE_DIR, "incremental_vacuum.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE)],
)
log = logging.getLogger('incremental-vacuum')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=None,
                         help='Máximo de páginas a liberar en esta corrida (por defecto: todas las disponibles)')
    args = parser.parse_args()

    if not os.path.exists(DB):
        log.error(f"No se encontró la base de datos en {DB}")
        sys.exit(1)

    size_before = os.path.getsize(DB)
    conn = sqlite3.connect(DB, timeout=30.0)
    try:
        auto_vacuum = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if auto_vacuum != 2:
            log.warning(
                "auto_vacuum no está en INCREMENTAL (valor actual=%s). "
                "La base de datos debe configurarse con auto_vacuum=INCREMENTAL.", auto_vacuum
            )
            return

        freelist_before = conn.execute("PRAGMA freelist_count").fetchone()[0]
        if args.pages:
            conn.execute("PRAGMA incremental_vacuum(?)", (args.pages,))
        else:
            conn.execute("PRAGMA incremental_vacuum")
        conn.commit()
        freelist_after = conn.execute("PRAGMA freelist_count").fetchone()[0]
    finally:
        conn.close()

    size_after = os.path.getsize(DB)
    freed_mb = round((size_before - size_after) / (1024 * 1024), 3)
    log.info(
        "incremental_vacuum OK — páginas libres: %d → %d | tamaño: %.3f MB → %.3f MB (liberado: %.3f MB)",
        freelist_before, freelist_after,
        size_before / (1024 * 1024), size_after / (1024 * 1024), freed_mb
    )


if __name__ == "__main__":
    main()