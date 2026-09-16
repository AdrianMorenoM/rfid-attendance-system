#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_test.py — Prueba de carga simulando varios dashboards/kioscos
consultando el sistema al mismo tiempo.

IMPORTANTE: solo golpea endpoints de SOLO LECTURA (/api/estado,
/api/ultimo-evento, /api/estadisticas) — seguro de correr contra
producción. NO uses este patrón contra endpoints que modifican datos.

Simula el patrón real de polling documentado en el README (§9.3):
  - /api/ultimo-evento cada 800ms  (POLL_NEW_EVENT_MS)
  - /api/estado        cada 5000ms (POLL_STATS_MS)

Requiere: aiohttp (pip install aiohttp --break-system-packages)

Uso:
    python3 load_test.py --clients 5 --duration 30
    python3 load_test.py --clients 20 --duration 60 --host 192.168.1.140
"""

import argparse
import asyncio
import statistics
import time

import aiohttp


async def poll_loop(session, name, url, interval_s, stop_at, latencies, errors):
    while time.monotonic() < stop_at:
        t0 = time.perf_counter()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                await resp.read()
                elapsed_ms = (time.perf_counter() - t0) * 1000
                latencies.append(elapsed_ms)
                if resp.status != 200:
                    errors.append(f"{name}: HTTP {resp.status}")
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
        await asyncio.sleep(interval_s)


async def simulate_client(client_id, dash_base, duration, latencies_estado,
                           latencies_evento, errors):
    stop_at = time.monotonic() + duration
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            poll_loop(session, f"cliente{client_id}-estado",
                      f"{dash_base}/api/estado", 5.0, stop_at,
                      latencies_estado, errors),
            poll_loop(session, f"cliente{client_id}-evento",
                      f"{dash_base}/api/ultimo-evento", 0.8, stop_at,
                      latencies_evento, errors),
        )


def percentil(datos, p):
    if not datos:
        return float("nan")
    datos_ordenados = sorted(datos)
    idx = int(len(datos_ordenados) * p / 100)
    idx = min(idx, len(datos_ordenados) - 1)
    return datos_ordenados[idx]


async def main_async(args):
    dash_base = f"http://{args.host}:{args.dashboard_port}"

    latencies_estado = []
    latencies_evento = []
    errors = []

    print(f"Simulando {args.clients} clientes durante {args.duration}s contra {dash_base}")
    print("(patrón real del dashboard: /api/estado cada 5s, /api/ultimo-evento cada 0.8s)")
    print()

    t_start = time.perf_counter()
    await asyncio.gather(*[
        simulate_client(i, dash_base, args.duration, latencies_estado,
                         latencies_evento, errors)
        for i in range(args.clients)
    ])
    t_total = time.perf_counter() - t_start

    print(f"Duración real: {t_total:.1f}s\n")

    for nombre, datos in [
        ("/api/estado", latencies_estado),
        ("/api/ultimo-evento", latencies_evento),
    ]:
        if not datos:
            print(f"{nombre}: sin datos (revisa conectividad)")
            continue
        print(f"{nombre}  (n={len(datos)} peticiones)")
        print(f"  promedio: {statistics.mean(datos):.1f}ms")
        print(f"  mediana:  {statistics.median(datos):.1f}ms")
        print(f"  p95:      {percentil(datos, 95):.1f}ms")
        print(f"  p99:      {percentil(datos, 99):.1f}ms")
        print(f"  máximo:   {max(datos):.1f}ms")
        print()

    if errors:
        print(f"⚠️  {len(errors)} errores durante la prueba (primeros 10):")
        for e in errors[:10]:
            print(f"  - {e}")
    else:
        print("✅ Sin errores durante la prueba.")

    # Referencia del README (§8.2): p95 de /api/estado en peor caso ~400ms
    # por la llamada a systemctl is-active. Si tu p95 supera eso por mucho
    # con pocos clientes, es señal de que ese cuello de botella (ya
    # documentado) empieza a doler más de lo esperado.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--dashboard-port", type=int, default=5000)
    parser.add_argument("--clients", type=int, default=5,
                         help="Número de dashboards/kioscos simulados en paralelo")
    parser.add_argument("--duration", type=int, default=30,
                         help="Duración de la prueba en segundos")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()