#!/bin/bash
# rfid-fijar-hora.sh: fija la hora del sistema SOLO si el reloj no esta sincronizado.
# Lo ejecuta una unidad systemd de root (no sudo). Instalar con:
#   sudo install -o root -g root -m 755 scripts/rfid-fijar-hora.sh /usr/local/sbin/
#
# Uso: rfid-fijar-hora.sh [--validar] EPOCH_SEGUNDOS
set -euo pipefail

MIN_EPOCH=1767225600     # 2026-01-01 00:00 UTC
MAX_EPOCH=2082758400     # 2036-01-01 00:00 UTC
SYNC_MARCA="/run/systemd/timesync/synchronized"
MANUAL_MARCA="/run/rfid-shared/reloj_manual_ok"

MODO="aplicar"
if [ "${1:-}" = "--validar" ]; then
    MODO="validar"
    shift
fi
EPOCH="${1:-}"

if ! [[ "$EPOCH" =~ ^[0-9]{10}$ ]]; then
    echo "Formato invalido: se espera un epoch en segundos de 10 digitos" >&2
    exit 1
fi
if [ "$EPOCH" -lt "$MIN_EPOCH" ] || [ "$EPOCH" -gt "$MAX_EPOCH" ]; then
    echo "Hora fuera del rango permitido" >&2
    exit 1
fi
if [ -e "$SYNC_MARCA" ]; then
    echo "El reloj ya esta sincronizado con NTP: no se permite fijar la hora a mano" >&2
    exit 2
fi
if [ ! -d "$(dirname "$MANUAL_MARCA")" ]; then
    echo "No existe el directorio de la marca: $(dirname "$MANUAL_MARCA")" >&2
    exit 3
fi
if [ "$MODO" = "validar" ]; then
    echo "OK (validacion, sin cambios)"
    exit 0
fi

/usr/bin/date -u -s "@$EPOCH" > /dev/null
if [ -x /usr/sbin/fake-hwclock ]; then
    /usr/sbin/fake-hwclock save || true
fi
/usr/bin/install -m 0644 /dev/null "$MANUAL_MARCA"
/usr/bin/logger -t rfid-fijar-hora "Hora fijada a mano: epoch=$EPOCH"
echo "OK"
