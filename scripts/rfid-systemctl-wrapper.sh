#!/bin/bash
# rfid-systemctl-wrapper.sh
# Wrapper de validacion para permitir que rfid-svc controle SOLO los
# servicios RFID con SOLO las acciones permitidas, vía sudo.
# Se instala en /usr/local/bin/ y sudoers apunta unicamente a este script,
# nunca a systemctl directamente con comodines.

set -euo pipefail

ACTION="${1:-}"
SERVICE="${2:-}"

ALLOWED_ACTIONS="start stop restart enable disable status is-active is-enabled"
ALLOWED_SERVICES="rfid-crud.service rfid-dashboard.service rfid-reader.service"

action_ok=0
for a in $ALLOWED_ACTIONS; do
    [ "$ACTION" = "$a" ] && action_ok=1
done

service_ok=0
for s in $ALLOWED_SERVICES; do
    [ "$SERVICE" = "$s" ] && service_ok=1
done

if [ "$action_ok" -ne 1 ] || [ "$service_ok" -ne 1 ]; then
    echo "Accion o servicio no permitido: '$ACTION' '$SERVICE'" >&2
    exit 1
fi

exec /usr/bin/systemctl "$ACTION" "$SERVICE"