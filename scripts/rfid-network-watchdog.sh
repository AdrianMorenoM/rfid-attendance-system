#!/bin/bash
# Watchdog de conectividad Wi-Fi (prioriza la red LOCAL)
# Solo actúa si se pierde la red local (puerta de enlace).
# Que no haya internet NO es motivo para reconectar.

LOG="/home/admin/rfid-system/shared/network_watchdog.log"
IFACE="wlan0"
CHECK_INTERVAL=30
FAIL_THRESHOLD=3
PING_TIMEOUT=3
INTERNET_TARGETS=("8.8.8.8" "1.1.1.1")
NM_RESTART_MIN_GAP=600   # segundos mínimos entre reinicios de NetworkManager

fail_count=0
last_state=""
last_nm_restart=0
state="sin-red"
GW=""

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"
}

ping_ok() {
    ping -c 1 -W "$PING_TIMEOUT" "$1" >/dev/null 2>&1
}

internet_ok() {
    local t
    for t in "${INTERNET_TARGETS[@]}"; do
        ping_ok "$t" && return 0
    done
    return 1
}

# Actualiza $state ("internet", "solo-lan" o "sin-red").
# Devuelve 0 si la red local funciona.
check_connectivity() {
    GW=$(ip -4 route show default dev "$IFACE" 2>/dev/null | awk '/^default/ {print $3; exit}')
    if [ -z "$GW" ]; then
        state="sin-red"
        return 1
    fi
    if ping_ok "$GW"; then
        if internet_ok; then state="internet"; else state="solo-lan"; fi
        return 0
    fi
    # Algunas redes no responden ping en la puerta de enlace: probar internet y luego ARP
    if internet_ok; then
        state="internet"
        return 0
    fi
    if command -v arping >/dev/null 2>&1 && arping -c 1 -w 3 -I "$IFACE" "$GW" >/dev/null 2>&1; then
        state="solo-lan"
        return 0
    fi
    state="sin-red"
    return 1
}

reconnect_best_known() {
    log "Sin red local — buscando mejor red conocida disponible…"
    nmcli device wifi rescan 2>/dev/null
    sleep 3

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
        now=$(date +%s)
        if [ $((now - last_nm_restart)) -ge "$NM_RESTART_MIN_GAP" ]; then
            log "Ninguna red conocida visible — reiniciando NetworkManager como último recurso"
            systemctl restart NetworkManager
            last_nm_restart=$now
        else
            log "Ninguna red conocida visible — esperando antes de reiniciar NetworkManager"
        fi
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
            sleep 15
        fi
    fi
    if [ "$state" != "$last_state" ]; then
        log "Estado de red: $state (puerta de enlace: ${GW:-ninguna})"
        last_state="$state"
    fi
    sleep "$CHECK_INTERVAL"
done
