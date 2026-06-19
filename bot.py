#!/usr/bin/env python3
"""
OWL Telegram Bot - Unified Access to ALL Services
===================================================
Direct access to all ports/services through Telegram.
No need to visit individual ports - everything flows through the bot.

Services accessible:
- LLM Chat (qwen 7B, cloud models)
- Code Server (port 8888)
- Web Portal (port 3000)
- nginx (port 8081)
- WebSocket Bridge (port 8082)
- Redis (port 6379)
- ADB (port 5037)
- OpenClaw (port 18789)
- Hermes Proxy API (port 8090)
- Control Plane (port 9090)
- Termux API (battery, WiFi, notifications)
- WiFi Monitor
"""

import os
import sys
import json
import time
import signal
import logging
import threading
import subprocess
import http.client
import urllib.request
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_TOKEN = None  # Loaded from env file below

def _load_token():
    """Load token from env file to avoid shell escaping issues."""
    try:
        with open('/root/.hermes/.env', 'r') as f:
            for line in f:
                if line.strip().startswith('TELEGRAM_BOT_TOKEN'):
                    return line.strip().split('=', 1)[1]
    except:
        pass
    return ""

TELEGRAM_TOKEN = _load_token()
TELEGRAM_API = "api.telegram.org"
PROXY_URL = "http://127.0.0.1:8090"
CONTROL_URL = "http://127.0.0.1:9090"
LOG_FILE = "/tmp/owl-telegram-bot.log"

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("owl-bot")

# ============================================================
# TELEGRAM API
# ============================================================

class TelegramAPI:
    def __init__(self, token):
        self.token = token
        self.offset = 0

    def _request(self, method, data=None, timeout=30):
        path = f"/bot{self.token}/{method}"
        body = json.dumps(data).encode('utf-8') if data else None
        headers = {"Content-Type": "application/json"}

        for attempt in range(3):
            try:
                conn = http.client.HTTPSConnection(TELEGRAM_API, timeout=timeout)
                conn.request("POST" if body else "GET", path, body=body, headers=headers)
                resp = conn.getresponse()
                result = json.loads(resp.read().decode('utf-8'))
                conn.close()
                if result.get("ok"):
                    return result.get("result")
                return None
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return None

    def get_me(self):
        return self._request("getMe")

    def get_updates(self, timeout=30):
        data = {"timeout": timeout, "allowed_updates": ["message"]}
        if self.offset:
            data["offset"] = self.offset
        result = self._request("getUpdates", data=data, timeout=timeout + 10)
        if result:
            for update in result:
                if "update_id" in update:
                    self.offset = update["update_id"] + 1
        return result or []

    def send_message(self, chat_id, text, reply_to=None, parse_mode="HTML"):
        data = {"chat_id": chat_id, "text": text[:4096], "parse_mode": parse_mode}
        if reply_to:
            data["reply_to_message_id"] = reply_to
        return self._request("sendMessage", data=data)

    def send_chat_action(self, chat_id, action="typing"):
        return self._request("sendChatAction", data={"chat_id": chat_id, "action": action})


# ============================================================
# SERVICE ACCESS LAYER
# ============================================================

class ServiceAccess:
    """Unified access to all local services."""

    @staticmethod
    def _http_get(url, timeout=10):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except:
            return None

    @staticmethod
    def _http_post(url, data, timeout=30):
        try:
            body = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(url, data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return {"error": str(e)}

    # --- Proxy API ---
    def proxy_status(self):
        return self._http_get(f"{PROXY_URL}/api/v1/status")

    def proxy_models(self):
        return self._http_get(f"{PROXY_URL}/api/v1/models")

    def proxy_chat(self, messages, model="qwen-7b", max_tokens=512):
        return self._http_post(f"{PROXY_URL}/api/v1/chat/completions", {
            "model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": 0.7
        }, timeout=120)

    def proxy_switch_model(self, model):
        return self._http_post(f"{PROXY_URL}/api/v1/local/switch", {"model": model})

    # --- Control Plane ---
    def control_status(self):
        return self._http_get(f"{CONTROL_URL}/status")

    # --- Direct Service Access ---
    def service_status(self, port):
        return self._http_get(f"http://127.0.0.1:{port}/")

    # --- Termux ---
    def termux(self, cmd, timeout=10):
        try:
            r = subprocess.run(f"termux-{cmd}", shell=True, capture_output=True,
                             text=True, timeout=timeout)
            return r.stdout.strip() if r.returncode == 0 else None
        except:
            return None

    def termux_battery(self):
        out = self.termux("battery-status")
        return json.loads(out) if out else None

    def termux_wifi(self):
        out = self.termux("wifi-connectioninfo")
        return json.loads(out) if out else None

    # --- ADB Bridge ---
    def adb_bridge(self, action, **kwargs):
        """Access ADB bridge API."""
        if action == "devices":
            return self._http_get("http://127.0.0.1:9091/devices")
        elif action == "info":
            return self._http_get("http://127.0.0.1:9091/info")
        elif action == "scan":
            return self._http_get("http://127.0.0.1:9091/scan")
        elif action == "connect":
            return self._http_post("http://127.0.0.1:9091/connect", {"ip": kwargs.get("ip", ""), "port": kwargs.get("port", 5555)})
        elif action == "shell":
            return self._http_post("http://127.0.0.1:9091/shell", {"cmd": kwargs.get("cmd", "")})
        return {"error": f"Unknown ADB action: {action}"}

    # --- System ---
    def system_info(self):
        info = {}
        try:
            r = subprocess.run("free -h", shell=True, capture_output=True, text=True)
            for line in r.stdout.split("\n"):
                if "Mem:" in line:
                    parts = line.split()
                    info["memory"] = f"{parts[2]}/{parts[1]}"
                elif "Swap:" in line:
                    parts = line.split()
                    info["swap"] = f"{parts[2]}/{parts[1]}"
        except: pass
        try:
            r = subprocess.run("df -h / | tail -1", shell=True, capture_output=True, text=True)
            parts = r.stdout.split()
            info["disk"] = f"{parts[2]}/{parts[3]} ({parts[4]})"
        except: pass
        try:
            with open('/proc/loadavg') as f:
                info["load"] = f.read().strip().split()[:3]
        except: pass
        try:
            r = subprocess.run("hostname -I", shell=True, capture_output=True, text=True)
            info["ip"] = r.stdout.strip()
        except: pass
        return info


# ============================================================
# MESSAGE HANDLER
# ============================================================

class BotHandler:
    def __init__(self):
        self.tg = TelegramAPI(TELEGRAM_TOKEN)
        self.svc = ServiceAccess()
        self.sessions = {}  # chat_id -> {"model": str, "history": []}

    def handle(self, update):
        if "message" not in update:
            return

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()
        msg_id = msg.get("message_id")
        user = msg.get("from", {})
        name = user.get("first_name", "User")

        if not text:
            return

        log.info(f"[{chat_id}] {name}: {text[:80]}")

        # Initialize session
        if chat_id not in self.sessions:
            self.sessions[chat_id] = {"model": "qwen-7b", "history": []}

        # Commands
        if text.startswith("/"):
            self._command(chat_id, text, msg_id, name)
            return

        # Regular message -> LLM chat
        self._chat(chat_id, text, msg_id)

    def _command(self, chat_id, text, msg_id, name):
        cmd = text.split()[0].lower().split('@')[0]
        args = text[len(cmd):].strip()

        if cmd == "/start":
            self.tg.send_message(chat_id,
                "🦉 <b>OWL Unified Bot</b>\n\n"
                "I give you direct access to ALL services:\n\n"
                "📊 /status - Full system status\n"
                "🤖 /models - List LLM models\n"
                "💬 /chat &lt;message&gt; - Chat with AI\n"
                "🔄 /switch &lt;model&gt; - Switch model\n"
                "💻 /code - Code Server (8888)\n"
                "🌐 /portal - Web Portal (3000)\n"
                "📡 /nginx - nginx status (8081)\n"
                "🔌 /ws - WebSocket bridge (8082)\n"
                "🗄️ /redis - Redis status (6379)\n"
                "📱 /adb - ADB devices (5037)\n"
                "🦾 /openclaw - OpenClaw (18789)\n"
                "🔋 /battery - Battery status\n"
                "📶 /wifi - WiFi info\n"
                "🌍 /ip - Device IP\n"
                "💾 /system - System info\n"
                "🔧 /shell &lt;cmd&gt; - Run shell command\n"
                "📋 /help - Show all commands\n\n"
                "Or just type to chat with AI! 🐍",
                reply_to=msg_id
            )

        elif cmd == "/help":
            self.tg.send_message(chat_id,
                "📖 <b>OWL Bot Commands</b>\n\n"
                "<b>AI Chat:</b>\n"
                "/chat &lt;msg&gt; - Chat with current model\n"
                "/switch &lt;model&gt; - Switch LLM model\n"
                "/models - List all models\n\n"
                "<b>Services:</b>\n"
                "/status - Proxy API status\n"
                "/code - Open Code Server\n"
                "/portal - Open Web Portal\n"
                "/nginx - nginx status\n"
                "/redis - Redis status\n"
                "/adb - ADB devices\n"
                "/openclaw - OpenClaw status\n\n"
                "<b>Device:</b>\n"
                "/battery - Battery level\n"
                "/wifi - WiFi info\n"
                "/ip - Device IP\n"
                "/system - System info\n"
                "/shell &lt;cmd&gt; - Run command",
                reply_to=msg_id
            )

        elif cmd == "/status":
            status = self.svc.proxy_status()
            if status:
                self.tg.send_message(chat_id,
                    f"📊 <b>Proxy API Status</b>\n\n"
                    f"Status: {status.get('status', '?')}\n"
                    f"Uptime: {status.get('uptime_human', '?')}\n"
                    f"Requests: {status.get('total_requests', 0)}\n"
                    f"Errors: {status.get('error_rate', '0%')}\n"
                    f"Local LLM: {'✅' if status.get('local_llm', {}).get('running') else '❌'}\n"
                    f"Active Model: {status.get('local_llm', {}).get('active_model', 'None')}\n"
                    f"Models: {status.get('models', {}).get('total', 0)} total "
                    f"({status.get('models', {}).get('local', 0)} local, "
                    f"{status.get('models', {}).get('cloud', 0)} cloud)\n"
                    f"API Keys: OpenRouter={'✅' if status.get('api_keys', {}).get('openrouter') else '❌'} "
                    f"Google={'✅' if status.get('api_keys', {}).get('google') else '❌'}",
                    reply_to=msg_id
                )
            else:
                self.tg.send_message(chat_id, "❌ Proxy API unavailable", reply_to=msg_id)

        elif cmd == "/models":
            models = self.svc.proxy_models()
            if models and "data" in models:
                lines = ["🤖 <b>Available Models</b>\n"]
                for m in models["data"]:
                    avail = "✅" if m["available"] else "❌"
                    cost = "FREE" if m["cost_per_1k"] == 0 else f"${m['cost_per_1k']}/1K"
                    lines.append(f"{avail} <b>{m['name']}</b> ({m['provider']}) - {cost}")
                self.tg.send_message(chat_id, "\n".join(lines), reply_to=msg_id)
            else:
                self.tg.send_message(chat_id, "❌ Could not fetch models", reply_to=msg_id)

        elif cmd == "/switch":
            if args:
                result = self.svc.proxy_switch_model(args)
                if result and result.get("success"):
                    self.sessions[chat_id]["model"] = args
                    self.tg.send_message(chat_id, f"✅ Switched to <b>{args}</b>", reply_to=msg_id)
                else:
                    self.tg.send_message(chat_id, f"❌ {result.get('message', 'Failed')}", reply_to=msg_id)
            else:
                self.tg.send_message(chat_id, "Usage: /switch <model_name>", reply_to=msg_id)

        elif cmd == "/chat":
            if args:
                self._chat(chat_id, args, msg_id)
            else:
                self.tg.send_message(chat_id, "Usage: /chat <message>", reply_to=msg_id)

        elif cmd == "/code":
            self.tg.send_message(chat_id,
                "💻 <b>Code Server</b>\n\n"
                "Access VS Code in browser:\n"
                f"http://{self._get_ip()}:8888\n\n"
                "Password: owlserver2026",
                reply_to=msg_id
            )

        elif cmd == "/portal":
            self.tg.send_message(chat_id,
                "🌐 <b>Web Portal</b>\n\n"
                f"http://{self._get_ip()}:3000",
                reply_to=msg_id
            )

        elif cmd == "/nginx":
            status = self.svc.service_status(8081)
            self.tg.send_message(chat_id,
                f"📡 <b>nginx</b>\n\n"
                f"Status: {'✅ Running' if status else '❌ Down'}\n"
                f"URL: http://{self._get_ip()}:8081",
                reply_to=msg_id
            )

        elif cmd == "/redis":
            try:
                r = subprocess.run("redis-cli ping", shell=True, capture_output=True, text=True, timeout=5)
                status = "✅ PONG" if "PONG" in r.stdout else "❌ Down"
            except:
                status = "❌ Down"
            self.tg.send_message(chat_id, f"🗄️ <b>Redis</b>\n\nStatus: {status}", reply_to=msg_id)

        elif cmd == "/ws":
            self.tg.send_message(chat_id,
                "🔌 <b>WebSocket Bridge</b>\n\n"
                f"ws://{self._get_ip()}:8082",
                reply_to=msg_id
            )

        elif cmd == "/adb":
            devices = self.svc.adb_bridge("devices")
            if devices:
                lines = ["📱 <b>ADB Devices</b>\n"]
                for d in devices:
                    lines.append(f"📱 {d['serial']} ({d['state']})")
                self.tg.send_message(chat_id, "\n".join(lines), reply_to=msg_id)
            else:
                self.tg.send_message(chat_id, "📱 <b>ADB</b>\n\nNo devices connected\n\nUse /adb_scan to search network", reply_to=msg_id)

        elif cmd == "/adb_scan":
            self.tg.send_message(chat_id, "🔍 Scanning network for ADB devices...", reply_to=msg_id)
            result = self.svc.adb_bridge("scan")
            devices = result.get("devices", [])
            if devices:
                lines = ["🔍 <b>Found ADB Devices</b>\n"]
                for ip in devices:
                    lines.append(f"📱 {ip}:5555")
                self.tg.send_message(chat_id, "\n".join(lines), reply_to=msg_id)
            else:
                self.tg.send_message(chat_id, "❌ No ADB devices found on network", reply_to=msg_id)

        elif cmd == "/adb_connect":
            if args:
                parts = args.split(":")
                ip = parts[0]
                port = int(parts[1]) if len(parts) > 1 else 5555
                result = self.svc.adb_bridge("connect", ip=ip, port=port)
                self.tg.send_message(chat_id,
                    f"✅ Connected to {ip}:{port}" if result.get("success") else f"❌ Failed to connect to {ip}:{port}",
                    reply_to=msg_id)
            else:
                self.tg.send_message(chat_id, "Usage: /adb_connect <ip>:<port>", reply_to=msg_id)

        elif cmd == "/openclaw":
            status = self.svc.service_status(18789)
            self.tg.send_message(chat_id,
                f"🦾 <b>OpenClaw</b>\n\n"
                f"Status: {'✅ Running' if status else '❌ Down'}\n"
                f"URL: http://{self._get_ip()}:18789",
                reply_to=msg_id
            )

        elif cmd == "/battery":
            batt = self.svc.termux_battery()
            if batt:
                self.tg.send_message(chat_id,
                    f"🔋 <b>Battery</b>\n\n"
                    f"Level: {batt.get('percentage', '?')}%\n"
                    f"Status: {batt.get('status', '?')}\n"
                    f"Temp: {batt.get('temperature', '?')}°C\n"
                    f"Health: {batt.get('health', '?')}",
                    reply_to=msg_id
                )
            else:
                self.tg.send_message(chat_id, "❌ Termux API unavailable", reply_to=msg_id)

        elif cmd == "/wifi":
            wifi = self.svc.termux_wifi()
            if wifi:
                self.tg.send_message(chat_id,
                    f"📶 <b>WiFi</b>\n\n"
                    f"SSID: {wifi.get('ssid', 'N/A')}\n"
                    f"IP: {wifi.get('ip', 'N/A')}\n"
                    f"Signal: {wifi.get('rssi', 'N/A')} dBm\n"
                    f"Speed: {wifi.get('link_speed_mbps', 'N/A')} Mbps",
                    reply_to=msg_id
                )
            else:
                self.tg.send_message(chat_id, "❌ WiFi info unavailable", reply_to=msg_id)

        elif cmd == "/ip":
            info = self.svc.system_info()
            self.tg.send_message(chat_id,
                f"🌍 <b>Network</b>\n\n"
                f"IP: {info.get('ip', 'N/A')}",
                reply_to=msg_id
            )

        elif cmd == "/system":
            info = self.svc.system_info()
            self.tg.send_message(chat_id,
                f"💾 <b>System Info</b>\n\n"
                f"Memory: {info.get('memory', 'N/A')}\n"
                f"Swap: {info.get('swap', 'N/A')}\n"
                f"Disk: {info.get('disk', 'N/A')}\n"
                f"Load: {', '.join(info.get('load', ['N/A']))}\n"
                f"IP: {info.get('ip', 'N/A')}",
                reply_to=msg_id
            )

        elif cmd == "/shell":
            if args:
                # Try ADB first, then local shell
                adb_result = self.svc.adb_bridge("shell", cmd=args)
                if adb_result and "output" in adb_result:
                    out = adb_result["output"]
                else:
                    try:
                        r = subprocess.run(args, shell=True, capture_output=True, text=True, timeout=30)
                        out = r.stdout.strip() or r.stderr.strip()
                    except Exception as e:
                        out = str(e)
                self.tg.send_message(chat_id,
                    f"🔧 <b>Shell</b>\n\n<code>{out[:3000]}</code>",
                    reply_to=msg_id
                )
            else:
                self.tg.send_message(chat_id, "Usage: /shell <command>", reply_to=msg_id)

        else:
            self.tg.send_message(chat_id, f"Unknown command: {text}\nType /help for commands.", reply_to=msg_id)

    def _chat(self, chat_id, text, msg_id):
        """Handle chat message through proxy API."""
        self.tg.send_chat_action(chat_id, "typing")

        session = self.sessions[chat_id]
        model = session["model"]

        # Build messages
        history = session["history"]
        history.append({"role": "user", "content": text})
        if len(history) > 20:
            history = history[-20:]
        session["history"] = history

        result = self.svc.proxy_chat(history, model)

        if result and "error" in result:
            # Fallback: try with a different model
            fallback = "gemini-2.5-flash" if model != "gemini-2.5-flash" else "qwen-7b"
            result = self.svc.proxy_chat(history, fallback)
            if result and "error" not in result:
                model = fallback

        if result and "choices" in result:
            response = result["choices"][0]["message"]["content"]
            session["history"].append({"role": "assistant", "content": response})
            self.tg.send_message(chat_id, response, reply_to=msg_id)
        elif result and "error" in result:
            self.tg.send_message(chat_id,
                f"❌ <b>Error</b>\n\n{result['error']}\n\n"
                f"Try /switch to change model or /models to see available models.",
                reply_to=msg_id
            )
        else:
            self.tg.send_message(chat_id, "❌ No response from AI. Try again.", reply_to=msg_id)

    def _get_ip(self):
        try:
            r = subprocess.run("hostname -I", shell=True, capture_output=True, text=True)
            return r.stdout.strip().split()[0]
        except:
            return "localhost"


# ============================================================
# MAIN
# ============================================================

def main():
    log.info("=" * 60)
    log.info("OWL Telegram Bot Starting...")
    log.info("=" * 60)

    handler = BotHandler()

    # Verify Telegram
    me = handler.tg.get_me()
    if me:
        log.info(f"Bot: @{me.get('username')} ({me.get('first_name')})")
    else:
        log.error("Telegram API unreachable!")
        return

    # Clear webhook
    handler.tg._request("deleteWebhook")
    log.info("Using long-polling mode")

    log.info("Entering main loop...")

    reconnect_delay = 5
    while True:
        try:
            updates = handler.tg.get_updates(timeout=30)
            reconnect_delay = 5

            for update in updates:
                try:
                    handler.handle(update)
                except Exception as e:
                    log.error(f"Error handling update: {e}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"Polling error: {e}")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)

    log.info("Bot stopped.")


if __name__ == "__main__":
    main()
