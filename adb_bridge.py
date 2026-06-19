#!/usr/bin/env python3
"""
OWL ADB Bridge - Wireless Android Connection
=============================================
Connects to Android devices over WiFi without USB.
Auto-discovers devices on network.
"""

import os
import sys
import json
import time
import socket
import logging
import subprocess
import http.client
from http.server import HTTPServer, BaseHTTPRequestHandler

ADB_BRIDGE_PORT = 9091
LOG_FILE = "/tmp/adb-bridge.log"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("adb-bridge")


class ADBManager:
    @staticmethod
    def run(cmd, timeout=30):
        try:
            r = subprocess.run(f"adb {cmd}", shell=True, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip(), r.returncode
        except: return "", -1

    def devices(self):
        out, _ = self.run("devices -l")
        devs = []
        for line in out.split("\n")[1:]:
            if line.strip() and "device" in line:
                parts = line.split()
                devs.append({"serial": parts[0], "state": parts[1], "details": " ".join(parts[2:]) if len(parts) > 2 else ""})
        return devs

    def connect(self, ip, port=5555):
        out, _ = self.run(f"connect {ip}:{port}")
        return "connected" in out.lower() or "already connected" in out.lower()

    def disconnect(self, ip, port=5555):
        self.run(f"disconnect {ip}:{port}")

    def shell(self, cmd):
        out, rc = self.run(f'shell "{cmd}"')
        return out

    def push(self, local, remote):
        out, rc = self.run(f'push "{local}" "{remote}"')
        return rc == 0

    def pull(self, remote, local):
        out, rc = self.run(f'pull "{remote}" "{local}"')
        return rc == 0

    def info(self):
        devs = self.devs()
        if not devs: return None
        info = {}
        for p in ["ro.product.model", "ro.build.version.release", "ro.product.brand", "ro.product.name"]:
            out, _ = self.run(f"shell getprop {p}")
            info[p.split('.')[-1]] = out.strip()
        out, _ = self.run("shell dumpsys battery")
        for line in out.split('\n'):
            if 'level:' in line: info['battery_level'] = line.split(':')[-1].strip()
            elif 'status:' in line: info['battery_status'] = line.split(':')[-1].strip()
            elif 'temperature:' in line: info['battery_temp'] = line.split(':')[-1].strip()
        out, _ = self.run("shell ip route | grep src | awk '{print $9}'")
        info['ip'] = out.strip()
        return info

    def scan(self, base="192.168.1", start=1, end=254, port=5555):
        found = []
        for i in range(start, end + 1):
            ip = f"{base}.{i}"
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.3)
                r = s.connect_ex((ip, port))
                s.close()
                if r == 0:
                    found.append(ip)
            except: pass
        return found

    def termux_shell(self, cmd):
        """Run command in Termux environment."""
        return self.shell(f"/data/data/com.termux/files/usr/bin/{cmd}")

    def termux_api(self, api_cmd):
        """Run Termux API command."""
        return self.shell(f"termux-{api_cmd}")


class ADBHandler(BaseHTTPRequestHandler):
    adb = ADBManager()

    def log_message(self, fmt, *args): pass

    def _json(self, data, status=200):
        body = json.dumps(data, indent=2, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.rstrip('/')
        if p == '/devices': return self._json(self.adb.devices())
        if p == '/info': return self._json(self.adb.info() or {"error": "no device"})
        if p == '/scan': return self._json({"devices": self.adb.scan()})
        if p == '/health': return self._json({"status": "ok", "devices": len(self.adb.devices())})
        self._json({"error": f"Unknown: {p}"}, 404)

    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(cl)) if cl > 0 else {}
        p = self.path.rstrip('/')

        if p == '/connect':
            ip = body.get("ip")
            if ip:
                return self._json({"success": self.adb.connect(ip, body.get("port", 5555))})
            return self._json({"error": "IP required"}, 400)

        if p == '/shell':
            cmd = body.get("cmd", "")
            if cmd:
                return self._json({"output": self.adb.shell(cmd)})
            return self._json({"error": "cmd required"}, 400)

        if p == '/termux':
            cmd = body.get("cmd", "")
            if cmd:
                return self._json({"output": self.adb.termux_shell(cmd)})
            return self._json({"error": "cmd required"}, 400)

        if p == '/push':
            local = body.get("local", "")
            remote = body.get("remote", "")
            if local and remote:
                return self._json({"success": self.adb.push(local, remote)})
            return self._json({"error": "local and remote required"}, 400)

        if p == '/pull':
            remote = body.get("remote", "")
            local = body.get("local", "")
            if remote and local:
                return self._json({"success": self.adb.pull(remote, local)})
            return self._json({"error": "remote and local required"}, 400)

        self._json({"error": f"Unknown: {p}"}, 404)


def main():
    log.info(f"ADB Bridge on port {ADB_BRIDGE_PORT}")
    srv = HTTPServer(("0.0.0.0", ADB_BRIDGE_PORT), ADBHandler)
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.shutdown()

if __name__ == "__main__":
    main()
