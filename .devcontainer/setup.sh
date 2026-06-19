#!/bin/bash
# HERMES-OS Setup Script for GitHub Codespace
set -e

echo "🦉 Setting up HERMES-OS..."

# System dependencies
apt-get update && apt-get install -y \
    redis-server nginx curl wget git \
    nmap nikto hydra sqlmap gobuster hashcat \
    build-essential cmake pkg-config \
    libssl-dev libffi-dev

# Start Redis
redis-server --daemonize yes

# Start Nginx
nginx

# Python dependencies
pip3 install --upgrade pip
pip3 install \
    flask fastapi uvicorn \
    requests aiohttp \
    redis python-telegram-bot \
    web3 eth-account \
    py-solc-x \
    beautifulsoup4 lxml \
    numpy pandas \
    python-dotenv pyyaml

# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source ~/.cargo/env

# Install Go (if not present)
if ! command -v go &> /dev/null; then
    wget -q https://go.dev/dl/go1.24.4.linux-amd64.tar.gz
    tar -C /usr/local -xzf go1.24.4.linux-amd64.tar.gz
    export PATH=$PATH:/usr/local/go/bin
fi

# Install Solidity
pip3 install py-solc-x
python3 -c "from solcx import install_solc; install_solc('0.8.20')" 2>/dev/null || true

# Create .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || echo "TELEGRAM_BOT_TOKEN=your_token_here" > .env
fi

# Start all services
echo "🚀 Starting HERMES services..."
python3 hermes.py &
python3 proxy_api_os.py &
python3 control_plane.py &
python3 rag_server.py &
python3 airllm_server.py &
python3 github_server.py &
python3 miniapp_agent.py &
python3 web3_os.py &
python3 web3_money_engine.py &
python3 browser_agent.py &
python3 adb_bridge.py &

echo "✅ HERMES-OS is ready!"
echo "📊 Dashboard: http://localhost:9090/status"
echo "🤖 Bot: @Hermes_termux_chat_bot"
