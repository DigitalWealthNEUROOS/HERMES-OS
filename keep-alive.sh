#!/bin/bash
# ============================================================
# OWL Keep-Alive System
# Ensures Telegram Bot + Hermes Gateway + Local LLM + Services
# never stop running. Self-healing every 60 seconds.
# ============================================================

LOG="/tmp/keep-alive.log"
MAX_LOG_SIZE=1048576  # 1MB

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
    # Rotate log if too big
    if [ -f "$LOG" ] && [ $(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0) -gt $MAX_LOG_SIZE ]; then
        mv "$LOG" "${LOG}.old"
    fi
}

# ---- 1. Ensure Services Running ----
ensure_services() {
    # nginx
    if ! ss -tlnp 2>/dev/null | grep -q ':8081'; then
        service nginx start 2>/dev/null
        log "RESTARTED: nginx"
    fi

    # redis
    if ! redis-cli ping 2>/dev/null | grep -q PONG; then
        service redis-server start 2>/dev/null
        log "RESTARTED: redis-server"
    fi

    # ssh
    if ! ss -tlnp 2>/dev/null | grep -q ':22'; then
        service ssh start 2>/dev/null
        log "RESTARTED: ssh"
    fi

    # php-fpm
    if ! ss -tlnp 2>/dev/null | grep -q ':9000'; then
        service php8.4-fpm start 2>/dev/null
        log "RESTARTED: php8.4-fpm"
    fi
}

# ---- 2. Ensure Local LLM Running ----
ensure_llm() {
    if ! curl -s --max-time 3 http://localhost:11434/ 2>/dev/null | grep -q "SimpleChat\|LlamaCpp\|html"; then
        pkill -f llama-server 2>/dev/null
        sleep 1
        /usr/bin/llama-server \
            --model /root/models/qwen2.5/qwen2.5-7b-instruct-q4_k_m.gguf \
            --host 0.0.0.0 \
            --port 11434 \
            --ctx-size 32768 \
            --threads 4 \
            --n-gpu-layers 0 \
            > /tmp/llama-server.log 2>&1 &
        log "RESTARTED: llama-server qwen-7b (PID: $!)"
        sleep 3
    fi
}

# ---- 3. Ensure Hermes Gateway Running ----
ensure_gateway() {
    # Check if hermes gateway process is running
    if ! pgrep -f "hermes.*gateway" > /dev/null 2>&1; then
        log "WARNING: Hermes gateway not detected as process"
        # Gateway might be running as service, check port
        # Hermes gateway typically runs on a specific port
        # We rely on the cron-based restart for gateway
    fi
}

# ---- 4. Ensure ADB Server Running ----
ensure_adb() {
    if ! pgrep -f "adb.*fork-server" > /dev/null 2>&1; then
        adb start-server 2>/dev/null
        log "RESTARTED: ADB server"
    fi
}

# ---- 5. WiFi Connection Check ----
ensure_wifi() {
    # Check if we have internet connectivity
    if ! ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
        log "WARNING: No internet connectivity"
        # Try to restart WiFi via termux-wifi if available
        if command -v termux-wifi-enable &>/dev/null; then
            termux-wifi-enable true 2>/dev/null
            log "ACTION: termux-wifi-enable true"
        fi
    fi
}

# ---- 6. Telegram API Health Check ----
check_telegram() {
    TOKEN=$(grep "^TELEGRAM_BOT_TOKEN" /root/.hermes/.env 2>/dev/null | head -1 | sed 's/.*=//')
        if [ -n "$TOKEN" ]; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://api.telegram.org/bot${TOKEN}/getMe" 2>/dev/null)
        if [ "$HTTP_CODE" != "200" ]; then
            log "WARNING: Telegram API returned HTTP $HTTP_CODE"
        fi
    fi
}

# ---- 7. Termux API Check ----
check_termux_api() {
    # Check if termux-api is available
    if command -v termux-battery-status &>/dev/null; then
        BATTERY=$(termux-battery-status 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('percentage','?'))" 2>/dev/null)
        if [ -n "$BATTERY" ]; then
            log "INFO: Battery ${BATTERY}%"
        fi
    fi
}

# ---- 8. Disk Space Check ----
check_disk() {
    DISK_USAGE=$(df / 2>/dev/null | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ -n "$DISK_USAGE" ] && [ "$DISK_USAGE" -gt 90 ]; then
        log "WARNING: Disk usage at ${DISK_USAGE}%"
    fi
}

# ---- 9. Memory Check ----
check_memory() {
    FREE_MEM=$(free -m 2>/dev/null | awk '/^Mem:/{print $4}')
    if [ -n "$FREE_MEM" ] && [ "$FREE_MEM" -lt 500 ]; then
        log "WARNING: Low memory - ${FREE_MEM}MB free"
        # Clear caches
        sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
        log "ACTION: Cleared memory caches"
    fi
}

# ---- MAIN LOOP ----
log "=== Keep-Alive System Started ==="
log "PID: $$"

while true; do
    ensure_services
    ensure_llm
    ensure_gateway
    ensure_adb
    ensure_wifi
    check_telegram
    check_termux_api
    check_disk
    check_memory
    sleep 60
done
