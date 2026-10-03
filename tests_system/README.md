# tests_system — suite de sistema del proyecto RFID

Complementa a `shared/tests/` (no la reemplaza). Cubre: 01 RFID end-to-end · 02 Seguridad ·
03 Resiliencia · 04 Rendimiento · 05 Backups · 06 Integraciones · 07 Cobertura.

## Instalar (en la Raspberry, como admin)
    unzip -o tests_system.zip -d ~/rfid-system/
    cd ~/rfid-system && bash tests_system/run_all.sh --no-live      # primera vez: solo pruebas seguras

## Modos
| Comando | Qué hace |
|---|---|
| `run_all.sh --no-live` | Solo pruebas en proceso (BD temporal, subprocess bloqueado). No toca nada real. |
| `run_all.sh` | Añade pruebas en vivo de SOLO LECTURA (concurrencia, latencia, nginx, systemd, tailscale, backup crear/borrar). |
| `run_all.sh --destructive` | Además reinicia servicios, hace kill -9 y bloquea la BD 3 s. Úsalo con la Pi sin tráfico. |
| `run_all.sh --destructive --hardware` | Además lee una tarjeta física (detiene rfid-reader 15 s). |
| `run_all.sh --cov` | Cobertura de líneas, ramas y funciones (incluye la suite existente). |
| `run_all.sh -k seguridad` | Cualquier argumento extra se pasa a pytest. |

Reporte: `tests_system/reports/reporte.html` (+ `htmlcov/`, `coverage.xml`, `perf.json`).
Verlo: `cd tests_system/reports && python3 -m http.server 8088` y abrir `http://<ip-tailscale>:8088/reporte.html`.

## Dashboard sin login en la app
Si el dashboard no tiene login propio (público, o protegido solo por Nginx con allow/deny), corre con
`RFID_DASH_PUBLICO=1` para omitir las pruebas que exigen login en la app:
`RFID_DASH_PUBLICO=1 bash tests_system/run_all.sh`
La prueba `test_rechaza_conexiones_que_no_vienen_de_tailscale_ni_de_la_pi` (06) comprueba que Nginx
cierre el acceso desde la red local.

## Umbrales (variables de entorno)
RFID_P50_MS=1000 · RFID_P95_MS=3000 · RFID_MAX_MS=8000 · RFID_BACKUP_MAX_AGE_H=72 ·
RFID_CERT_MIN_DAYS=14 · RFID_WAL_MAX_MB=32 · COV_MIN_LINES=75 · COV_MIN_BRANCHES=60 · COV_MIN_FUNCTIONS=75

## Garantías de seguridad de la suite
- Nunca llama a reboot/shutdown ni a los endpoints de servicios/red/admin-scan contra el sistema real.
- Pruebas en proceso: `subprocess`/`os.system` bloqueados y BD temporal (nunca `shared/rfid.db`).
- En vivo: máximo 2 logins fallidos (el bloqueo es a 5/min por IP y comparte 127.0.0.1 con cron).
- Backups en vivo: se crea un backup y se borra ese mismo. NUNCA se restaura sobre la BD real.

## aplicar_parches.py (uso único)
Parchea `crud/app_crud.py` (restore) y `shared/rfid_reader.py` (contador de reintentos). Hace copia de los
originales en `~/parches-bak/`, se niega a modificar si el código no coincide exactamente y no corre dos veces.
    python3 tests_system/aplicar_parches.py
