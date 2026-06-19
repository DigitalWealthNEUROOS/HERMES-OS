#!/bin/bash
# OWL Keep-Alive Monitor
# Ensures all critical processes are running

LOG="/tmp/owl-keepalive.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$TIMESTAMP] $1" >> "$LOG"
}

# Check and restart function
ensure() {
    local name="$1"
    local check_cmd="$2"
    local start_cmd="$3"
    
    if eval "$check_cmd" > /dev/null 2>&1; then
        return 0
    fi
    
    log "RESTARTING: $name"
    eval "$start_cmd" > /dev/null 2>&1
    sleep 2
    
    if eval "$check_cmd" > /dev/null 2>&1; then
        log "OK: $name restarted"
    else
        log "FAIL: $name could not be restarted"
    fi
}

# === SERVICES ===
# nginx
ensure "nginx" \
    "curl -s -o /dev/null --max-time 2 http://127.0.0.1:8081/" \
    "service nginx start"

# redis
ensure "redis" \
    "redis-cli ping 2>/dev/null | grep -q PONG" \
    "service redis-server start"

# ssh
ensure "ssh" \
    "echo '' | nc -w2 127.0.0.1 22 2>/dev/null | grep -q SSH" \
    "service ssh start"

# ADB
ensure "adb" \
    "adb devices 2>/dev/null | grep -q List" \
    "adb start-server"

# === LOCAL LLM (Qwen 2.5 7B) ===
ensure "llama-server" \
    "curl -s --max-time 2 http://127.0.0.1:11434/ > /dev/null 2>&1" \
    "/usr/bin/llama-server --model /root/models/qwen2.5/qwen2.5-7b-instruct-q4_k_m.gguf --host 0.0.0.0 --port 11434 --ctx-size 32768 --threads 4 --n-gpu-layers 0 > /tmp/llama-server.log 2>&1 &"

# === PROXY API OS ===
ensure "proxy-api" \
    "curl -s --max-time 2 http://127.0.0.1:8090/api/v1/health > /dev/null 2>&1" \
    "cd /root/telegram-bridge && python3 proxy_api_os.py > /tmp/proxy-api.log 2>&1 &"

# === HERMES AGENT ===
ensure "hermes-agent" \
    "pgrep -f 'hermes.py' > /dev/null" \
    "cd /root/telegram-bridge && python3 hermes.py > /tmp/hermes-agent.log 2>&1 &"

# === CONTROL PLANE ===
ensure "control-plane" \
    "curl -s --max-time 2 http://127.0.0.1:9090/health > /dev/null 2>&1" \
    "cd /root/telegram-bridge && python3 control_plane.py > /tmp/control-plane.log 2>&1 &"

# === RAG SERVER ===
ensure "rag-server" \
    "curl -s --max-time 2 http://127.0.0.1:9092/health > /dev/null 2>&1" \
    "cd /root/telegram-bridge && python3 rag_server.py > /tmp/rag-server.log 2>&1 &"

# === AIRLLM SERVER ===
ensure "airllm-server" \
    "curl -s --max-time 2 http://127.0.0.1:9093/health > /dev/null 2>&1" \
    "cd /root/telegram-bridge && python3 airllm_server.py > /tmp/airllm-server.log 2>&1 &"

# === GITHUB SERVER ===
ensure "github-server" \
    "curl -s --max-time 2 http://127.0.0.1:9094/health > /dev/null 2>&1" \
    "cd /root/telegram-bridge && python3 github_server.py > /tmp/github-server.log 2>&1 &"

# === WEB3 MONEY ENGINE ===
ensure "web3-money" \
    "curl -s --max-time 2 http://127.0.0.1:9098/health > /dev/null 2>&1" \
    "cd /root/telegram-bridge && python3 web3_money_engine.py > /tmp/web3-money.log 2>&1 &"

# === BROWSER AGENT ===
ensure "browser-agent" \
    "curl -s --max-time 2 http://127.0.0.1:9097/health > /dev/null 2>&1" \
    "cd /root/telegram-bridge && python3 browser_agent.py > /tmp/browser-agent.log 2>&1 &"

# === TELEGRAM API CHECK ===
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://api.telegram.org/bot$(grep '^TELEGRAM_BOT_TOKEN' /root/.hermes/.env | cut -d= -f2)/getMe" 2>/dev/null)
if [ "$HTTP_CODE" != "200" ]; then
    log "WARNING: Telegram API returned HTTP $HTTP_CODE"
fi

# === DISK CHECK ==="
DISK_PCT=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_PCT" -gt 90 ]; then
    log "WARNING: Disk usage at ${DISK_PCT}%"
fi

# === MEMORY CHECK ==="
FREE_MEM=$(free -m | awk '/^Mem:/{print $7}')
if [ "$FREE_MEM" -lt 300 ]; then
    log "WARNING: Low memory - ${FREE_MEM}MB available"
    sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
fi

exit 0
