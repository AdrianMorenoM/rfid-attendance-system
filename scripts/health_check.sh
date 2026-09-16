#!/bin/bash
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -u admin:admin12345 http://127.0.0.1:5001/api/health/db)
if [ "$RESPONSE" != "200" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - FALLO: health check devolvió $RESPONSE" >> /home/admin/rfid-system/logs/health_check.log
fi
