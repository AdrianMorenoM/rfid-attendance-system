#!/bin/bash
set -uo pipefail
source /etc/rfid-offsite.conf
DB=/home/admin/rfid-system/data/rfid.db
STAGE=/var/backups/rfid-offsite
TS=$(date +%Y%m%d_%H%M%S)
SNAP="$STAGE/rfid_offsite_$TS.db"
FALLOS=0

mkdir -p "$STAGE"; chmod 700 "$STAGE"
sqlite3 "$DB" ".backup '$SNAP'" || { echo "fallo al crear snapshot"; exit 1; }
[ "$(sqlite3 "$SNAP" 'PRAGMA integrity_check;')" = "ok" ] \
  || { echo "snapshot corrupto, no se envia"; rm -f "$SNAP"; exit 1; }
sync

scp -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15 \
    "$SNAP" "$REMOTE:$REMOTE_DIR/" \
  && echo "OK windows" || { echo "FALLO windows"; FALLOS=1; }

if mountpoint -q "$USB_DIR"; then
  cp "$SNAP" "$USB_DIR/" && sync && echo "OK usb" || { echo "FALLO usb"; FALLOS=1; }
else
  echo "usb no montada (omitida)"
fi

ls -1t "$STAGE"/rfid_offsite_*.db | tail -n +4 | xargs -r rm -f
exit $FALLOS

