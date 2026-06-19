#!/usr/bin/env python3
"""
OWL Telegram Bridge - Persistent Bot Handler
=============================================
Connects Telegram API + Termux API + WiFi API into a single
self-healing bridge that keeps the bot alive and responsive.

Features:
- Long-polling Telegram updates with auto-reconnect
- Local LLM fallback (llama-server on :11434)
- Termux API integration (battery, WiFi, notifications)
- WiFi connection monitoring
- Auto-restart on failure
- Health check endpoint
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
import urllib.parse
import urllib.error
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_TOKEN="8842777172:AAEY5MyG4d8gzrxUA_yNelj5eM-YYL6hMuo"  # From .env
TELEGRAM_API = "api.telegram.org"
LLM_URL = "http://localhost:11434"
LOG_FILE = "/tmp/telegram-bridge.log"
HEALTH_PORT = 9191  # Local health check HTTP server
POLL_TIMEOUT = 30  # seconds for long-polling
RECONNECT_DELAY = 5  # seconds between reconnects
MAX_RECONNECT_DELAY = 60

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("owl-bridge")

# ============================================================
# TELEGRAM API
# ============================================================

class TelegramAPI:
    """Direct HTTPS calls to Telegram Bot API - no external deps."""

    def __init__(self, token):
        self.token = token
        self.offset = 0
        self._conn = None

    def _request(self, method, data=None, timeout=30):
        """Make HTTPS request to Telegram API."""
        path = f"/bot{self.token}/{method}"
        body = None
        if data:
            body = json.dumps(data).encode('utf-8')

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
                else:
                    log.warning(f"Telegram API error: {result}")
                    return None
            except (http.client.HTTPException, ConnectionError, OSError, json.JSONDecodeError) as e:
                log.warning(f"Telegram API attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return None

    def get_me(self):
        return self._request("getMe")

    def get_updates(self, timeout=POLL_TIMEOUT):
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
        data = {
            "chat_id": chat_id,
            "text": text[:4096],  # Telegram limit
            "parse_mode": parse_mode,
        }
        if reply_to:
            data["reply_to_message_id"] = reply_to
        return self._request("sendMessage", data=data)

    def send_chat_action(self, chat_id, action="typing"):
        return self._request("sendChatAction", data={"chat_id": chat_id, "action": action})

    def set_webhook(self, url=None):
        """Set or clear webhook."""
        if url:
            return self._request("setWebhook", data={"url": url})
        return self._request("deleteWebhook")


# ============================================================
# LOCAL LLM (llama-server)
# ============================================================

class LocalLLM:
    """Talks to llama-server on localhost:11434."""

    def __init__(self, base_url=LLM_URL):
        self.base_url = base_url
        self.available = False
        self._check()

    def _check(self):
        try:
            conn = http.client.HTTPConnection("localhost", 11434, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            self.available = resp.status == 200
        except:
            self.available = False
        log.info(f"Local LLM available: {self.available}")
        return self.available

    def chat(self, messages, max_tokens=512, temperature=0.7):
        """Send chat completion request to local LLM."""
        if not self.available:
            if not self._check():
                return None

        body = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }).encode('utf-8')

        try:
            conn = http.client.HTTPConnection("localhost", 11434, timeout=120)
            conn.request("POST", "/v1/chat/completions", body=body,
                        headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            result = json.loads(resp.read().decode('utf-8'))
            conn.close()

            if "choices" in result and result["choices"]:
                return result["choices"][0].get("message", {}).get("content", "")
            return None
        except Exception as e:
            log.error(f"LLM request failed: {e}")
            self.available = False
            return None


# ============================================================
# TERMUX API
# ============================================================

class TermuxAPI:
    """Interface to Termux API commands."""

    @staticmethod
    def run(cmd, timeout=10):
        """Run a termux-* command."""
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    @classmethod
    def battery_status(cls):
        out = cls.run("termux-battery-status")
        if out:
            try:
                return json.loads(out)
            except:
                pass
        return None

    @classmethod
    def wifi_status(cls):
        out = cls.run("termux-wifi-connectioninfo")
        if out:
            try:
                return json.loads(out)
            except:
                pass
        return None

    @classmethod
    def wifi_enable(cls, enable=True):
        cls.run(f"termux-wifi-enable {str(enable).lower()}")

    @classmethod
    def notify(cls, title, content, id="owl-bridge"):
        cls.run(f'termux-notification --title "{title}" --content "{content}" --id "{id}"')

    @classmethod
    def toast(cls, text):
        cls.run(f'termux-toast "{text}"')

    @classmethod
    def get_ip(cls):
        """Get device IP address."""
        out = cls.run("ip route get 1.1.1.1 2>/dev/null | head -1 | awk '{print $7}'")
        if out:
            return out.strip()
        out = cls.run("hostname -I 2>/dev/null | awk '{print $1}'")
        return out.strip() if out else "unknown"

    @classmethod
    def is_available(cls):
        """Check if termux-api is installed."""
        return cls.run("which termux-battery-status") is not None


# ============================================================
# WIFI CONNECTION MONITOR
# ============================================================

class WiFiMonitor:
    """Monitors WiFi connection and auto-recovers."""

    def __init__(self, termux):
        self.termux = termux
        self.last_check = 0
        self.check_interval = 30

    def check(self):
        now = time.time()
        if now - self.last_check < self.check_interval:
            return True
        self.last_check = now

        # Check internet connectivity
        try:
            conn = http.client.HTTPSConnection("8.8.8.8", timeout=5)
            conn.request("GET", "/")
            conn.close()
            return True
        except:
            pass

        # Try termux WiFi toggle
        if self.termux.is_available():
            log.warning("WiFi down - attempting termux-wifi-enable")
            self.termux.wifi_enable(False)
            time.sleep(2)
            self.termux.wifi_enable(True)
            time.sleep(5)

        return False


# ============================================================
# HEALTH CHECK HTTP SERVER
# ============================================================

class HealthServer:
    """Simple HTTP server for health checks."""

    def __init__(self, port, bridge):
        self.port = port
        self.bridge = bridge
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info(f"Health server on port {self.port}")

    def _run(self):
        import http.server
        bridge = self.bridge

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status = {
                    "status": "ok",
                    "uptime": time.time() - bridge.start_time,
                    "telegram": bridge.telegram_available,
                    "llm": bridge.llm.available,
                    "termux": bridge.termux.is_available(),
                    "wifi": bridge.wifi.check(),
                    "timestamp": datetime.now().isoformat(),
                }
                body = json.dumps(status, indent=2).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                pass  # Suppress default logging

        try:
            server = http.server.HTTPServer(("0.0.0.0", self.port), Handler)
            server.serve_forever()
        except Exception as e:
            log.error(f"Health server error: {e}")


# ============================================================
# MESSAGE HANDLER
# ============================================================

class MessageHandler:
    """Processes incoming Telegram messages."""

    def __init__(self, tg, llm, termux):
        self.tg = tg
        self.llm = llm
        self.termux = termux
        self.chat_sessions = {}  # chat_id -> [messages]

    def handle(self, update):
        if "message" not in update:
            return

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        msg_id = msg.get("message_id")
        user = msg.get("from", {})
        username = user.get("username", user.get("first_name", "unknown"))

        log.info(f"Message from @{username} in {chat_id}: {text[:80]}")

        # Command handling
        if text.startswith("/"):
            self._handle_command(chat_id, text, msg_id, username)
            return

        # Regular message -> respond via LLM or echo
        self.tg.send_chat_action(chat_id, "typing")

        # Try local LLM first
        response = None
        if self.llm.available:
            # Build conversation context
            if chat_id not in self.chat_sessions:
                self.chat_sessions[chat_id] = [
                    {"role": "system", "content": "You are OWL, an AI assistant running on Termus/Android. Be helpful, concise, and bilingual (Arabic/English)."}
                ]
            self.chat_sessions[chat_id].append({"role": "user", "content": text})

            # Keep last 20 messages
            if len(self.chat_sessions[chat_id]) > 21:
                self.chat_sessions[chat_id] = [self.chat_sessions[chat_id][0]] + self.chat_sessions[chat_id][-20:]

            response = self.llm.chat(self.chat_sessions[chat_id])
            if response:
                self.chat_sessions[chat_id].append({"role": "assistant", "content": response})

        if not response:
            response = f"🦉 OWL Bridge Active\n\nYour message: {text}\n\nLocal LLM: {'✅' if self.llm.available else '❌'}\nTermux API: {'✅' if self.termux.is_available() else '❌'}"

        self.tg.send_message(chat_id, response, reply_to=msg_id)

    def _handle_command(self, chat_id, text, msg_id, username):
        cmd = text.split()[0].lower().split('@')[0]

        if cmd == "/start":
            self.tg.send_message(chat_id,
                "🦉 <b>OWL Bridge Bot</b>\n\n"
                "I'm your persistent AI bridge. I never sleep.\n\n"
                "Commands:\n"
                "/status - System status\n"
                "/health - Health check\n"
                "/battery - Battery level\n"
                "/wifi - WiFi info\n"
                "/ip - Device IP\n"
                "/restart - Restart bridge\n"
                "/help - Show help\n\n"
                "Or just chat with me! 🐍",
                reply_to=msg_id
            )

        elif cmd == "/status":
            batt = self.termux.battery_status()
            wifi = self.termux.wifi_status()
            batt_str = f"{batt.get('percentage', '?')}%" if batt else "N/A"
            wifi_str = wifi.get("ssid", "N/A") if wifi else "N/A"

            status = (
                f"📊 <b>System Status</b>\n\n"
                f"🟢 Bridge: Active\n"
                f"🤖 LLM: {'Online' if self.llm.available else 'Offline'}\n"
                f"📱 Termux API: {'Available' if self.termux.is_available() else 'Unavailable'}\n"
                f"🔋 Battery: {batt_str}\n"
                f"📶 WiFi: {wifi_str}\n"
                f"🌐 IP: {self.termux.get_ip()}\n"
                f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
            )
            self.tg.send_message(chat_id, status, reply_to=msg_id)

        elif cmd == "/health":
            self.tg.send_message(chat_id,
                f"✅ <b>Health Check</b>\n\n"
                f"Telegram API: {'✅' if self.tg.get_me() else '❌'}\n"
                f"Local LLM: {'✅' if self.llm.available else '❌'}\n"
                f"Termux API: {'✅' if self.termux.is_available() else '❌'}\n"
                f"Uptime: {int(time.time() - self.start_time)}s",
                reply_to=msg_id
            )

        elif cmd == "/battery":
            batt = self.termux.battery_status()
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
                self.tg.send_message(chat_id, "❌ Termux API not available", reply_to=msg_id)

        elif cmd == "/wifi":
            wifi = self.termux.wifi_status()
            if wifi:
                self.tg.send_message(chat_id,
                    f"📶 <b>WiFi Info</b>\n\n"
                    f"SSID: {wifi.get('ssid', 'N/A')}\n"
                    f"BSSID: {wifi.get('bssid', 'N/A')}\n"
                    f"IP: {wifi.get('ip', 'N/A')}\n"
                    f"Speed: {wifi.get('link_speed_mbps', 'N/A')} Mbps\n"
                    f"Signal: {wifi.get('rssi', 'N/A')} dBm",
                    reply_to=msg_id
                )
            else:
                self.tg.send_message(chat_id, "❌ WiFi info unavailable", reply_to=msg_id)

        elif cmd == "/ip":
            ip = self.termux.get_ip()
            self.tg.send_message(chat_id, f"🌐 <b>Device IP:</b> {ip}", reply_to=msg_id)

        elif cmd == "/restart":
            self.tg.send_message(chat_id, "🔄 Restarting bridge...", reply_to=msg_id)
            os.execv(sys.executable, [sys.executable] + sys.argv)

        elif cmd == "/help":
            self.tg.send_message(chat_id,
                "📖 <b>OWL Bridge Help</b>\n\n"
                "This bot is a persistent bridge between:\n"
                "• Telegram API\n"
                "• Termux API (Android)\n"
                "• WiFi Connection Monitor\n"
                "• Local LLM (Phi-3)\n\n"
                "It auto-heals and never stops.\n"
                "Send any message to chat with the local AI.",
                reply_to=msg_id
            )

        else:
            self.tg.send_message(chat_id, f"Unknown command: {text}", reply_to=msg_id)


# ============================================================
# MAIN BRIDGE
# ============================================================

class OWLBridge:
    """Main bridge orchestrator."""

    def __init__(self):
        self.start_time = time.time()
        self.running = True
        self.telegram_available = False

        # Initialize components
        log.info("=" * 50)
        log.info("OWL Telegram Bridge Starting...")
        log.info("=" * 50)

        self.tg = TelegramAPI(TELEGRAM_TOKEN)
        self.llm = LocalLLM()
        self.termux = TermuxAPI()
        self.wifi = WiFiMonitor(self.termux)
        self.handler = MessageHandler(self.tg, self.llm, self.termux)
        self.handler.start_time = self.start_time
        self.health = HealthServer(HEALTH_PORT, self)

        # Verify Telegram
        me = self.tg.get_me()
        if me:
            self.telegram_available = True
            log.info(f"Telegram bot: @{me.get('username')} ({me.get('first_name')})")
        else:
            log.error("Telegram API unreachable!")

        # Clear any existing webhook (we use long-polling)
        self.tg.set_webhook(None)
        log.info("Webhook cleared - using long-polling")

        # Start health server
        self.health.start()

        # Signal handlers
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        log.info("Shutdown signal received")
        self.running = False

    def run(self):
        """Main loop - long-poll Telegram for updates."""
        log.info("Entering main polling loop...")
        reconnect_delay = RECONNECT_DELAY

        while self.running:
            try:
                updates = self.tg.get_updates(timeout=POLL_TIMEOUT)
                reconnect_delay = RECONNECT_DELAY  # Reset on success

                for update in updates:
                    try:
                        self.handler.handle(update)
                    except Exception as e:
                        log.error(f"Error handling update: {e}")

                # Periodic WiFi check
                self.wifi.check()

            except KeyboardInterrupt:
                log.info("Interrupted by user")
                break
            except Exception as e:
                log.error(f"Polling error: {e}")
                log.info(f"Reconnecting in {reconnect_delay}s...")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)

        log.info("Bridge stopped.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    bridge = OWLBridge()
    bridge.run()
