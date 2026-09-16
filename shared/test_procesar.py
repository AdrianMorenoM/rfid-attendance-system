#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_procesar.py — Pruebas funcionales aisladas de la lógica del lector RFID.

No toca rfid.db — cada prueba crea su propia base temporal en memoria.
Corre con: ./venv/bin/python -m pytest shared/test_procesar.py -v

Cubre el diagrama de decisión §4 del README:
  UID desconocido → rechazado
  Tarjeta inactiva → rechazado
  Estudiante inactivo → rechazado
  Primer escaneo del día → aceptado
  Reincidencia en el mismo día → rechazado (ya registrado hoy)
  Regresión: inyección SQL en UID → no rompe la base
  Regresión: UID con espacios/mayúsculas → se normaliza correctamente
"""

import sqlite3
import tempfile
import os
import pytest
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Infraestructura: base de datos temporal y función procesar_uid
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS estudiantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT    NOT NULL,
    activo      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tarjetas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT    NOT NULL UNIQUE,
    estudiante_id   INTEGER NOT NULL REFERENCES estudiantes(id),
    activa          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS registros (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    estudiante_id   INTEGER NOT NULL REFERENCES estudiantes(id),
    tarjeta_uid     TEXT    NOT NULL,
    timestamp       TEXT    NOT NULL,
    fecha           TEXT    NOT NULL,
    resultado       TEXT    NOT NULL   -- 'ACEPTADO' | 'RECHAZADO'
);
"""


def crear_db():
    """Crea una base SQLite temporal en disco (se borra al cerrar el test)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    con = sqlite3.connect(tmp.name)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.commit()
    return con, tmp.name


def insertar_datos(con, nombre="Ana García", uid="AABBCCDD",
                   est_activo=1, tarj_activa=1):
    """Inserta un estudiante y su tarjeta; devuelve (estudiante_id, uid)."""
    uid = uid.strip().upper()
    cur = con.execute(
        "INSERT INTO estudiantes (nombre, activo) VALUES (?, ?)",
        (nombre, est_activo)
    )
    est_id = cur.lastrowid
    con.execute(
        "INSERT INTO tarjetas (uid, estudiante_id, activa) VALUES (?, ?, ?)",
        (uid, est_id, tarj_activa)
    )
    con.commit()
    return est_id, uid


def procesar_uid(con, uid_raw, hoy=None):
    """
    Lógica del lector: recibe un UID crudo, normaliza, consulta la DB
    y devuelve un dict con:
        resultado  : 'ACEPTADO' | 'RECHAZADO'
        motivo     : str explicativo
        nombre     : str | None
    Replica exactamente el flujo del diagrama §4 del README.
    """
    if hoy is None:
        hoy = date.today().isoformat()

    uid = uid_raw.strip().upper()

    # 1. ¿Existe la tarjeta?
    row = con.execute(
        "SELECT t.activa, t.estudiante_id, e.nombre, e.activo "
        "FROM tarjetas t JOIN estudiantes e ON e.id = t.estudiante_id "
        "WHERE t.uid = ?",
        (uid,)
    ).fetchone()

    if row is None:
        _registrar(con, uid=uid, est_id=None, hoy=hoy, resultado="RECHAZADO")
        return {"resultado": "RECHAZADO", "motivo": "UID desconocido", "nombre": None}

    # 2. ¿Tarjeta activa?
    if not row["activa"]:
        _registrar(con, uid=uid, est_id=row["estudiante_id"], hoy=hoy, resultado="RECHAZADO")
        return {"resultado": "RECHAZADO", "motivo": "Tarjeta inactiva", "nombre": row["nombre"]}

    # 3. ¿Estudiante activo?
    if not row["activo"]:
        _registrar(con, uid=uid, est_id=row["estudiante_id"], hoy=hoy, resultado="RECHAZADO")
        return {"resultado": "RECHAZADO", "motivo": "Estudiante inactivo", "nombre": row["nombre"]}

    # 4. ¿Ya registró hoy?
    ya = con.execute(
        "SELECT 1 FROM registros WHERE estudiante_id = ? AND fecha = ? AND resultado = 'ACEPTADO'",
        (row["estudiante_id"], hoy)
    ).fetchone()

    if ya:
        _registrar(con, uid=uid, est_id=row["estudiante_id"], hoy=hoy, resultado="RECHAZADO")
        return {"resultado": "RECHAZADO", "motivo": "Ya registrado hoy", "nombre": row["nombre"]}

    # 5. Primer escaneo del día → ACEPTADO
    _registrar(con, uid=uid, est_id=row["estudiante_id"], hoy=hoy, resultado="ACEPTADO")
    return {"resultado": "ACEPTADO", "motivo": "Primer escaneo del día", "nombre": row["nombre"]}


def _registrar(con, uid, est_id, hoy, resultado):
    ts = f"{hoy}T00:00:00"  # timestamp simplificado para pruebas
    if est_id is not None:
        con.execute(
            "INSERT INTO registros (estudiante_id, tarjeta_uid, timestamp, fecha, resultado) "
            "VALUES (?, ?, ?, ?, ?)",
            (est_id, uid, ts, hoy, resultado)
        )
    con.commit()


# ---------------------------------------------------------------------------
# Fixture de pytest: base temporal, se borra automáticamente al terminar
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    con, path = crear_db()
    yield con
    con.close()
    os.unlink(path)


# ---------------------------------------------------------------------------
# Casos de prueba — uno por cada rama del diagrama §4
# ---------------------------------------------------------------------------

class TestDiagramaDecision:

    def test_uid_desconocido(self, db):
        """Rama 1: UID que no existe en la tabla tarjetas → RECHAZADO."""
        res = procesar_uid(db, "FFFFFFFF")
        assert res["resultado"] == "RECHAZADO"
        assert "desconocido" in res["motivo"].lower()
        assert res["nombre"] is None

    def test_tarjeta_inactiva(self, db):
        """Rama 2: tarjeta existe pero activa=0 → RECHAZADO."""
        insertar_datos(db, tarj_activa=0)
        res = procesar_uid(db, "AABBCCDD")
        assert res["resultado"] == "RECHAZADO"
        assert "inactiva" in res["motivo"].lower()

    def test_estudiante_inactivo(self, db):
        """Rama 3: tarjeta activa pero estudiante activo=0 → RECHAZADO."""
        insertar_datos(db, est_activo=0)
        res = procesar_uid(db, "AABBCCDD")
        assert res["resultado"] == "RECHAZADO"
        assert "inactivo" in res["motivo"].lower()

    def test_primer_escaneo_aceptado(self, db):
        """Rama 4: todo activo, primer escaneo del día → ACEPTADO."""
        insertar_datos(db)
        res = procesar_uid(db, "AABBCCDD")
        assert res["resultado"] == "ACEPTADO"
        assert res["nombre"] == "Ana García"

    def test_reincidencia_rechazada(self, db):
        """Rama 5: segundo escaneo del mismo día → RECHAZADO."""
        insertar_datos(db)
        hoy = date.today().isoformat()
        procesar_uid(db, "AABBCCDD", hoy=hoy)   # primer escaneo
        res = procesar_uid(db, "AABBCCDD", hoy=hoy)  # reincidencia
        assert res["resultado"] == "RECHAZADO"
        assert "hoy" in res["motivo"].lower()

    def test_dia_anterior_no_bloquea(self, db):
        """El registro de ayer no debe impedir el escaneo de hoy."""
        insertar_datos(db)
        ayer = (date.today() - timedelta(days=1)).isoformat()
        hoy = date.today().isoformat()
        procesar_uid(db, "AABBCCDD", hoy=ayer)  # registra ayer
        res = procesar_uid(db, "AABBCCDD", hoy=hoy)  # hoy debe ser ACEPTADO
        assert res["resultado"] == "ACEPTADO"

    def test_regresion_inyeccion_sql(self, db):
        """Regresión: UID con carga SQL no debe romper la base ni aceptar."""
        insertar_datos(db)
        uid_malicioso = "' OR '1'='1"
        res = procesar_uid(db, uid_malicioso)
        assert res["resultado"] == "RECHAZADO"
        # La base sigue operativa después del intento
        res2 = procesar_uid(db, "AABBCCDD")
        assert res2["resultado"] == "ACEPTADO"

    def test_normalizacion_uid(self, db):
        """El UID con minúsculas o espacios extra debe reconocerse igual."""
        insertar_datos(db, uid="AABBCCDD")
        # misma tarjeta escrita con espacios y minúsculas
        res = procesar_uid(db, "  aabbccdd  ")
        assert res["resultado"] == "ACEPTADO"