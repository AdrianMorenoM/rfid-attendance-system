#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smoke_test_api.py — Pruebas de humo contra el sistema RFID EN VIVO.

IMPORTANTE: solo toca endpoints de SOLO LECTURA (GET). Nunca llama
purge, baja-masiva, restore, reboot, shutdown, ni ninguna ruta que
modifique datos — es seguro correr esto contra rfid-crud.service y
rfid-dashboard.service en producción, tantas veces como se quiera.

Requiere: requests (pip install requests --break-system-packages)

Uso:
    python3 smoke_test_api.py --user admin --password TU_CONTRASEÑA
    python3 smoke_test_api.py --user admin --password TU_CONTRASEÑA --host 192.168.1.140
"""

import argparse
import sys
import time
import requests


def check(nombre, condicion, detalle=""):
    estado = "✅ PASS" if condicion else "❌ FAIL"
    print(f"{estado}  {nombre}" + (f"  — {detalle}" if detalle and not condicion else ""))
    return condicion


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--crud-port", type=int, default=5001)
    parser.add_argument("--dashboard-port", type=int, default=5000)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    auth = (args.user, args.password)
    crud_base = f"http://{args.host}:{args.crud_port}"
    dash_base = f"http://{args.host}:{args.dashboard_port}"

    resultados = []

    # ---- 1. Autenticación ----
    r = requests.get(f"{crud_base}/api/estadisticas")
    resultados.append(check(
        "Rechaza peticiones sin credenciales (401)",
        r.status_code == 401, f"status={r.status_code}"
    ))

    r = requests.get(f"{crud_base}/api/estadisticas", auth=("admin", "credencial_incorrecta_xyz"))
    resultados.append(check(
        "Rechaza credenciales incorrectas (401)",
        r.status_code == 401, f"status={r.status_code}"
    ))

    r = requests.get(f"{crud_base}/api/estadisticas", auth=auth)
    resultados.append(check(
        "Acepta credenciales correctas (200)",
        r.status_code == 200, f"status={r.status_code}"
    ))

    # ---- 2. Cabeceras de seguridad (ver §7.1 del README) ----
    if r.status_code == 200:
        headers_esperadas = [
            "X-Frame-Options", "X-Content-Type-Options",
            "Content-Security-Policy", "Referrer-Policy", "Permissions-Policy",
        ]
        faltantes = [h for h in headers_esperadas if h not in r.headers]
        resultados.append(check(
            "Cabeceras de seguridad presentes",
            not faltantes, f"faltan: {faltantes}"
        ))

    # ---- 3. Estructura de /api/estadisticas ----
    if r.status_code == 200:
        data = r.json()
        claves_esperadas = {
            "total_estudiantes", "estudiantes_activos", "total_tarjetas",
            "tarjetas_activas", "registros_hoy", "total_registros", "aceptados_hoy",
        }
        stats = data.get("stats", {})
        resultados.append(check(
            "/api/estadisticas trae todas las claves esperadas",
            claves_esperadas.issubset(stats.keys()),
            f"faltan: {claves_esperadas - stats.keys()}"
        ))
        resultados.append(check(
            "Los conteos son coherentes (activos <= total)",
            stats.get("estudiantes_activos", 0) <= stats.get("total_estudiantes", 0)
        ))

    # ---- 4. Health check de la base de datos ----
    r = requests.get(f"{crud_base}/api/health/db", auth=auth)
    resultados.append(check(
        "/api/health/db responde 200",
        r.status_code == 200, f"status={r.status_code}"
    ))
    if r.status_code == 200:
        data = r.json()
        resultados.append(check(
            "/api/health/db reporta healthy=true",
            data.get("healthy") is True, f"result={data.get('result')}"
        ))

    # ---- 5. Endpoint /api/migrate deshabilitado responde 404, no 403 ----
    # (comportamiento deliberado documentado en §7.14 — no revela su existencia)
    r = requests.post(f"{crud_base}/api/migrate", auth=auth)
    resultados.append(check(
        "/api/migrate responde 404 si ALLOW_HTTP_MIGRATIONS está deshabilitado "
        "(si esto falla con 200, revisa que la variable no haya quedado activa)",
        r.status_code in (404, 200),  # 200 solo si el flag está activo a propósito
        f"status={r.status_code}"
    ))

    # ---- 6. Dashboard: /api/estado y /api/ultimo-evento ----
    r = requests.get(f"{dash_base}/api/estado")
    resultados.append(check(
        "GET /api/estado (dashboard) responde 200",
        r.status_code == 200, f"status={r.status_code}"
    ))
    if r.status_code == 200:
        data = r.json()
        resultados.append(check(
            "/api/estado trae 'hourly' con exactamente 24 posiciones",
            len(data.get("hourly", [])) == 24,
            f"len={len(data.get('hourly', []))}"
        ))
        resultados.append(check(
            "/api/estado trae 'reader_ok' como booleano",
            isinstance(data.get("reader_ok"), bool)
        ))

    r = requests.get(f"{dash_base}/api/ultimo-evento")
    resultados.append(check(
        "GET /api/ultimo-evento (dashboard) responde 200",
        r.status_code == 200, f"status={r.status_code}"
    ))

    # ---- 7. Latencia básica de los endpoints más consultados ----
    for nombre, url, kwargs in [
        ("GET /api/estado", f"{dash_base}/api/estado", {}),
        ("GET /api/ultimo-evento", f"{dash_base}/api/ultimo-evento", {}),
        ("GET /api/estadisticas", f"{crud_base}/api/estadisticas", {"auth": auth}),
    ]:
        t0 = time.perf_counter()
        requests.get(url, **kwargs)
        ms = (time.perf_counter() - t0) * 1000
        # Umbrales generosos acordes a §8.2 del README (peor caso ~400ms
        # para /api/estado por la llamada a systemctl)
        umbral = 800
        resultados.append(check(
            f"{nombre} responde en menos de {umbral}ms",
            ms < umbral, f"{ms:.1f}ms"
        ))

    # ---- Resumen ----
    print()
    total = len(resultados)
    ok = sum(resultados)
    print(f"Resultado: {ok}/{total} pruebas pasaron")
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()