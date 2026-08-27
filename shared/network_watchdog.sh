#!/bin/bash
# Watchdog de conectividad Wi-Fi
# Revisa conexión periódicamente y reconecta a la mejor red conocida disponible.

LOG="/home/admin/rfid-system/shared/network_watchdog.log"
CHECK_INTERVAL=30      # segundos entre chequeos normales
FAIL_THRESHOLD=3       # chequeos fallidos consecutivos antes de actuar
PING_TARGETS=("8.8.8.8" "1.1.1.1")
PING_TIMEOUT=3

fail_count=0

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"
}

check_connectivity() {
    for target in "${PING_TARGETS[@]}"; do
        if ping -c 1 -W "$PING_TIMEOUT" "$target" >/dev/null 2>&1; then
            return 0
        fi
    done
    return 1
}

reconnect_best_known() {
    log "Sin conectividad — buscando mejor red conocida disponible…"
    nmcli device wifi rescan 2>/dev/null
    sleep 3

    # Redes conocidas (guardadas) y redes visibles ordenadas por señal
    mapfile -t known < <(nmcli -t -f NAME connection show | sort -u)
    mapfile -t visible < <(nmcli -t -f SSID,SIGNAL dev wifi list | sort -t: -k2 -nr)

    best=""
    best_signal=-1
    for entry in "${visible[@]}"; do
        ssid="${entry%%:*}"
        signal="${entry##*:}"
        [ -z "$ssid" ] && continue
        for k in "${known[@]}"; do
            if [ "$ssid" = "$k" ] && [ "$signal" -gt "$best_signal" ]; then
                best="$ssid"
                best_signal="$signal"
            fi
        done
    done

    if [ -n "$best" ]; then
        log "Conectando a red conocida con mejor señal: $best (${best_signal}%)"
        nmcli connection up "$best" >> "$LOG" 2>&1
    else
        log "Ninguna red conocida visible — reiniciando NetworkManager como último recurso"
        systemctl restart NetworkManager
    fi
}

log "Watchdog de red iniciado"

while true; do
    if check_connectivity; then
        fail_count=0
    else
        fail_count=$((fail_count + 1))
        log "Chequeo fallido ($fail_count/$FAIL_THRESHOLD)"
        if [ "$fail_count" -ge "$FAIL_THRESHOLD" ]; then
            reconnect_best_known
            fail_count=0
            sleep 15   # da tiempo a que la reconexión se estabilice antes del próximo chequeo
        fi
    fi
    sleep "$CHECK_INTERVAL"
done
