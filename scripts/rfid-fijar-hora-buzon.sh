#!/bin/bash
# Procesa la peticion de fijar hora que deja el CRUD. Corre como root (unidad systemd).
set -uo pipefail

DIR=/run/rfid-shared
REQ="$DIR/fijar_hora.req"
RES="$DIR/fijar_hora.res"
FIJAR=/usr/local/sbin/rfid-fijar-hora.sh

responder() {
    local tmp
    tmp=$(mktemp "$DIR/.res.XXXXXX") || exit 1
    printf '%s %s\n' "$1" "$2" > "$tmp"
    chmod 0644 "$tmp"
    mv -f "$tmp" "$RES"
}

# Solo un archivo regular; cualquier otra cosa se borra para no re-disparar la unidad
if [ -L "$REQ" ] || [ ! -f "$REQ" ]; then
    rm -rf -- "$REQ"
    exit 0
fi

EPOCH=$(timeout 2 head -c 16 < "$REQ" | tr -d '\n')
rm -rf -- "$REQ"

salida=$("$FIJAR" "$EPOCH" 2>&1)
rc=$?
responder "$rc" "$salida"
