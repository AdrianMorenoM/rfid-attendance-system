#!/bin/bash

set -u

ENV_FILE="/home/admin/rfid-system/.env"

if [ ! -r "$ENV_FILE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - FALLO: no se puede leer $ENV_FILE" \
        >> /home/admin/rfid-system/logs/health_check.log
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [ -z "${ADMIN_USER:-}" ] || [ -z "${ADMIN_PASSWORD:-}" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - FALLO: ADMIN_USER/ADMIN_PASSWORD no están configurados" \
        >> /home/admin/rfid-system/logs/health_check.log
    exit 1
fi

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -u "$ADMIN_USER:$ADMIN_PASSWORD" \
    http://127.0.0.1:5001/api/health/db)

if [ "$RESPONSE" != "200" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - FALLO: health check devolvió $RESPONSE" \
        >> /home/admin/rfid-system/logs/health_check.log
fi

# Verificar que rfid-reader esté activo
if ! systemctl is-active --quiet rfid-reader.service; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - FALLO: rfid-reader.service no está activo — reiniciando" \
        >> /home/admin/rfid-system/logs/health_check.log
    sudo systemctl restart rfid-reader.service
fi
