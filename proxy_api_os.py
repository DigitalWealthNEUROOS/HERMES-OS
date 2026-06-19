#!/usr/bin/env python3
"""
HERMES PROXY API OS
===================
Unified proxy for ALL LLM API connections.
Replaces direct openrouter.ai calls with hermes-proxy routing.

Architecture:
- Hermes Agent -> hermes-proxy.ai/api/v1/* -> Multiple LLM providers
- Local model (qwen 7B) served directly
- Cloud models routed through proxy with failover
- Web dashboard for monitoring
- Telegram bot integration

Endpoints:
- POST /api/v1/chat/completions  -> Chat with any model
- GET  /api/v1/models           -> List all available models
- GET  /api/v1/health           -> Health check
- GET  /api/v1/status           -> Full system status
- GET  /dashboard               -> Web dashboard
"""

import os
import sys
import json
import time
import signal
import socket
import logging
import hashlib
import threading
import subprocess
import http.client
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

PROXY_PORT = 8090
LLM_PORT = 11434
LOG_FILE = "/tmp/hermes-proxy.log"

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("hermes-proxy")

# ============================================================
# MODEL REGISTRY - All available models
# ============================================================

MODELS = {
    # Local model (served by llama-server) - Qwen 2.5 7B is the ONLY local model
    "qwen-7b": {
        "id": "qwen-7b",
        "name": "Qwen 2.5 7B Instruct",
        "provider": "local",
        "endpoint": f"http://127.0.0.1:{LLM_PORT}",
        "context_length": 32768,
        "cost_per_1k": 0,
        "ram_gb": 6.0,
        "model_file": "/root/models/qwen2.5/qwen2.5-7b-instruct-q4_k_m.gguf",
        "available": False,
    },
    # Cloud models (routed through proxy)
    "claude-sonnet-4": {
        "id": "anthropic/claude-sonnet-4",
        "name": "Claude Sonnet 4",
        "provider": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "context_length": 200000,
        "cost_per_1k": 0.003,
        "available": True,
    },
    "claude-opus-4": {
        "id": "anthropic/claude-opus-4",
        "name": "Claude Opus 4",
        "provider": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "context_length": 200000,
        "cost_per_1k": 0.015,
        "available": True,
    },
    "gpt-4o": {
        "id": "openai/gpt-4o",
        "name": "GPT-4o",
        "provider": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "context_length": 128000,
        "cost_per_1k": 0.005,
        "available": True,
    },
    "gpt-4o-mini": {
        "id": "openai/gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "context_length": 128000,
        "cost_per_1k": 0.00015,
        "available": True,
    },
    "gemini-2.5-flash": {
        "id": "gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "provider": "google",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
        "context_length": 1000000,
        "cost_per_1k": 0.0001,
        "available": True,
    },
    "llama-3.3-70b": {
        "id": "meta-llama/llama-3.3-70b-instruct",
        "name": "Llama 3.3 70B",
        "provider": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "context_length": 131072,
        "cost_per_1k": 0.0005,
        "available": True,
    },
    "deepseek-v3": {
        "id": "deepseek/deepseek-v3",
        "name": "DeepSeek V3",
        "provider": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "context_length": 65536,
        "cost_per_1k": 0.0002,
        "available": True,
    },
    "owl-alpha": {
        "id": "openrouter/owl-alpha",
        "name": "OWL Alpha",
        "provider": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "context_length": 131072,
        "cost_per_1k": 0,
        "available": True,
    },
}

# ============================================================
# API KEYS
# ============================================================

def load_api_keys():
    """Load API keys from .env file."""
    keys = {}
    try:
        with open('/root/.hermes/.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('OPENROUTER_API_KEY'):
                    keys['openrouter'] = line.split('=', 1)[1]
                elif line.startswith('GOOGLE_API_KEY'):
                    keys['google'] = line.split('=', 1)[1]
                elif line.startswith('GROQ_API_KEY'):
                    keys['groq'] = line.split('=', 1)[1]
    except:
        pass
    return keys

API_KEYS = load_api_keys()

# ============================================================
# LOCAL LLM MANAGER
# ============================================================

class LocalLLMManager:
    """Manages local LLM models with auto-switching."""

    def __init__(self):
        self.active_model = None
        self.llm_port = LLM_PORT
        self.server_pid = None
        self._check_models()

    def _check_models(self):
        """Check which local models are available."""
        for key, model in MODELS.items():
            if model["provider"] == "local":
                model["available"] = os.path.exists(model.get("model_file", ""))

    def is_running(self):
        """Check if llama-server is running."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            r = s.connect_ex(('127.0.0.1', self.llm_port))
            s.close()
            return r == 0
        except:
            return False

    def start_model(self, model_key):
        """Start llama-server with specific model."""
        model = MODELS.get(model_key)
        if not model or model["provider"] != "local":
            return False, f"Model {model_key} is not a local model"

        if not os.path.exists(model["model_file"]):
            return False, f"Model file not found: {model['model_file']}"

        # Kill existing server
        subprocess.run("pkill -f llama-server 2>/dev/null", shell=True)
        time.sleep(2)

        # Start new server
        cmd = (
            f"/usr/bin/llama-server "
            f"--model {model['model_file']} "
            f"--host 0.0.0.0 --port {self.llm_port} "
            f"--ctx-size {model['context_length']} "
            f"--threads 4 --n-gpu-layers 0 "
            f"> /tmp/llama-server.log 2>&1 &"
        )
        subprocess.run(cmd, shell=True)
        time.sleep(5)

        if self.is_running():
            self.active_model = model_key
            log.info(f"Started local model: {model_key}")
            return True, f"Started {model_key}"
        else:
            return False, f"Failed to start {model_key}"

    def get_active(self):
        """Get currently active local model."""
        if self.is_running():
            return self.active_model
        return None


# ============================================================
# PROXY ROUTER
# ============================================================

class ProxyRouter:
    """Routes API requests to appropriate LLM provider."""

    def __init__(self):
        self.local_llm = LocalLLMManager()
        self.request_count = 0
        self.error_count = 0
        self.start_time = time.time()

    def route_chat(self, request_data):
        """Route a chat completion request to the appropriate provider."""
        self.request_count += 1

        # Determine which model to use
        model_id = request_data.get("model", "qwen-7b")

        # Find model config
        model_config = None
        for key, m in MODELS.items():
            if m["id"] == model_id or key == model_id:
                model_config = m
                break

        if not model_config:
            # Default to qwen-7b
            model_config = MODELS.get("qwen-7b")

        provider = model_config["provider"]

        if provider == "local":
            return self._route_local(request_data, model_config)
        else:
            return self._route_cloud(request_data, model_config)

    def _route_local(self, request_data, model_config):
        """Route to local LLM server."""
        # Ensure the right model is loaded
        model_key = None
        for k, m in MODELS.items():
            if m["id"] == model_config["id"]:
                model_key = k
                break

        if model_key and self.local_llm.active_model != model_key:
            if not self.local_llm.is_running() or self.local_llm.active_model != model_key:
                success, msg = self.local_llm.start_model(model_key)
                if not success:
                    return {"error": f"Failed to start local model: {msg}"}

        if not self.local_llm.is_running():
            return {"error": "Local LLM server not running"}

        # Forward request to llama-server
        return self._http_post(
            f"http://127.0.0.1:{LLM_PORT}/v1/chat/completions",
            request_data
        )

    def _route_cloud(self, request_data, model_config):
        """Route to cloud LLM provider through proxy."""
        endpoint = model_config["endpoint"]
        provider = model_config["provider"]

        # Get the right API key
        if provider == "google":
            api_key = API_KEYS.get('google', '')
        else:
            api_key = API_KEYS.get('openrouter', '')

        if not api_key:
            return {"error": f"No API key for provider: {provider}"}

        # Set the model in request
        request_data["model"] = model_config["id"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        if provider != "google":
            headers["HTTP-Referer"] = "https://hermes-proxy.ai"
            headers["X-Title"] = "Hermes Proxy API OS"

        try:
            body = json.dumps(request_data).encode('utf-8')
            req = urllib.request.Request(
                f"{endpoint}/chat/completions",
                data=body,
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data
        except urllib.error.HTTPError as e:
            self.error_count += 1
            error_body = e.read().decode('utf-8', errors='replace')
            log.error(f"Cloud API error: {e.code} - {error_body[:200]}")
            return {"error": f"Provider error: {e.code}", "details": error_body[:500]}
        except Exception as e:
            self.error_count += 1
            log.error(f"Cloud API error: {e}")
            return {"error": str(e)}

    def _http_post(self, url, data):
        """Make HTTP POST request."""
        try:
            body = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            self.error_count += 1
            return {"error": str(e)}

    def list_models(self):
        """List all available models."""
        # Update local model availability
        self.local_llm._check_models()

        model_list = []
        for key, m in MODELS.items():
            model_list.append({
                "id": m["id"],
                "name": m["name"],
                "provider": m["provider"],
                "context_length": m["context_length"],
                "available": m["available"],
                "cost_per_1k": m.get("cost_per_1k", 0),
            })

        return {
            "object": "list",
            "data": model_list,
        }

    def get_status(self):
        """Get proxy status."""
        uptime = time.time() - self.start_time
        return {
            "status": "running",
            "uptime_seconds": int(uptime),
            "uptime_human": f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m {int(uptime % 60)}s",
            "total_requests": self.request_count,
            "total_errors": self.error_count,
            "error_rate": f"{(self.error_count / max(self.request_count, 1)) * 100:.1f}%",
            "local_llm": {
                "running": self.local_llm.is_running(),
                "active_model": self.local_llm.get_active(),
            },
            "api_keys": {
                "openrouter": bool(API_KEYS.get('openrouter')),
                "google": bool(API_KEYS.get('google')),
                "groq": bool(API_KEYS.get('groq')),
            },
            "models": {
                "total": len(MODELS),
                "local": sum(1 for m in MODELS.values() if m["provider"] == "local" and m["available"]),
                "cloud": sum(1 for m in MODELS.values() if m["provider"] != "local" and m["available"]),
            }
        }


# ============================================================
# HTTP SERVER
# ============================================================

class ProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Hermes Proxy API OS."""
    router = ProxyRouter()

    def log_message(self, fmt, *args):
        pass  # Suppress default logging

    def _json(self, data, status=200):
        body = json.dumps(data, indent=2, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Hermes-Proxy", "v1.0")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip('/')

        if path in ['/api/v1/health', '/health']:
            return self._json({"status": "ok", "service": "hermes-proxy", "version": "1.0"})

        if path in ['/api/v1/status', '/status']:
            return self._json(self.router.get_status())

        if path in ['/api/v1/models', '/models']:
            return self._json(self.router.list_models())

        if path in ['/dashboard', '/']:
            return self._dashboard()

        self._json({"error": f"Unknown endpoint: {path}"}, 404)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'

        try:
            data = json.loads(body) if body else {}
        except:
            return self._json({"error": "Invalid JSON"}, 400)

        path = self.path.rstrip('/')

        if path in ['/api/v1/chat/completions', '/chat/completions']:
            result = self.router.route_chat(data)
            if "error" in result:
                return self._json(result, 500)
            return self._json(result)

        if path == '/api/v1/local/switch':
            model = data.get("model", "qwen-7b")
            success, msg = self.router.local_llm.start_model(model)
            return self._json({"success": success, "message": msg})

        self._json({"error": f"Unknown endpoint: {path}"}, 404)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _dashboard(self):
        """Serve web dashboard."""
        status = self.router.get_status()
        models = self.router.list_models()

        model_rows = ""
        for m in models["data"]:
            avail = "✅" if m["available"] else "❌"
            provider_color = "#00ff88" if m["provider"] == "local" else "#4488ff"
            model_rows += f"""
            <tr>
                <td>{avail}</td>
                <td><b>{m['name']}</b></td>
                <td style="color:{provider_color}">{m['provider']}</td>
                <td>{m['context_length']:,}</td>
                <td>${m['cost_per_1k']}</td>
            </tr>"""

        body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hermes Proxy API OS</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: linear-gradient(135deg, #0a0a1a 0%, #1a1a3e 100%);
            color: #eee; font-family: 'Courier New', monospace; padding: 20px;
            min-height: 100vh;
        }}
        .header {{
            text-align: center; padding: 30px 0; border-bottom: 2px solid #00ff88;
            margin-bottom: 30px;
        }}
        .header h1 {{ color: #00ff88; font-size: 2.5em; text-shadow: 0 0 20px #00ff88; }}
        .header p {{ color: #888; margin-top: 10px; }}
        .stats {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px; margin-bottom: 30px;
        }}
        .stat-card {{
            background: rgba(0,255,136,0.05); border: 1px solid #00ff88;
            border-radius: 12px; padding: 20px; text-align: center;
        }}
        .stat-card h3 {{ color: #00ff88; font-size: 2em; }}
        .stat-card p {{ color: #888; margin-top: 5px; }}
        .section {{
            background: rgba(255,255,255,0.03); border-radius: 12px;
            padding: 20px; margin-bottom: 20px;
        }}
        .section h2 {{ color: #00ff88; margin-bottom: 15px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #00ff88; background: rgba(0,255,136,0.05); }}
        tr:hover {{ background: rgba(255,255,255,0.03); }}
        .endpoint {{
            background: #1a1a2e; padding: 15px; border-radius: 8px;
            margin: 10px 0; border-left: 4px solid #00ff88;
        }}
        .endpoint code {{ color: #00ff88; }}
        .status-dot {{
            display: inline-block; width: 10px; height: 10px;
            border-radius: 50%; margin-right: 8px;
        }}
        .status-up {{ background: #00ff88; box-shadow: 0 0 10px #00ff88; }}
        .status-down {{ background: #ff4444; }}
        a {{ color: #00ff88; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🦉 HERMES PROXY API OS</h1>
        <p>Unified LLM Proxy • Local + Cloud Models • One Endpoint</p>
        <p style="color:#666; font-size: 0.9em;">
            <span class="status-dot {'status-up' if status['local_llm']['running'] else 'status-down'}"></span>
            Uptime: {status['uptime_human']} |
            Requests: {status['total_requests']} |
            Errors: {status['error_rate']}
        </p>
    </div>

    <div class="stats">
        <div class="stat-card">
            <h3>{status['models']['total']}</h3>
            <p>Total Models</p>
        </div>
        <div class="stat-card">
            <h3>{status['models']['local']}</h3>
            <p>Local Models</p>
        </div>
        <div class="stat-card">
            <h3>{status['models']['cloud']}</h3>
            <p>Cloud Models</p>
        </div>
        <div class="stat-card">
            <h3>{status['local_llm']['active_model'] or 'None'}</h3>
            <p>Active Local Model</p>
        </div>
    </div>

    <div class="section">
        <h2>🔗 API Endpoints</h2>
        <div class="endpoint">
            <b>POST</b> <code>/api/v1/chat/completions</code> - Chat with any model
        </div>
        <div class="endpoint">
            <b>GET</b> <code>/api/v1/models</code> - List all models
        </div>
        <div class="endpoint">
            <b>GET</b> <code>/api/v1/status</code> - System status
        </div>
        <div class="endpoint">
            <b>POST</b> <code>/api/v1/local/switch</code> - Switch local model
        </div>
    </div>

    <div class="section">
        <h2>🤖 Available Models</h2>
        <table>
            <tr>
                <th>Status</th><th>Model</th><th>Provider</th><th>Context</th><th>Cost/1K</th>
            </tr>
            {model_rows}
        </table>
    </div>

    <div class="section">
        <h2>🔑 API Keys</h2>
        <p>OpenRouter: {'✅ Configured' if status['api_keys']['openrouter'] else '❌ Missing'}</p>
        <p>Google: {'✅ Configured' if status['api_keys']['google'] else '❌ Missing'}</p>
        <p>Groq: {'✅ Configured' if status['api_keys']['groq'] else '❌ Missing'}</p>
    </div>

    <div class="section">
        <h2>📝 Usage Example</h2>
        <pre style="background:#0a0a1a;padding:15px;border-radius:8px;overflow-x:auto;">
curl -X POST http://localhost:{PROXY_PORT}/api/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{{
    "model": "qwen-7b",
    "messages": [{{"role": "user", "content": "Hello!"}}],
    "max_tokens": 256
  }}'</pre>
    </div>

    <p style="text-align:center;color:#666;margin-top:30px;">
        Hermes Proxy API OS v1.0 • Running on port {PROXY_PORT}
    </p>
</body>
</html>""".encode('utf-8')

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ============================================================
# MAIN
# ============================================================

def main():
    log.info("=" * 60)
    log.info("HERMES PROXY API OS Starting...")
    log.info(f"Port: {PROXY_PORT}")
    log.info(f"LLM Port: {LLM_PORT}")
    log.info("=" * 60)

    # Start with phi-3 by default
    # Start with qwen-7b by default
    if MODELS["qwen-7b"]["available"]:
        log.info("Starting local model: qwen-7b")
        router.local_llm.start_model("qwen-7b")

    # Start HTTP server
    server = HTTPServer(("0.0.0.0", PROXY_PORT), ProxyHandler)
    log.info(f"Proxy API listening on port {PROXY_PORT}")
    log.info(f"Dashboard: http://localhost:{PROXY_PORT}/dashboard")
    log.info(f"API: http://localhost:{PROXY_PORT}/api/v1")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
