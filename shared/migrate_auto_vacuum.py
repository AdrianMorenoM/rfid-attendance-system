#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migración ÚNICA: activa auto_vacuum=INCREMENTAL en una base de datos
que ya tiene tablas y datos.

auto_vacuum solo puede fijarse sobre una base vacía; en una base con
tablas hace falta VACUUM para reescribir el archivo completo con el
nuevo modo aplicado. Este script:
  1. Hace un respaldo de seguridad antes de tocar nada.
  2. Fija PRAGMA auto_vacuum=INCREMENTAL.
  3. Ejecuta VACUUM (reescribe todo el archivo, puede tardar según el tamaño).

Ejecutar UNA sola vez, con los servicios (crud/dashboard/reader) DETENIDOS
para evitar que otro proceso escriba mientras VACUUM corre:

    sudo systemctl stop rfid-crud.service rfid-dashboard.service rfid-reader.service
    cd ~/rfid-system
    ./venv/bin/python shared/migrate_auto_vacuum.py
    sudo systemctl start rfid-crud.service rfid-dashboard.service rfid-reader.service
"""

import sqlite3, os, shutil, sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB       = os.path.join(BASE_DIR, "rfid.db")


def main():
    if not os.path.exists(DB):
        sys.exit(f"ERROR: no se encontró la base de datos en {DB}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DB}.pre_autovacuum_{ts}.bak"
    print(f"→ Respaldando {DB} → {backup_path}")
    shutil.copy2(DB, backup_path)

    conn = sqlite3.connect(DB, timeout=30.0)
    try:
        current = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        # 0 = NONE, 1 = FULL, 2 = INCREMENTAL
        if current == 2:
            print("✅ auto_vacuum ya está en INCREMENTAL. Nada que hacer.")
            return

        print("→ Fijando PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")

        print("→ Ejecutando VACUUM (puede tardar unos segundos/minutos)...")
        conn.execute("VACUUM")
        conn.commit()

        new_val = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if new_val == 2:
            print("✅ auto_vacuum=INCREMENTAL activado correctamente.")
            print(f"   Respaldo previo conservado en: {backup_path}")
        else:
            sys.exit(f"⚠️  auto_vacuum quedó en valor inesperado: {new_val}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()