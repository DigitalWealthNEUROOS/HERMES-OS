#!/usr/bin/env python3
"""OWL Unified Control Plane - Single entry point for ALL local services."""

import os, sys, json, time, signal, logging, threading, subprocess, http.client
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

CONTROL_PORT = 9090
LOG_FILE = "/tmp/owl-control-plane.log"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("owl-control")

SERVICES = {
    "llm": {"name": "LLM Server (Qwen 2.5 7B)", "port": 11434, "url": "http://localhost:11434", "description": "Local LLM inference server"},
    "code_server": {"name": "Code Server (VS Code)", "port": 8888, "url": "http://localhost:8888", "description": "VS Code in browser"},
    "portal": {"name": "Web Portal", "port": 3000, "url": "http://localhost:3000", "description": "OWL Web Portal"},
    "nginx": {"name": "nginx Web Server", "port": 8081, "url": "http://localhost:8081", "description": "Main web server"},
    "ws_bridge": {"name": "WebSocket Bridge", "port": 8082, "url": "http://localhost:8082", "description": "WebSocket real-time bridge"},
    "redis": {"name": "Redis Cache", "port": 6379, "url": None, "description": "In-memory cache & message broker"},
    "adb": {"name": "ADB Server", "port": 5037, "url": None, "description": "Android Debug Bridge"},
    "ssh": {"name": "SSH Server", "port": 22, "url": None, "description": "Secure Shell access"},
    "dashboard": {"name": "OWL Dashboard", "port": 8081, "url": "http://localhost:8081/dashboard", "description": "OWL Dashboard UI"},
    "openclaw": {"name": "OpenClaw Gateway", "port": 18789, "url": "http://localhost:18789", "description": "OpenClaw AI gateway"},
    "hermes": {"name": "Hermes Gateway", "port": None, "url": None, "description": "Hermes AI Agent Gateway"},
}

MODELS = {
    "qwen-7b": {"file": "qwen2.5-7b-instruct-q4_k_m.gguf", "path": "/root/models/qwen2.5/qwen2.5-7b-instruct-q4_k_m.gguf", "size": "4.4GB", "context": 32768, "ram": 6.0},
}


class ServiceMonitor:
    """Monitors health of all local services."""

    @staticmethod
    def check_port(port, timeout=2):
        """Check if a TCP port is open. Works in proot environments."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            result = s.connect_ex(('127.0.0.1', port))
            s.close()
            if result == 0:
                return True
        except:
            pass
        # Fallback: try connecting via HTTP
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
            conn.request("GET", "/")
            resp = conn.getresponse()
            conn.close()
            return resp.status < 500
        except:
            pass
        # Last resort: try subprocess check
        try:
            result = subprocess.run(
                f"echo '' | nc -w1 127.0.0.1 {port} 2>/dev/null",
                shell=True, capture_output=True, timeout=timeout + 2
            )
            if result.returncode == 0:
                return True
        except:
            pass
        # Try curl as final fallback
        try:
            result = subprocess.run(
                f"curl -s -o /dev/null --max-time {timeout} http://127.0.0.1:{port}/ 2>/dev/null",
                shell=True, capture_output=True, timeout=timeout + 2
            )
            if result.returncode == 0:
                return True
        except:
            pass
        return False

    def check_all(self):
        results = {}
        for key, svc in SERVICES.items():
            port = svc.get("port")
            if port:
                up = self.check_port(port)
                results[key] = {"name": svc["name"], "port": port, "status": "up" if up else "down", "description": svc["description"]}
            else:
                results[key] = {"name": svc["name"], "port": None, "status": "unknown", "description": svc["description"]}
        return results

    def get_status_report(self):
        services = self.check_all()
        up_count = sum(1 for s in services.values() if s["status"] == "up")
        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {"total": len(services), "up": up_count, "down": len(services) - up_count},
            "services": services,
            "system": self._system_info(),
            "models": self._model_status(),
        }

    def _system_info(self):
        info = {}
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    if 'MemTotal' in line: info['mem_total'] = line.split()[1]
                    elif 'MemAvailable' in line: mem_free = line.split()[1]; break
            with open('/proc/loadavg') as f:
                info['load'] = f.read().strip()
        except: pass
        result = subprocess.run("df -h / | tail -1", shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            parts = result.stdout.split()
            info['disk_used'] = parts[2]; info['disk_avail'] = parts[3]; info['disk_pct'] = parts[4]
        return info

    def _model_status(self):
        status = {}
        for key, model in MODELS.items():
            exists = os.path.exists(model["path"])
            running = self.check_port(11434) if exists else False
            status[key] = {"exists": exists, "size": model["size"], "context": model["context"], "ram_gb": model["ram"], "llm_server": running}
        return status


class LLMManager:
    """Manages local LLM models with auto-switching."""

    def __init__(self):
        self.active_model = "qwen-7b"
        self.llm_port = 11434
        self.loaded_pid = None
        self._ensure_running("qwen-7b")

    def _ensure_running(self, model_name):
        """Ensure llama-server is running with the specified model."""
        if ServiceMonitor.check_port(self.llm_port):
            self.active_model = model_name
            return True
        return self._start_server(model_name)

    def _start_server(self, model_name):
        """Start llama-server for a specific model."""
        model = MODELS.get(model_name)
        if not model or not os.path.exists(model["path"]):
            return False

        # Kill existing server
        subprocess.run("pkill -f llama-server 2>/dev/null", shell=True)
        time.sleep(1)

        cmd = (f"/usr/bin/llama-server --model {model['path']} "
               f"--host 0.0.0.0 --port {self.llm_port} "
               f"--ctx-size {model['context']} --threads 4 --n-gpu-layers 0 "
               f"> /tmp/llama-server.log 2>&1 &")
        subprocess.run(cmd, shell=True)
        time.sleep(4)

        if ServiceMonitor.check_port(self.llm_port):
            self.active_model = model_name
            return True
        return False

    def switch_model(self, model_name):
        """Switch to a different model."""
        if model_name not in MODELS:
            return False, f"Unknown model: {model_name}. Available: {list(MODELS.keys())}"

        if model_name == self.active_model and ServiceMonitor.check_port(self.llm_port):
            return True, f"Already running {model_name}"

        if self._start_server(model_name):
            return True, f"Switched to {model_name}"
        return False, f"Failed to start {model_name}"

    def get_available_models(self):
        return MODELS

    def chat(self, messages, model=None, max_tokens=1024, temperature=0.7):
        """Send chat request to local LLM."""
        if model and model != self.active_model:
            self.switch_model(model)

        if not ServiceMonitor.check_port(self.llm_port):
            return {"error": "LLM server not running", "model": self.active_model}

        payload = json.dumps({
            "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "stream": False,
        }).encode('utf-8')

        try:
            conn = http.client.HTTPConnection("localhost", self.llm_port, timeout=120)
            conn.request("POST", "/v1/chat/completions", body=payload,
                        headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = json.loads(resp.read().decode('utf-8'))
            conn.close()
            if "choices" in data and data["choices"]:
                return {"response": data["choices"][0]["message"]["content"],
                        "model": data.get("model", self.active_model),
                        "usage": data.get("usage", {})}
            return {"error": "No response from model", "raw": str(data)[:200]}
        except Exception as e:
            return {"error": str(e)}


class TermuxBridge:
    """Termux API bridge."""
    is_available = False

    def __init__(self):
        result = subprocess.run("which termux-battery-status", shell=True, capture_output=True, timeout=3)
        self.is_available = result.returncode == 0

    def _run(self, cmd, timeout=10):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip() if r.returncode == 0 else None
        except: return None

    def battery(self):
        out = self._run("termux-battery-status")
        return json.loads(out) if out else None

    def wifi(self):
        out = self._run("termux-wifi-connectioninfo")
        return json.loads(out) if out else None

    def notify(self, title, content):
        self._run(f'termux-notification --title "{title}" --content "{content}"'); return True

    def toast(self, text):
        self._run(f'termux-toast "{text}"'); return True

    def ip(self):
        out = self._run("ip route get 1.1.1.1 2>/dev/null | awk '{print $7}'")
        return out.strip() if out else "192.168.1.184"

    def toggle_wifi(self, enable=True):
        self._run(f"termux-wifi-enable {str(enable).lower()}"); return True

    def toggle_flash(self, on=True):
        self._run(f"termux-torch {'on' if on else 'off'}"); return True


class ADBBridge:
    """Wireless ADB management."""
    @staticmethod
    def _run(cmd, timeout=30):
        try:
            r = subprocess.run(f"adb {cmd}", shell=True, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip(), r.returncode
        except: return "", -1

    def devices(self):
        out, _ = self._run("devices -l")
        return [{"serial": p.split()[0], "state": p.split()[1]}
                for l in out.split("\n")[1:] if (p := l.split()) and "device" in l and len(p) >= 2]

    def connect(self, ip, port=5555):
        out, _ = self._run(f"connect {ip}:{port}"); return "connected" in out.lower()

    def shell(self, cmd):
        out, _ = self._run(f"shell {cmd}"); return out

    def info(self):
        if not self.devices(): return None
        info = {}
        for p in ["ro.product.model", "ro.build.version.release", "ro.product.brand"]:
            out, _ = self._run(f"shell getprop {p}"); info[p.split('.')[-1]] = out.strip()
        out, _ = self._run("shell dumpsys battery | grep -E 'level|status' | head -2")
        for l in out.split('\n'):
            if ':' in l: k, v = l.split(':', 1); info[f"battery_{k.strip()}"] = v.strip()
        return info


class ControlPlaneHandler(BaseHTTPRequestHandler):
    monitor = ServiceMonitor()
    llm = LLMManager()
    termux = TermuxBridge()
    adb = ADBBridge()

    def log_message(self, fmt, *args): pass

    def _json(self, data, status=200):
        body = json.dumps(data, indent=2, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, port, path, method="GET", body=None):
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=30)
            headers = {}
            if body and isinstance(body, bytes):
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=body, headers=headers if headers else None)
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            self.send_response(resp.status)
            for h, v in resp.getheaders():
                if h.lower() not in ('transfer-encoding', 'connection'):
                    self.send_header(h, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._json({"error": f"Proxy to port {port} failed: {e}"}, 502)

    def do_GET(self):
        p = self.path.rstrip('/')
        if p in ['/health', '/status', '/']:
            return self._json({"status": "ok", "service": "control-plane", "version": "1.0"})
        if p in ['/full', '/status', '/']:
            return self._json(self.monitor.get_status_report())
        if p.startswith('/proxy/'):
            parts = p.split('/', 3)
            if len(parts) >= 3:
                try: port = int(parts[2]); rest = '/' + parts[3] if len(parts) > 3 else '/'; self._proxy(port, rest)
                except ValueError: self._json({"error": "Invalid port"}, 400)
            return
        if p == '/llm/models': return self._json(self.llm.get_available_models())
        if p == '/termux/battery': return self._json(self.termux.battery() or {"error": "unavailable"})
        if p == '/termux/wifi': return self._json(self.termux.wifi() or {"error": "unavailable"})
        if p == '/termux/ip': return self._json({"ip": self.termux.ip()})
        if p == '/adb/devices': return self._json(self.adb.devices())
        if p == '/adb/info': return self._json(self.adb.info() or {"error": "no device"})
        if p == '/services': return self._json(SERVICES)
        if p == '/dashboard': return self._dashboard()
        self._json({"error": f"Unknown: {p}"}, 404)

    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        body_str = self.rfile.read(cl) if cl > 0 else b'{}'
        try: data = json.loads(body_str)
        except: data = {}
        p = self.path.rstrip('/')

        if p == '/llm/chat':
            result = self.llm.chat(data.get("messages", []), data.get("model"), data.get("max_tokens", 1024), data.get("temperature", 0.7))
            return self._json(result)
        if p == '/llm/switch':
            ok, msg = self.llm.switch_model(data.get("model", "qwen-7b"))
            return self._json({"success": ok, "message": msg})
        if p == '/termux/notify':
            self.termux.notify(data.get("title", "OWL"), data.get("content", "")); return self._json({"ok": True})
        if p == '/termux/toast':
            self.termux.toast(data.get("text", "")); return self._json({"ok": True})
        if p == '/termux/wifi':
            self.termux.toggle_wifi(data.get("enable", True)); return self._json({"ok": True})
        if p == '/termux/flashlight':
            self.termux.toggle_flash(data.get("on", True)); return self._json({"ok": True})
        if p == '/adb/connect':
            if ip := data.get("ip"):
                return self._json({"success": self.adb.connect(ip, data.get("port", 5555))})
            return self._json({"error": "IP required"}, 400)
        if p == '/adb/shell':
            if cmd := data.get("cmd"):
                return self._json({"output": self.adb.shell(cmd)})
            return self._json({"error": "cmd required"}, 400)
        if p.startswith('/proxy/'):
            parts = p.split('/', 3)
            if len(parts) >= 3:
                try: port = int(parts[2]); rest = '/' + parts[3] if len(parts) > 3 else '/'; self._proxy(port, rest, "POST", body_str)
                except ValueError: self._json({"error": "Invalid port"}, 400)
            return
        self._json({"error": f"Unknown: {p}"}, 404)

    def _dashboard(self):
        r = self.monitor.get_status_report()
        rows = ""
        for k, s in r["services"].items():
            c = "#0f0" if s["status"] == "up" else "#f44" if s["status"] == "down" else "#ff0"
            port = f":{s['port']}" if s.get('port') else ""
            rows += f'<tr><td><span style="color:{c}">●</span> {s["name"]}</td><td>{port}</td><td><span style="color:{c}">{s["status"]}</span></td></tr>'
        body = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>OWL Control</title>
<style>body{{background:#0a0a1a;color:#eee;font-family:monospace;padding:20px}}h1{{color:#0f8}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:8px 12px;border:1px solid #333}}th{{background:#1a1a2e}}a{{color:#0f8}}</style></head>
<body><h1>🦉 OWL Control Plane</h1>
<p>Services: {r["summary"]["up"]}/{r["summary"]["total"]} up | {r["timestamp"][:19]}</p>
<table><tr><th>Service</th><th>Port</th><th>Status</th></tr>{rows}</table>
<h2>Quick Access</h2>
<p><a href="/proxy/11434/">LLM</a> | <a href="/proxy/8888/">Code Server</a> | <a href="/proxy/3000/">Portal</a> |
<a href="/proxy/8081/">nginx</a> | <a href="/proxy/18789/">OpenClaw</a></p></body></html>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    log.info(f"OWL Control Plane on port {CONTROL_PORT}")
    srv = HTTPServer(("0.0.0.0", CONTROL_PORT), ControlPlaneHandler)
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.shutdown()

if __name__ == "__main__":
    main()
