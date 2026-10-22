#!/bin/sh
# /usr/local/bin/rfid-drop-caches.sh
#
# Libera la caché de página del kernel Linux (equivalente a
# `sync; echo 3 > /proc/sys/vm/drop_caches`).
#
# Este script existe para NO tener que dar sudo NOPASSWD sobre
# `sh -c '...'` genérico: `sudo -n sh -c 'CUALQUIER_COSA'` con NOPASSWD
# es virtualmente sudo total, porque root ejecuta lo que sea que venga
# en el string. Al fijar el script (sin argumentos, sin leer stdin, sin
# interpolar nada externo) y autorizar en sudoers solo la ruta exacta
# de ESTE archivo, el usuario de la app únicamente puede ejecutar este
# comportamiento fijo y nada más — no puede pedirle a sudo que ejecute
# otra cosa.
#
# No acepta argumentos ni variables de entorno externas relevantes:
# no hay nada que un atacante que ya comprometiera app_crud.py pudiera
# usar para hacer que este script haga algo distinto de liberar caché.

set -eu

sync
echo 3 > /proc/sys/vm/drop_caches
