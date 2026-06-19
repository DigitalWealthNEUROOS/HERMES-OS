#!/bin/bash
# ============================================================
# OWL Master Start Script
# Starts ALL services, bridges, and keep-alive systems.
# Run this to boot the entire OWL ecosystem.
# ============================================================

set -e

OWL_DIR="/root/telegram-bridge"
LOG_DIR="/tmp"
PID_DIR="/tmp/owl-pids"

mkdir -p "$PID_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] OWL-MASTER: $1" | tee -a "$LOG_DIR/owl-master.log"
}

kill_existing() {
    local name="$1"
    local pidfile="$PID_DIR/${name}.pid"
    if [ -f "$pidfile" ]; then
        local pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            log "Killed existing $name (PID: $pid)"
        fi
        rm -f "$pidfile"
    fi
}

start_daemon() {
    local name="$1"
    shift
    local pidfile="$PID_DIR/${name}.pid"

    # Kill existing
    kill_existing "$name"

    # Start new
    nohup "$@" > "$LOG_DIR/${name}.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$pidfile"
    log "Started $name (PID: $pid)"
    sleep 1

    # Verify
    if kill -0 "$pid" 2>/dev/null; then
        log "✅ $name is running"
    else
        log "❌ $name failed to start"
        cat "$LOG_DIR/${name}.log" 2>/dev/null | tail -5
    fi
}

# ============================================================
# PHASE 1: System Services
# ============================================================
log "=== PHASE 1: System Services ==="

for svc in nginx redis-server ssh fail2ban php8.4-fpm; do
    if [ -f "/etc/init.d/$svc" ]; then
        service "$svc" start 2>/dev/null && log "✅ $svc" || log "⚠️ $svc (may already be running)"
    fi
done

# Start cron (proot-compatible)
if ! pgrep -x "crond" > /dev/null 2>/dev/null && ! pgrep -x "cron" > /dev/null 2>/dev/null; then
    crond -b 2>/dev/null || true
fi

# Start ADB server
adb start-server 2>/dev/null && log "✅ ADB server" || log "⚠️ ADB server"

# ============================================================
# PHASE 2: Local LLM
# ============================================================
log "=== PHASE 2: Local LLM ==="

if [ -f /root/models/qwen2.5/qwen2.5-7b-instruct-q4_k_m.gguf ]; then
    start_daemon "llama-server" /usr/bin/llama-server \
        --model /root/models/qwen2.5/qwen2.5-7b-instruct-q4_k_m.gguf \
        --host 0.0.0.0 \
        --port 11434 \
        --ctx-size 32768 \
        --threads 4 \
        --n-gpu-layers 0
else
    log "⚠️ qwen-7b model not found, skipping LLM"
fi

# ============================================================
# PHASE 3: Keep-Alive System
# ============================================================
log "=== PHASE 3: Keep-Alive System ==="
start_daemon "keep-alive" bash "$OWL_DIR/keep-alive.sh"

# ============================================================
# PHASE 4: Telegram Bridge
# ============================================================
log "=== PHASE 4: Telegram Bridge ==="
start_daemon "telegram-bridge" python3 "$OWL_DIR/bridge.py"

# ============================================================
# PHASE 5: Health Check
# ============================================================
log "=== PHASE 5: Health Check ==="
sleep 3

echo ""
echo "=========================================="
echo "  OWL ECOSYSTEM STATUS"
echo "=========================================="

# Services
echo -n "  nginx:     "; ss -tlnp 2>/dev/null | grep -q ':8081' && echo "✅" || echo "❌"
echo -n "  redis:     "; redis-cli ping 2>/dev/null | grep -q PONG && echo "✅" || echo "❌"
echo -n "  ssh:       "; ss -tlnp 2>/dev/null | grep -q ':22' && echo "✅" || echo "❌"
echo -n "  php-fpm:   "; ss -tlnp 2>/dev/null | grep -q ':9000' && echo "✅" || echo "❌"
echo -n "  LLM:       "; curl -s --max-time 2 http://localhost:11434/ > /dev/null 2>&1 && echo "✅" || echo "❌"
echo -n "  keep-alive "; pgrep -f "keep-alive" > /dev/null && echo "✅" || echo "❌"
echo -n "  bridge:    "; pgrep -f "bridge.py" > /dev/null && echo "✅" || echo "❌"

# Telegram Bot
TOKEN=$(grep "^TELEGRAM_BOT_TOKEN" /root/.hermes/.env 2>/dev/null | sed 's/.*=//')
TG_STATUS=$(curl -s --max-time 5 "https://api.telegram.org/bot${TOKEN}/getMe" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ ' + d['result']['username'] if d.get('ok') else '❌')" 2>/dev/null || echo "❌")
echo -n "  telegram:  "; echo "$TG_STATUS"

# ADB
echo -n "  ADB:       "; adb devices 2>/dev/null | grep -v "^List" | grep -q "device" && echo "✅ connected" || echo "⚠️ no device"

# Health server
echo -n "  health:    "; curl -s --max-time 2 http://localhost:9191/ > /dev/null 2>&1 && echo "✅" || echo "❌"

echo ""
echo "  Webhook:   Long-polling mode"
echo "  LLM:       localhost:11434 (qwen-7b)"
echo "  Health:    http://localhost:9191/"
echo "  PIDs:      $PID_DIR/"
echo ""
echo "=========================================="
echo "  🦉 OWL is awake and watching."
echo "=========================================="
