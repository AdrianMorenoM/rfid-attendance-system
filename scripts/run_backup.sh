#!/bin/bash
set -euo pipefail
source /home/admin/rfid-system/.env 
curl -s -H "X-Requested-With: XMLHttpRequest" -u "admin:${ADMIN_PASSWORD}" -X POST http://127.0.0.1:5001/api/software/database/backup >> /home/admin/rfid-system/logs/backup_auto.log 2>&1
