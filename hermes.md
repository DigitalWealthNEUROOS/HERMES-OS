# HERMES v2.0 - Money-Generating Telegram Agent

## Overview
HERMES is a fork of OWL Telegram Terminal, optimized for money generation on Telegram.
It combines AI-powered automation with crypto earning strategies.

## Revenue Streams

### 1. Airdrop Farming
- **TON Foundation**: 1-10 TON per drop
- **Arbitrum**: 100-500 ARB
- **Starknet**: 50-200 STRK
- **LayerZero**: 100-1000 ZRO
- **Blast**: 50-200 BLAST
- **EigenLayer**: 10-100 EIGEN
- **Binance Megadrop**: 50-500 BNB

### 2. Bot Farming
- **Notcoin**: 0.1-1 TON/day
- **Hamster Kombat**: 100-1000 coins/day
- **Blum**: 50-500 points/day
- **Major**: 10-100 points/day
- **TapSwap**: 100-500 points/day
- **Yescoin**: 100-1000 points/day
- **Pixelverse**: 50-200 coins/day
- **Catizen**: 50-300 coins/day
- **Time Farm**: 0.01-0.1 TON/day

### 3. Daily Earnings
- Check-in: +10 points/day
- Channel join: +30 points
- Bot start: +20 points
- Referral: +100 points per friend
- Airdrop complete: +50 points

### 4. Trading Signals
- Live market analysis
- Buy/Sell/Hold signals
- Portfolio tracking
- Price alerts

## Architecture

```
Telegram User
     ↓
HERMES Agent (hermes.py)
     ↓
┌─────────────────────────────────────────────┐
│  Money Engine                               │
│  ├── TON Wallet Manager                     │
│  ├── Airdrop Farmer                         │
│  ├── Bot Farmer                             │
│  ├── Trading Signals                        │
│  └── Earnings Tracker                       │
├─────────────────────────────────────────────┤
│  AI Engine                                  │
│  ├── Qwen 2.5 7B (local)                   │
│  ├── RAG Server (9092)                      │
│  └── AirLLM (9093)                          │
├─────────────────────────────────────────────┤
│  Infrastructure                             │
│  ├── Proxy API (8090)                       │
│  ├── Control Plane (9090)                   │
│  ├── GitHub Server (9094)                   │
│  ├── Mini App Agent (9095)                  │
│  └── ADB Bridge (9091)                      │
└─────────────────────────────────────────────┘
```

## Commands

### Earning
- `/earn` - Money dashboard
- `/wallet` - TON wallet management
- `/airdrop` - Active airdrops
- `/botfarm` - Bot farming
- `/trading` - Trading signals
- `/referral` - Referral link
- `/balance` - Check balance

### System
- `/terminal` - Shell terminal
- `/ai` - AI chat
- `/status` - System status
- `/servers` - Server management
- `/help` - All commands

## Money Generation Strategy

### Daily Routine
1. **Check-in**: +10 points
2. **Bot farming**: Start all 10 bots = ~500 points/day
3. **Airdrops**: Complete 3-5 airdrops = ~200 points/day
4. **Referrals**: Share link = +100 per referral
5. **Trading**: Follow signals for profit

### Estimated Daily Earnings
- Bot farming: 500-1000 points
- Airdrops: 200-500 points
- Tasks: 100-200 points
- **Total: 800-1700 points/day**

### Monthly Projection
- Low: 24,000 points
- Medium: 36,000 points
- High: 51,000 points

## Setup

```bash
# Start HERMES
cd /root/telegram-bridge
python3 hermes.py

# Or use keep-alive
bash keepalive.sh
```

## Files
- `hermes.py` - Main agent
- `hermes.md` - This documentation
- `proxy_api_os.py` - LLM proxy
- `airllm_server.py` - Multi-model serving
- `rag_server.py` - Knowledge base
- `miniapp_agent.py` - Mini app backend
- `github_server.py` - GitHub integration
- `control_plane.py` - Service control
- `adb_bridge.py` - Android bridge

## Keep-Alive
All services monitored every 3 minutes via cron.
Auto-restart on failure.

## Security
- No passwords stored
- OAuth tokens only
- API keys in .env
- Redis for session storage
- In-memory RAG (no disk)
