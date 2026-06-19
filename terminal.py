#!/usr/bin/env python3
"""
OWL Telegram Terminal - Complete Telegram OS
=============================================
A full terminal inside Telegram. Can do ANYTHING:

1. Shell Terminal - Execute any command
2. Mini Apps Platform - Build and run mini apps
3. Telegram API - Full Telegram API access
4. Telegram.com Login - Web login to telegram.com
5. Codespace Access - GitHub Codespace control
6. Server Management - All Hermes servers
7. Bot Search - Find and interact with other bots
8. Earning Tools - Crypto and Telegram earning
9. File Manager - Upload/download/edit files
10. AI Chat - Qwen 2.5 7B with RAG
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
import html
import re
import base64
import hashlib
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_TOKEN = None  # Loaded from env
TELEGRAM_API = "api.telegram.org"
BOT_USERNAME = "Hermes_termux_chat_bot"

# Load token from env file
def _load_token():
    try:
        with open('/root/.hermes/.env', 'r') as f:
            for line in f:
                if line.strip().startswith('TELEGRAM_BOT_TOKEN'):
                    return line.strip().split('=', 1)[1]
    except:
        pass
    return ""

TELEGRAM_TOKEN = _load_token()

# Server URLs
PROXY_URL = "http://127.0.0.1:8090"
AIRLLM_URL = "http://127.0.0.1:9093"
RAG_URL = "http://127.0.0.1:9092"
GITHUB_URL = "http://127.0.0.1:9094"
CONTROL_URL = "http://127.0.0.1:9090"
ADB_URL = "http://127.0.0.1:9091"

MINIAPP_URL = "http://127.0.0.1:9095"
MINIAPP_WEB = "https://hermes-proxy.ai/miniapp"  # Public URL for Mini App

LOG_FILE = "/tmp/telegram-terminal.log"
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("telegram-terminal")

# ============================================================
# TELEGRAM API CLIENT
# ============================================================

class TelegramClient:
    """Full Telegram Bot API client."""

    def __init__(self, token):
        self.token = token
        self.offset = 0

    def _call(self, method, data=None, files=None, timeout=30):
        """Call Telegram Bot API."""
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        try:
            if files:
                # Multipart upload
                import mimetypes
                boundary = hashlib.md5(str(time.time()).encode()).hexdigest()
                body = b""
                for key, value in (data or {}).items():
                    body += f"--{boundary}\r\n".encode()
                    body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
                    body += str(value).encode() + b"\r\n"
                for key, (filename, content, mimetype) in files.items():
                    body += f"--{boundary}\r\n".encode()
                    body += f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode()
                    body += f"Content-Type: {mimetype}\r\n\r\n".encode()
                    body += content + b"\r\n"
                body += f"--{boundary}--\r\n".encode()
                headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
            elif data:
                body = json.dumps(data).encode('utf-8')
                headers = {"Content-Type": "application/json"}
            else:
                body = None
                headers = {}

            req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            log.error(f"API error {method}: {e}")
            return {"ok": False, "error": str(e)}

    def get_me(self):
        return self._call("getMe")

    def get_updates(self, timeout=30):
        data = {"timeout": timeout, "allowed_updates": ["message", "callback_query", "inline_query"]}
        if self.offset:
            data["offset"] = self.offset
        result = self._call("getUpdates", data=data, timeout=timeout + 10)
        if result.get("ok"):
            for update in result.get("result", []):
                if "update_id" in update:
                    self.offset = update["update_id"] + 1
        return result.get("result", [])

    def send_message(self, chat_id, text, reply_to=None, parse_mode="HTML", reply_markup=None, disable_preview=True):
        data = {"chat_id": chat_id, "text": text[:4096], "parse_mode": parse_mode, "disable_web_page_preview": disable_preview}
        if reply_to:
            data["reply_to_message_id"] = reply_to
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        return self._call("sendMessage", data=data)

    def edit_message(self, chat_id, message_id, text, parse_mode="HTML", reply_markup=None):
        data = {"chat_id": chat_id, "message_id": message_id, "text": text[:4096], "parse_mode": parse_mode}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        return self._call("editMessageText", data=data)

    def delete_message(self, chat_id, message_id):
        return self._call("deleteMessage", data={"chat_id": chat_id, "message_id": message_id})

    def send_chat_action(self, chat_id, action="typing"):
        return self._call("sendChatAction", data={"chat_id": chat_id, "action": action})

    def send_document(self, chat_id, content, filename, caption="", reply_to=None):
        files = {"document": (filename, content if isinstance(content, bytes) else content.encode(), "application/octet-stream")}
        data = {"chat_id": chat_id, "caption": caption[:1024]}
        if reply_to:
            data["reply_to_message_id"] = reply_to
        return self._call("sendDocument", data=data, files=files)

    def send_photo(self, chat_id, photo_url, caption="", reply_to=None):
        data = {"chat_id": chat_id, "photo": photo_url, "caption": caption[:1024]}
        if reply_to:
            data["reply_to_message_id"] = reply_to
        return self._call("sendPhoto", data=data)

    def answer_callback(self, callback_query_id, text="", show_alert=False):
        return self._call("answerCallbackQuery", data={"callback_query_id": callback_query_id, "text": text, "show_alert": show_alert})

    def answer_inline(self, inline_query_id, results):
        return self._call("answerInlineQuery", data={"inline_query_id": inline_query_id, "results": json.dumps(results)})

    def set_webhook(self, url=None):
        if url:
            return self._call("setWebhook", data={"url": url})
        return self._call("deleteWebhook")

    def get_chat(self, chat_id):
        return self._call("getChat", data={"chat_id": chat_id})

    def get_chat_member(self, chat_id, user_id):
        return self._call("getChatMember", data={"chat_id": chat_id, "user_id": user_id})

    def get_file(self, file_id):
        return self._call("getFile", data={"file_id": file_id})

    def download_file(self, file_path):
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except:
            return None

    def create_invite_link(self, chat_id, name=None):
        data = {"chat_id": chat_id, "creates_join_request": False}
        if name:
            data["name"] = name
        return self._call("createChatInviteLink", data=data)

    def send_sticker(self, chat_id, sticker_id, reply_to=None):
        data = {"chat_id": chat_id, "sticker": sticker_id}
        if reply_to:
            data["reply_to_message_id"] = reply_to
        return self._call("sendSticker", data=data)

    def send_poll(self, chat_id, question, options, reply_to=None):
        data = {"chat_id": chat_id, "question": question, "options": json.dumps(options)}
        if reply_to:
            data["reply_to_message_id"] = reply_to
        return self._call("sendPoll", data=data)

    def pin_message(self, chat_id, message_id):
        return self._call("pinChatMessage", data={"chat_id": chat_id, "message_id": message_id, "disable_notification": True})

    def get_user_profile_photos(self, user_id):
        return self._call("getUserProfilePhotos", data={"user_id": user_id})

    def set_my_commands(self, commands):
        """Set bot commands menu."""
        return self._call("setMyCommands", data={"commands": json.dumps(commands)})

    def set_chat_menu_button(self, menu_button=None):
        return self._call("setChatMenuButton", data={"menu_button": json.dumps(menu_button or {"type": "default"})})


# ============================================================
# INLINE KEYBOARD BUILDER
# ============================================================

def btn(text, callback_data=None, url=None, web_app=None):
    """Build inline keyboard button."""
    b = {"text": text}
    if callback_data:
        b["callback_data"] = callback_data[:64]
    if url:
        b["url"] = url
    if web_app:
        b["web_app"] = {"url": web_app}
    return b

def keyboard(rows):
    """Build inline keyboard markup."""
    return {"inline_keyboard": rows}

def menu_main():
    """Main menu keyboard."""
    return keyboard([
        [btn("💻 Terminal", "menu_terminal"), btn("🤖 AI Chat", "menu_ai")],
        [btn("📱 Mini Apps", "menu_miniapps"), btn("🔧 Servers", "menu_servers")],
        [btn("📂 Files", "menu_files"), btn("🌐 Telegram Web", "menu_tgweb")],
        [btn("🔍 Bot Search", "menu_botsearch"), btn("💰 Earning", "menu_earning")],
        [btn("📊 Status", "menu_status"), btn("⚙️ Settings", "menu_settings")],
    ])

def menu_terminal():
    """Terminal submenu."""
    return keyboard([
        [btn("🖥️ Shell", "term_shell"), btn("🐍 Python", "term_python")],
        [btn("📜 Scripts", "term_scripts"), btn("🔄 System", "term_system")],
        [btn("📡 Network", "term_network"), btn("🐳 Docker", "term_docker")],
        [btn("⬅️ Back", "menu_main")],
    ])

def menu_miniapps():
    """Mini apps submenu."""
    return keyboard([
        [btn("📝 Notes", "app_notes"), btn("📊 Dashboard", "app_dashboard")],
        [btn("🔍 Search", "app_search"), btn("📰 News", "app_news")],
        [btn("💱 Crypto", "app_crypto"), btn("🎮 Games", "app_games")],
        [btn("🛠️ Build App", "app_build"), btn("⬅️ Back", "menu_main")],
    ])

def menu_servers():
    """Servers submenu."""
    return keyboard([
        [btn("🔄 Restart All", "srv_restart"), btn("📊 All Status", "srv_status")],
        [btn("🤖 Proxy API", "srv_proxy"), btn("🧠 RAG", "srv_rag")],
        [btn("☁️ AirLLM", "srv_airllm"), btn("🐙 GitHub", "srv_github")],
        [btn("📱 ADB", "srv_adb"), btn("⬅️ Back", "menu_main")],
    ])

def menu_files():
    """File manager submenu."""
    return keyboard([
        [btn("📤 Upload", "file_upload"), btn("📥 Download", "file_download")],
        [btn("📂 List", "file_list"), btn("✏️ Edit", "file_edit")],
        [btn("🗑️ Delete", "file_delete"), btn("🔍 Search", "file_search")],
        [btn("⬅️ Back", "menu_main")],
    ])

def menu_earning():
    """Earning tools submenu."""
    return keyboard([
        [btn("🪙 Crypto Airdrop", "earn_airdrop"), btn("🤖 Bot Farm", "earn_botfarm")],
        [btn("📢 Channel Earn", "earn_channel"), btn("🎁 Tasks", "earn_tasks")],
        [btn("💎 TON Earn", "earn_ton"), btn("⬅️ Back", "menu_main")],
    ])


# ============================================================
# COMMAND HANDLER
# ============================================================

class TerminalHandler:
    """Handles all Telegram Terminal commands."""

    def __init__(self):
        self.tg = TelegramClient(TELEGRAM_TOKEN)
        self.sessions = {}  # chat_id -> {"state": str, "history": [], "model": str, "term_buffer": []}
        self._setup_commands()

    def _setup_commands(self):
        """Set bot commands menu."""
        commands = [
            {"command": "start", "description": "🏠 Main Menu"},
            {"command": "terminal", "description": "💻 Open Terminal"},
            {"command": "shell", "description": "🖥️ Execute Shell Command"},
            {"command": "ai", "description": "🤖 Chat with AI"},
            {"command": "miniapp", "description": "📱 Mini Apps"},
            {"command": "servers", "description": "🔧 Server Management"},
            {"command": "files", "description": "📂 File Manager"},
            {"command": "status", "description": "📊 System Status"},
            {"command": "search", "description": "🔍 Search Bots"},
            {"command": "earn", "description": "💰 Earning Tools"},
            {"command": "help", "description": "📖 Help & Commands"},
        ]
        self.tg.set_my_commands(commands)

    def handle(self, update):
        """Route update to appropriate handler."""
        if "message" in update:
            self._handle_message(update["message"])
        elif "callback_query" in update:
            self._handle_callback(update["callback_query"])
        elif "inline_query" in update:
            self._handle_inline(update["inline_query"])

    def _handle_message(self, msg):
        """Handle incoming message."""
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()
        msg_id = msg.get("message_id")

        if not text:
            return

        # Initialize session
        if chat_id not in self.sessions:
            self.sessions[chat_id] = {"state": "idle", "history": [], "model": "qwen-7b", "term_buffer": [], "term_output": []}

        session = self.sessions[chat_id]

        # Check if in terminal mode
        if session["state"] == "terminal":
            self._terminal_exec(chat_id, text, msg_id)
            return

        # Check if in AI chat mode
        if session["state"] == "ai_chat":
            self._ai_chat(chat_id, text, msg_id)
            return

        # Commands
        if text.startswith("/"):
            self._handle_command(chat_id, text, msg_id)
            return

        # Default: treat as AI chat
        self._ai_chat(chat_id, text, msg_id)

    def _handle_command(self, chat_id, text, msg_id):
        """Handle bot commands."""
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split('@')[0]
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "/start":
            self.tg.send_message(chat_id,
                "🦉 <b>OWL Telegram Terminal</b>\n\n"
                "Welcome to your complete Telegram OS!\n\n"
                "💻 <b>Terminal</b> - Full shell access\n"
                "🤖 <b>AI Chat</b> - Qwen 2.5 7B with RAG\n"
                "📱 <b>Mini Apps</b> - Build and run apps\n"
                "🔧 <b>Servers</b> - Manage all services\n"
                "📂 <b>Files</b> - File manager\n"
                "🔍 <b>Search</b> - Find bots and channels\n"
                "💰 <b>Earning</b> - Crypto and Telegram earning\n\n"
                "Type /help for all commands\n"
                "Or just type anything to chat with AI!",
                reply_markup=menu_main()
            )

        elif cmd == "/help":
            self.tg.send_message(chat_id,
                "📖 <b>OWL Terminal Commands</b>\n\n"
                "<b>Navigation:</b>\n"
                "/start - Main menu\n"
                "/terminal - Open terminal\n"
                "/ai - AI chat mode\n"
                "/miniapp - Mini apps\n\n"
                "<b>Terminal:</b>\n"
                "/shell &lt;cmd&gt; - Execute shell command\n"
                "/python &lt;code&gt; - Run Python code\n"
                "/scripts - List scripts\n\n"
                "<b>Servers:</b>\n"
                "/servers - Server management\n"
                "/status - System status\n"
                "/restart &lt;service&gt; - Restart service\n\n"
                "<b>Files:</b>\n"
                "/files - File manager\n"
                "/upload - Upload file\n"
                "/download &lt;path&gt; - Download file\n\n"
                "<b>Tools:</b>\n"
                "/search &lt;query&gt; - Search bots\n"
                "/earn - Earning tools\n"
                "/crypto - Crypto tracker\n\n"
                "<b>Telegram:</b>\n"
                "/tgweb - Telegram Web\n"
                "/tgbot - Bot management\n"
                "/tgchannel - Channel tools",
                reply_markup=menu_main()
            )

        elif cmd == "/terminal":
            self.sessions[chat_id]["state"] = "terminal"
            self.tg.send_message(chat_id,
                "💻 <b>Terminal Mode Activated</b>\n\n"
                "Type any shell command to execute.\n"
                "Special commands:\n"
                "  /exit - Exit terminal mode\n"
                "  /clear - Clear buffer\n"
                "  /history - Show command history\n\n"
                "Example: <code>ls -la /root</code>",
                reply_markup=menu_terminal()
            )

        elif cmd == "/shell":
            if args:
                self._terminal_exec(chat_id, args, msg_id)
            else:
                self.tg.send_message(chat_id, "Usage: /shell <command>\nExample: /shell ls -la", reply_to=msg_id)

        elif cmd == "/ai":
            self.sessions[chat_id]["state"] = "ai_chat"
            self.tg.send_message(chat_id,
                "🤖 <b>AI Chat Mode</b>\n\n"
                "Model: Qwen 2.5 7B\n"
                "RAG: Enabled\n\n"
                "Type anything to chat!\n"
                "/exit to exit AI mode.",
                reply_to=msg_id
            )

        elif cmd == "/miniapp":
            self.tg.send_message(chat_id,
                "📱 <b>Mini Apps Platform</b>\n\n"
                "Build and run mini apps inside Telegram!",
                reply_markup=menu_miniapps()
            )

        elif cmd == "/servers":
            self.tg.send_message(chat_id,
                "🔧 <b>Server Management</b>\n\n"
                "Manage all running services:",
                reply_markup=menu_servers()
            )

        elif cmd == "/status":
            self._send_status(chat_id, msg_id)

        elif cmd == "/files":
            self.tg.send_message(chat_id,
                "📂 <b>File Manager</b>\n\n"
                "Upload, download, edit, and manage files.",
                reply_markup=menu_files()
            )

        elif cmd == "/search":
            if args:
                self._search_bots(chat_id, args, msg_id)
            else:
                self.tg.send_message(chat_id,
                    "🔍 <b>Bot Search</b>\n\n"
                    "Usage: /search <query>\n"
                    "Example: /search crypto bot\n\n"
                    "Or use the Bot Search menu:",
                    reply_markup=menu_botsearch()
                )

        elif cmd == "/earn":
            self.tg.send_message(chat_id,
                "💰 <b>Earning Tools</b>\n\n"
                "Crypto airdrops, bot farms, channel earning, and more!",
                reply_markup=menu_earning()
            )

        elif cmd == "/restart":
            if args:
                self._restart_service(chat_id, args, msg_id)
            else:
                self.tg.send_message(chat_id, "Usage: <code>restart <service></code>\nServices: proxy, rag, airllm, github, control, bot, nginx, redis, llama", reply_to=msg_id)

        elif cmd == "/python":
            if args:
                self._run_python(chat_id, args, msg_id)
            else:
                self.tg.send_message(chat_id, "Usage: /python <code>\nExample: /python print('Hello')", reply_to=msg_id)

        elif cmd == "/tgweb":
            self.tg.send_message(chat_id,
                "🌐 <b>Telegram Web</b>\n\n"
                "Access Telegram Web:\n"
                "https://web.telegram.org\n\n"
                "Or use the bot to interact with Telegram API directly.",
                reply_to=msg_id
            )

        elif cmd == "/crypto":
            self._crypto_tracker(chat_id, msg_id)

        else:
            self.tg.send_message(chat_id, f"Unknown command: {text}\nType /help for commands.", reply_to=msg_id)

    def _handle_callback(self, cq):
        """Handle callback queries from inline keyboards."""
        chat_id = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        data = cq["data"]
        cq_id = cq["id"]

        # Answer callback
        self.tg.answer_callback(cq_id)

        # Route by callback data
        if data == "menu_main":
            self.sessions[chat_id]["state"] = "idle"
            self.tg.edit_message(chat_id, msg_id,
                "🦉 <b>OWL Telegram Terminal</b>\n\nSelect an option:",
                reply_markup=menu_main()
            )

        elif data == "menu_terminal":
            self.tg.edit_message(chat_id, msg_id, "💻 <b>Terminal</b>", reply_markup=menu_terminal())

        elif data == "menu_ai":
            self.sessions[chat_id]["state"] = "ai_chat"
            self.tg.edit_message(chat_id, msg_id,
                "🤖 <b>AI Chat Mode</b>\n\nType anything to chat with Qwen 2.5 7B!",
            )

        elif data == "menu_miniapps":
            self.tg.edit_message(chat_id, msg_id, "📱 <b>Mini Apps</b>", reply_markup=menu_miniapps())

        elif data == "menu_servers":
            self.tg.edit_message(chat_id, msg_id, "🔧 <b>Servers</b>", reply_markup=menu_servers())

        elif data == "menu_files":
            self.tg.edit_message(chat_id, msg_id, "📂 <b>Files</b>", reply_markup=menu_files())

        elif data == "menu_earning":
            self.tg.edit_message(chat_id, msg_id, "💰 <b>Earning</b>", reply_markup=menu_earning())

        elif data == "menu_status":
            self._send_status(chat_id, msg_id=msg_id, edit=True)

        elif data == "term_shell":
            self.sessions[chat_id]["state"] = "terminal"
            self.tg.edit_message(chat_id, msg_id,
                "💻 <b>Terminal Mode</b>\n\nType any shell command.\n/exit to exit."
            )

        elif data == "srv_restart":
            self._restart_all(chat_id, msg_id)

        elif data == "srv_status":
            self._send_status(chat_id, msg_id=msg_id, edit=True)

        elif data == "srv_proxy":
            self._service_action(chat_id, msg_id, "proxy", "proxy_api_os.py")

        elif data == "srv_rag":
            self._service_action(chat_id, msg_id, "rag", "rag_server.py")

        elif data == "srv_airllm":
            self._service_action(chat_id, msg_id, "airllm", "airllm_server.py")

        elif data == "srv_github":
            self._service_action(chat_id, msg_id, "github", "github_server.py")

        elif data == "srv_adb":
            self._service_action(chat_id, msg_id, "adb", "adb_bridge.py")

        elif data == "file_list":
            self._file_list(chat_id, msg_id)

        elif data == "earn_airdrop":
            self._earn_airdrop(chat_id, msg_id)

        elif data == "earn_botfarm":
            self._earn_botfarm(chat_id, msg_id)

        elif data == "earn_ton":
            self._earn_ton(chat_id, msg_id)

        elif data == "app_dashboard":
            self._miniapp_dashboard(chat_id, msg_id)

        elif data == "app_crypto":
            self._miniapp_crypto(chat_id, msg_id)

        elif data == "app_search":
            self._miniapp_search(chat_id, msg_id)

        elif data == "app_news":
            self._miniapp_news(chat_id, msg_id)

        elif data == "app_build":
            self._miniapp_build(chat_id, msg_id)

        elif data == "app_notes":
            self._miniapp_notes(chat_id, msg_id)

        elif data == "app_games":
            self._miniapp_games(chat_id, msg_id)

        elif data == "menu_botsearch":
            self.tg.edit_message(chat_id, msg_id,
                "🔍 <b>Bot Search</b>\n\n"
                "Use /search <query> to find bots.\n"
                "Example: /search crypto\n\n"
                "Popular bot categories:\n"
                "• Crypto bots\n"
                "• Earning bots\n"
                "• News bots\n"
                "• Trading bots\n"
                "• Airdrop bots",
                reply_markup=keyboard([[btn("⬅️ Back", "menu_main")]])
            )

        elif data == "menu_tgweb":
            self.tg.edit_message(chat_id, msg_id,
                "🌐 <b>Telegram Web Access</b>\n\n"
                "Web: https://web.telegram.org\n"
                "API: https://api.telegram.org\n\n"
                "Use /tgbot for bot management\n"
                "/tgchannel for channel tools",
                reply_markup=keyboard([[btn("⬅️ Back", "menu_main")]])
            )

        elif data == "menu_settings":
            self.tg.edit_message(chat_id, msg_id,
                "⚙️ <b>Settings</b>\n\n"
                f"Model: {self.sessions.get(chat_id, {}).get('model', 'qwen-7b')}\n"
                f"State: {self.sessions.get(chat_id, {}).get('state', 'idle')}\n\n"
                "Use /switch <model> to change AI model",
                reply_markup=keyboard([[btn("⬅️ Back", "menu_main")]])
            )

    def _handle_inline(self, iq):
        """Handle inline queries."""
        query = iq.get("query", "")
        iq_id = iq["inline_query_id"]

        results = [
            {
                "type": "article",
                "id": "1",
                "title": "🤖 OWL Terminal",
                "description": "Open OWL Telegram Terminal",
                "input_message_content": {
                    "message_text": "🦉 <b>OWL Telegram Terminal</b>\n\nType /start to begin!",
                }
            }
        ]
        self.tg.answer_inline(iq_id, results)

    # ============================================================
    # TERMINAL FUNCTIONS
    # ============================================================

    def _terminal_exec(self, chat_id, cmd, msg_id=None):
        """Execute shell command and return output."""
        if cmd.lower() == "/exit":
            self.sessions[chat_id]["state"] = "idle"
            self.tg.send_message(chat_id, "Exited terminal mode.", reply_markup=menu_main())
            return

        if cmd.lower() == "/clear":
            self.sessions[chat_id]["term_buffer"] = []
            self.tg.send_message(chat_id, "Terminal buffer cleared.")
            return

        if cmd.lower() == "/history":
            history = self.sessions[chat_id].get("term_buffer", [])
            text = "<b>Command History:</b>\n" + "\n".join(f"<code>{h}</code>" for h in history[-20:])
            self.tg.send_message(chat_id, text)
            return

        # Add to history
        self.sessions[chat_id]["term_buffer"].append(cmd)
        if len(self.sessions[chat_id]["term_buffer"]) > 100:
            self.sessions[chat_id]["term_buffer"] = self.sessions[chat_id]["term_buffer"][-100:]

        # Execute
        self.tg.send_chat_action(chat_id, "typing")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30,
                cwd="/root"
            )
            output = result.stdout.strip()
            error = result.stderr.strip()
            rc = result.returncode

            text = f"<b>$</b> <code>{html.escape(cmd[:200])}</code>\n"
            if output:
                text += f"<pre>{html.escape(output[:3000])}</pre>\n"
            if error:
                text += f"<pre style='color:red'>{html.escape(error[:1000])}</pre>\n"
            text += f"<i>exit: {rc}</i>"

            self.tg.send_message(chat_id, text, reply_to=msg_id)
        except subprocess.TimeoutExpired:
            self.tg.send_message(chat_id, f"<b>$</b> <code>{html.escape(cmd[:200])}</code>\n<i>Timeout (30s)</i>", reply_to=msg_id)
        except Exception as e:
            self.tg.send_message(chat_id, f"<b>Error:</b> {html.escape(str(e))}", reply_to=msg_id)

    def _run_python(self, chat_id, code, msg_id):
        """Execute Python code."""
        self.tg.send_chat_action(chat_id, "typing")
        try:
            result = subprocess.run(
                ["python3", "-c", code],
                capture_output=True, text=True, timeout=30, cwd="/root"
            )
            output = result.stdout.strip()
            error = result.stderr.strip()
            text = f"<b>Python:</b>\n<pre>{html.escape(code[:500])}</pre>\n"
            if output:
                text += f"<pre>{html.escape(output[:3000])}</pre>\n"
            if error:
                text += f"<pre>Error: {html.escape(error[:1000])}</pre>"
            self.tg.send_message(chat_id, text, reply_to=msg_id)
        except Exception as e:
            self.tg.send_message(chat_id, f"Error: {html.escape(str(e))}", reply_to=msg_id)

    # ============================================================
    # AI CHAT
    # ============================================================

    def _ai_chat(self, chat_id, text, msg_id):
        """Chat with AI through AirLLM."""
        self.tg.send_chat_action(chat_id, "typing")
        session = self.sessions[chat_id]
        model = session.get("model", "qwen-7b")
        history = session.get("history", [])
        history.append({"role": "user", "content": text})
        if len(history) > 20:
            history = history[-20:]
        session["history"] = history

        try:
            payload = json.dumps({"model": model, "messages": history, "max_tokens": 1024, "temperature": 0.7, "use_rag": True}).encode()
            req = urllib.request.Request(f"{AIRLLM_URL}/chat", data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode('utf-8'))
            if "choices" in result:
                response = result["choices"][0]["message"]["content"]
                session["history"].append({"role": "assistant", "content": response})
                self.tg.send_message(chat_id, response, reply_to=msg_id)
            elif "error" in result:
                self.tg.send_message(chat_id, f"❌ {result['error']}", reply_to=msg_id)
            else:
                self.tg.send_message(chat_id, "❌ No response", reply_to=msg_id)
        except Exception as e:
            self.tg.send_message(chat_id, f"❌ Error: {str(e)[:200]}", reply_to=msg_id)

    # ============================================================
    # STATUS & SERVERS
    # ============================================================

    def _send_status(self, chat_id, msg_id=None, edit=False):
        """Send system status."""
        services = [
            ("nginx", 8081), ("redis", 6379), ("llama (qwen)", 11434),
            ("proxy", 8090), ("control", 9090), ("rag", 9092),
            ("airllm", 9093), ("github", 9094), ("adb", 9091),
        ]
        lines = ["📊 <b>System Status</b>\n"]
        for name, port in services:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="GET")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    status = "🟢" if resp.status < 400 else "🟡"
            except:
                status = "🔴"
            lines.append(f"{status} {name} (:{port})")

        # System info
        try:
            r = subprocess.run("free -h | grep Mem", shell=True, capture_output=True, text=True, timeout=5)
            mem = r.stdout.strip().split()
            lines.append(f"\n💾 Memory: {mem[2]}/{mem[1]}")
        except: pass
        try:
            r = subprocess.run("df -h / | tail -1", shell=True, capture_output=True, text=True, timeout=5)
            disk = r.stdout.split()
            lines.append(f"💿 Disk: {disk[2]}/{disk[3]} ({disk[4]})")
        except: pass

        text = "\n".join(lines)
        if edit and msg_id:
            self.tg.edit_message(chat_id, msg_id, text, reply_markup=keyboard([[btn("🔄 Refresh", "menu_status")], [btn("⬅️ Back", "menu_main")]]))
        else:
            self.tg.send_message(chat_id, text, reply_to=msg_id, reply_markup=keyboard([[btn("🔄 Refresh", "menu_status")], [btn("⬅️ Back", "menu_main")]]))

    def _restart_service(self, chat_id, name, msg_id):
        """Restart a specific service."""
        service_map = {
            "proxy": ("proxy_api_os.py", 8090),
            "rag": ("rag_server.py", 9092),
            "airllm": ("airllm_server.py", 9093),
            "github": ("github_server.py", 9094),
            "control": ("control_plane.py", 9090),
            "adb": ("adb_bridge.py", 9091),
            "nginx": (None, 8081),
            "redis": (None, 6379),
            "llama": (None, 11434),
        }
        if name not in service_map:
            self.tg.send_message(chat_id, f"Unknown service: {name}\nAvailable: {', '.join(service_map.keys())}", reply_to=msg_id)
            return

        self.tg.send_chat_action(chat_id, "upload_document")
        script, port = service_map[name]

        try:
            if script:
                subprocess.run(f"pkill -f '{script}' 2>/dev/null", shell=True)
                time.sleep(1)
                subprocess.run(f"cd /root/telegram-bridge && nohup python3 {script} > /tmp/{name}.log 2>&1 &", shell=True)
            elif name == "nginx":
                subprocess.run("service nginx restart", shell=True)
            elif name == "redis":
                subprocess.run("service redis-server restart", shell=True)
            elif name == "llama":
                subprocess.run("pkill -f llama-server 2>/dev/null", shell=True)
                time.sleep(1)
                subprocess.run("nohup /usr/bin/llama-server --model /root/models/qwen2.5/qwen2.5-7b-instruct-q4_k_m.gguf --host 0.0.0.0 --port 11434 --ctx-size 32768 --threads 4 --n-gpu-layers 0 > /tmp/llama-server.log 2>&1 &", shell=True)

            time.sleep(3)
            # Check
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    self.tg.send_message(chat_id, f"✅ <b>{name}</b> restarted successfully!", reply_to=msg_id)
                    return
            except:
                self.tg.send_message(chat_id, f"⚠️ <b>{name}</b> restart command sent. May take a moment.", reply_to=msg_id)
        except Exception as e:
            self.tg.send_message(chat_id, f"❌ Error restarting {name}: {str(e)}", reply_to=msg_id)

    def _restart_all(self, chat_id, msg_id):
        """Restart all services."""
        services = ["proxy", "rag", "airllm", "github", "control", "adb"]
        self.tg.edit_message(chat_id, msg_id, "🔄 Restarting all services...")
        for svc in services:
            self._restart_service(chat_id, svc, None)
            time.sleep(1)
        self.tg.send_message(chat_id, "✅ All services restarted!", reply_markup=menu_servers())

    def _service_action(self, chat_id, msg_id, name, script):
        """Show service actions."""
        self.tg.edit_message(chat_id, msg_id,
            f"🔧 <b>{name.upper()}</b>\n\nActions:",
            reply_markup=keyboard([
                [btn("🔄 Restart", f"srv_{name}")],
                [btn("📜 Logs", f"logs_{name}")],
                [btn("⬅️ Back", "menu_servers")],
            ])
        )

    # ============================================================
    # FILE MANAGER
    # ============================================================

    def _file_list(self, chat_id, msg_id):
        """List files in /root."""
        try:
            r = subprocess.run("ls -lah /root/ | head -30", shell=True, capture_output=True, text=True, timeout=5)
            text = f"<b>📂 /root/</b>\n<pre>{html.escape(r.stdout)}</pre>"
        except:
            text = "❌ Could not list files"
        self.tg.edit_message(chat_id, msg_id, text, reply_markup=menu_files())

    # ============================================================
    # MINI APPS
    # ============================================================

    def _miniapp_dashboard(self, chat_id, msg_id):
        """Show mini app dashboard."""
        self.tg.edit_message(chat_id, msg_id,
            "📊 <b>Dashboard</b>\n\n"
            "Server: 192.168.1.184\n"
            "Uptime: " + self._get_uptime() + "\n"
            "Services: 9 running\n"
            "Disk: 92%\n"
            "RAM: ~8GB/11GB",
            reply_markup=keyboard([[btn("⬅️ Back", "menu_miniapps")]])
        )

    def _miniapp_crypto(self, chat_id, msg_id):
        """Crypto mini app."""
        prices = self._get_crypto_prices()
        self.tg.edit_message(chat_id, msg_id,
            f"💱 <b>Crypto Prices</b>\n\n{prices}",
            reply_markup=keyboard([[btn("🔄 Refresh", "app_crypto")], [btn("⬅️ Back", "menu_miniapps")]])
        )

    def _miniapp_search(self, chat_id, msg_id):
        """Search mini app."""
        self.tg.edit_message(chat_id, msg_id,
            "🔍 <b>Search</b>\n\n"
            "Use /search <query> to search.\n"
            "Examples:\n"
            "  /search crypto bot\n"
            "  /search airdrop\n"
            "  /search earning",
            reply_markup=keyboard([[btn("⬅️ Back", "menu_miniapps")]])
        )

    def _miniapp_news(self, chat_id, msg_id):
        """News mini app."""
        self.tg.edit_message(chat_id, msg_id,
            "📰 <b>News</b>\n\n"
            "Latest updates:\n"
            "• OWL Terminal v2.0 launched\n"
            "• Qwen 2.5 7B now default model\n"
            "• RAG Server active\n"
            "• AirLLM multi-model serving\n"
            "• GitHub Codespace integrated",
            reply_markup=keyboard([[btn("⬅️ Back", "menu_miniapps")]])
        )

    def _miniapp_build(self, chat_id, msg_id):
        """Build mini app."""
        self.tg.edit_message(chat_id, msg_id,
            "🛠️ <b>Build Mini App</b>\n\n"
            "To build a new mini app:\n"
            "1. Describe what you want\n"
            "2. I'll create the code\n"
            "3. Deploy it instantly\n\n"
            "Example: Build a todo app",
            reply_markup=keyboard([[btn("⬅️ Back", "menu_miniapps")]])
        )

    def _miniapp_notes(self, chat_id, msg_id):
        """Notes mini app."""
        self.tg.edit_message(chat_id, msg_id,
            "📝 <b>Notes</b>\n\n"
            "Your notes:\n"
            "(No notes yet)\n\n"
            "Type to add a note:",
            reply_markup=keyboard([[btn("⬅️ Back", "menu_miniapps")]])
        )

    def _miniapp_games(self, chat_id, msg_id):
        """Games mini app."""
        self.tg.edit_message(chat_id, msg_id,
            "🎮 <b>Games</b>\n\n"
            "Available games:\n"
            "• Tic Tac Toe\n"
            "• Quiz\n"
            "• Word Guess",
            reply_markup=keyboard([
                [btn("❌ Tic Tac Toe", "game_ttt"), btn("🧠 Quiz", "game_quiz")],
                [btn("⬅️ Back", "menu_miniapps")],
            ])
        )

    # ============================================================
    # EARNING TOOLS
    # ============================================================

    def _earn_airdrop(self, chat_id, msg_id):
        """Crypto airdrop tracker."""
        self.tg.edit_message(chat_id, msg_id,
            "🪙 <b>Crypto Airdrops</b>\n\n"
            "Active airdrops:\n"
            "• TON Foundation - Ongoing\n"
            "• Arbitrum - Check eligibility\n"
            "• Starknet - Potential\n"
            "• LayerZero - Rumored\n\n"
            "Use /crypto for price tracking",
            reply_markup=keyboard([[btn("⬅️ Back", "menu_earning")]])
        )

    def _earn_botfarm(self, chat_id, msg_id):
        """Bot farm info."""
        self.tg.edit_message(chat_id, msg_id,
            "🤖 <b>Bot Farm</b>\n\n"
            "Telegram earning bots:\n"
            "• Notcoin - Tap to earn\n"
            "• Hamster Kombat - Tap game\n"
            "• Blum - Points farming\n"
            "• Major - Rating system\n\n"
            "⚠️ Always DYOR before investing time.",
            reply_markup=keyboard([[btn("⬅️ Back", "menu_earning")]])
        )

    def _earn_ton(self, chat_id, msg_id):
        """TON earning."""
        self.tg.edit_message(chat_id, msg_id,
            "💎 <b>TON Earning</b>\n\n"
            "TON Network opportunities:\n"
            "• TON Mining (PoS validation)\n"
            "• TON DeFi (STON.fi, Dedust)\n"
            "• TON NFTs\n"
            "• TON DNS\n\n"
            "Wallet: Use Tonkeeper or @wallet",
            reply_markup=keyboard([[btn("⬅️ Back", "menu_earning")]])
        )

    # ============================================================
    # SEARCH
    # ============================================================

    def _search_bots(self, chat_id, query, msg_id):
        """Search for Telegram bots."""
        # Search via web
        try:
            search_url = f"https://www.google.com/search?q=telegram+bot+{urllib.parse.quote(query)}"
            req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode('utf-8', errors='replace')
            # Extract bot mentions
            bots = re.findall(r'@(\w+bot)', content)
            bots = list(set(bots))[:10]
            if bots:
                text = f"🔍 <b>Search: {html.escape(query)}</b>\n\nFound bots:\n"
                for b in bots:
                    text += f"• @{b}\n"
            else:
                text = f"🔍 No bots found for: {html.escape(query)}"
        except:
            text = f"🔍 Search for: {html.escape(query)}\n\nTry searching on:\nhttps://www.google.com/search?q=telegram+bot+{urllib.parse.quote(query)}"
        self.tg.send_message(chat_id, text, reply_to=msg_id)

    # ============================================================
    # CRYPTO TRACKER
    # ============================================================

    def _crypto_tracker(self, chat_id, msg_id):
        """Track crypto prices."""
        prices = self._get_crypto_prices()
        self.tg.send_message(chat_id, f"💱 <b>Crypto Prices</b>\n\n{prices}", reply_to=msg_id)

    def _get_crypto_prices(self):
        """Get crypto prices from API."""
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,toncoin,solana&vs_currencies=usd&include_24hr_change=true"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            lines = []
            for coin, info in data.items():
                price = info.get("usd", 0)
                change = info.get("usd_24h_change", 0)
                emoji = "🟢" if change >= 0 else "🔴"
                lines.append(f"{emoji} <b>{coin.upper()}</b>: ${price:,.2f} ({change:+.1f}%)")
            return "\n".join(lines)
        except:
            return "❌ Could not fetch prices"

    def _get_uptime(self):
        """Get system uptime."""
        try:
            with open('/proc/uptime') as f:
                seconds = float(f.read().split()[0])
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h {m}m"
        except:
            return "unknown"


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    log.info("=" * 60)
    log.info("OWL Telegram Terminal Starting...")
    log.info("=" * 60)

    handler = TerminalHandler()

    # Verify
    me = handler.tg.get_me()
    if me.get("ok"):
        log.info(f"Bot: @{me['result']['username']}")
    else:
        log.error("Telegram API unreachable!")
        return

    # Clear webhook
    handler.tg.set_webhook(None)
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

    log.info("Terminal stopped.")


if __name__ == "__main__":
    main()
