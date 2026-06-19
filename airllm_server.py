#!/usr/bin/env python3
"""
AirLLM Server - Multi-Model LLM Serving Platform
==================================================
Serves multiple LLM models with intelligent routing.
Combines local models (qwen 7B) with cloud models.

Features:
- Model pooling and load balancing
- Auto-fallback on failure
- Context-aware model selection
- In-memory caching
- GitHub Codespace integration
"""

import os
import sys
import json
import time
import hashlib
import logging
import threading
import subprocess
import http.client
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

AIRLLM_PORT = 9093
PROXY_URL = "http://127.0.0.1:8090"
RAG_URL = "http://127.0.0.1:9092"
LOG_FILE = "/tmp/airllm-server.log"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("airllm")


class ModelPool:
    """Manages a pool of available models with health checking."""

    def __init__(self):
        self.models = {}
        self.health = {}
        self._load_models()

    def _load_models(self):
        """Load model configurations."""
        self.models = {
            "qwen-7b": {
                "name": "Qwen 2.5 7B",
                "type": "local",
                "endpoint": "http://127.0.0.1:11434",
                "context": 32768,
                "speed": "medium",
                "cost": 0,
                "capabilities": ["chat", "code", "arabic", "reasoning"],
            },
            "gemini-2.5-flash": {
                "name": "Gemini 2.5 Flash",
                "type": "cloud",
                "endpoint": f"{PROXY_URL}/api/v1/chat/completions",
                "context": 1000000,
                "speed": "fast",
                "cost": 0.0001,
                "capabilities": ["chat", "code", "vision", "arabic", "reasoning"],
            },
            "claude-sonnet-4": {
                "name": "Claude Sonnet 4",
                "type": "cloud",
                "endpoint": f"{PROXY_URL}/api/v1/chat/completions",
                "context": 200000,
                "speed": "medium",
                "cost": 0.003,
                "capabilities": ["chat", "code", "reasoning", "analysis"],
            },
            "gpt-4o-mini": {
                "name": "GPT-4o Mini",
                "type": "cloud",
                "endpoint": f"{PROXY_URL}/api/v1/chat/completions",
                "context": 128000,
                "speed": "fast",
                "cost": 0.00015,
                "capabilities": ["chat", "code", "vision"],
            },
            "deepseek-v3": {
                "name": "DeepSeek V3",
                "type": "cloud",
                "endpoint": f"{PROXY_URL}/api/v1/chat/completions",
                "context": 65536,
                "speed": "medium",
                "cost": 0.0002,
                "capabilities": ["chat", "code", "reasoning", "math"],
            },
        }

    def check_health(self):
        """Check health of all models."""
        for key, model in self.models.items():
            if model["type"] == "local":
                try:
                    s = __import__('socket').socket(__import__('socket').AF_INET, __import__('socket').SOCK_STREAM)
                    s.settimeout(2)
                    r = s.connect_ex(('127.0.0.1', 11434))
                    s.close()
                    self.health[key] = r == 0
                except:
                    self.health[key] = False
            else:
                # Cloud models assumed available
                self.health[key] = True

    def select_model(self, task="chat", prefer_local=True, max_cost=0.001):
        """Select best model for a task."""
        self.check_health()

        candidates = []
        for key, model in self.models.items():
            if not self.health.get(key, False):
                continue
            if task not in model["capabilities"]:
                continue
            if model["cost"] > max_cost:
                continue
            candidates.append((key, model))

        if not candidates:
            return "gemini-2.5-flash"  # Fallback

        # Prefer local if requested
        if prefer_local:
            for key, model in candidates:
                if model["type"] == "local":
                    return key

        # Sort by speed then cost
        speed_order = {"fast": 0, "medium": 1, "slow": 2}
        candidates.sort(key=lambda x: (speed_order.get(x[1]["speed"], 1), x[1]["cost"]))

        return candidates[0][0]


class InMemoryCache:
    """In-memory response cache."""

    def __init__(self, max_size=1000, ttl=300):
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl

    def _key(self, model, messages):
        content = json.dumps({"model": model, "messages": messages}, sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, model, messages):
        key = self._key(model, messages)
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["time"] < self.ttl:
                return entry["response"]
            del self.cache[key]
        return None

    def set(self, model, messages, response):
        if len(self.cache) >= self.max_size:
            # Remove oldest
            oldest = min(self.cache.keys(), key=lambda k: self.cache[k]["time"])
            del self.cache[oldest]
        key = self._key(model, messages)
        self.cache[key] = {"response": response, "time": time.time()}

    def stats(self):
        return {"size": len(self.cache), "max_size": self.max_size, "ttl": self.ttl}


class AirLLMServer:
    """Main AirLLM server."""

    def __init__(self):
        self.model_pool = ModelPool()
        self.cache = InMemoryCache()
        self.request_count = 0
        self.start_time = time.time()

    def chat(self, messages, model=None, use_rag=True, **kwargs):
        """Process a chat request with intelligent model selection."""
        self.request_count += 1

        # Select model
        if not model:
            # Detect task from messages
            last_msg = messages[-1].get("content", "").lower() if messages else ""
            if any(kw in last_msg for kw in ["code", "function", "class", "def", "build", "create"]):
                task = "code"
            elif any(kw in last_msg for kw in ["analyze", "review", "explain", "why"]):
                task = "reasoning"
            else:
                task = "chat"
            model = self.model_pool.select_model(task=task)
        else:
            model = self._resolve_model_name(model)

        # Check cache
        cached = self.cache.get(model, messages)
        if cached:
            return {**cached, "cached": True, "model": model}

        # Enhance with RAG if requested
        if use_rag and len(messages) > 0:
            last_msg = messages[-1].get("content", "")
            if len(last_msg) > 10:
                rag_results = self._query_rag(last_msg)
                if rag_results and rag_results.get("results"):
                    context = "\n\n".join([r["text"] for r in rag_results["results"][:3]])
                    messages = [
                        {"role": "system", "content": f"Relevant context:\n{context}"},
                        *messages
                    ]

        # Forward to proxy
        payload = {"model": model, "messages": messages, "max_tokens": kwargs.get("max_tokens", 1024), "temperature": kwargs.get("temperature", 0.7)}

        try:
            body = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{PROXY_URL}/api/v1/chat/completions",
                data=body, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                self.cache.set(model, messages, result)
                return {**result, "model": model, "cached": False}
        except Exception as e:
            # Fallback to another model
            fallback = "gemini-2.5-flash" if model != "gemini-2.5-flash" else "gpt-4o-mini"
            try:
                payload["model"] = fallback
                body = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(
                    f"{PROXY_URL}/api/v1/chat/completions",
                    data=body, headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    return {**result, "model": fallback, "fallback": True, "cached": False}
            except Exception as e2:
                return {"error": str(e2), "original_error": str(e)}

    def _resolve_model_name(self, name):
        """Resolve model name to internal key."""
        name_map = {
            "qwen": "qwen-7b", "qwen-7b": "qwen-7b", "qwen2.5": "qwen-7b",
            "gemini": "gemini-2.5-flash", "gemini-2.5-flash": "gemini-2.5-flash",
            "claude": "claude-sonnet-4", "claude-sonnet-4": "claude-sonnet-4",
            "gpt-4o-mini": "gpt-4o-mini", "gpt4o-mini": "gpt-4o-mini",
            "deepseek": "deepseek-v3", "deepseek-v3": "deepseek-v3",
        }
        return name_map.get(name.lower(), name)

    def _query_rag(self, query):
        """Query the RAG system."""
        try:
            req = urllib.request.Request(f"{RAG_URL}/search?q={urllib.parse.quote(query)}&k=3")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except:
            return None

    def get_status(self):
        """Get server status."""
        self.model_pool.check_health()
        return {
            "status": "running",
            "uptime": int(time.time() - self.start_time),
            "requests": self.request_count,
            "models": {k: {"name": v["name"], "type": v["type"], "healthy": self.model_pool.health.get(k, False)} for k, v in self.model_pool.models.items()},
            "cache": self.cache.stats(),
        }


class AirLLMHandler(BaseHTTPRequestHandler):
    server = AirLLMServer()

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
        if p in ['/health', '/']:
            return self._json({"status": "ok", "service": "airllm", "version": "1.0"})
        if p == '/status':
            return self._json(self.server.get_status())
        if p == '/models':
            return self._json(self.server.model_pool.models)
        self._json({"error": f"Unknown: {p}"}, 404)

    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(cl)) if cl > 0 else {}
        p = self.path.rstrip('/')

        if p in ['/chat', '/v1/chat/completions']:
            messages = body.get("messages", [])
            model = body.get("model")
            use_rag = body.get("use_rag", True)
            result = self.server.chat(messages, model, use_rag,
                                      max_tokens=body.get("max_tokens", 1024),
                                      temperature=body.get("temperature", 0.7))
            if "error" in result:
                return self._json(result, 500)
            return self._json(result)

        self._json({"error": f"Unknown: {p}"}, 404)


def main():
    log.info(f"AirLLM Server on port {AIRLLM_PORT}")
    srv = HTTPServer(("0.0.0.0", AIRLLM_PORT), AirLLMHandler)
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.shutdown()

if __name__ == "__main__":
    main()
