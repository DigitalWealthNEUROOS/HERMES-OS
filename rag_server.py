#!/usr/bin/env python3
"""
Qwen 2.5 7B RAG Server - In-Memory Knowledge Base
===================================================
Server-side RAG that learns from Hermes Agent interactions.
All data stored in RAM (no disk). Uses multiple server databases.

Data sources:
- Hermes Agent session history (ClawMem)
- Server databases (Redis, SQLite in-memory)
- GitHub repositories (codespace, issues, PRs)
- Telegram conversations
- Web scraping results
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

RAG_PORT = 9092
LOG_FILE = "/tmp/rag-server.log"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("rag-server")


class InMemoryVectorDB:
    """Pure in-memory vector database - no disk storage."""

    def __init__(self):
        self.documents = []  # [{"id": str, "text": str, "embedding": list, "metadata": dict, "timestamp": float}]
        self.index = {}  # word -> [doc_ids] for fast keyword search
        self.max_docs = 10000

    def _tokenize(self, text):
        """Simple tokenization."""
        return text.lower().split()

    def _simple_embedding(self, text):
        """Create a simple hash-based embedding (no ML needed)."""
        tokens = self._tokenize(text)
        # Create a 128-dim vector based on word hashes
        vec = [0.0] * 128
        for token in tokens:
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            for i in range(128):
                vec[i] += ((h >> (i % 32)) & 1) * 2 - 1
        # Normalize
        mag = sum(x * x for x in vec) ** 0.5
        if mag > 0:
            vec = [x / mag for x in vec]
        return vec

    def add(self, text, metadata=None):
        """Add a document to the in-memory store."""
        doc_id = hashlib.md5(f"{text}{time.time()}".encode()).hexdigest()[:16]
        embedding = self._simple_embedding(text)

        doc = {
            "id": doc_id,
            "text": text[:2000],  # Limit text size
            "embedding": embedding,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }

        self.documents.append(doc)

        # Update keyword index
        for token in self._tokenize(text):
            if token not in self.index:
                self.index[token] = []
            self.index[token].append(doc_id)

        # Trim if too large
        if len(self.documents) > self.max_docs:
            removed = self.documents.pop(0)
            for token in self._tokenize(removed["text"]):
                if token in self.index and removed["id"] in self.index[token]:
                    self.index[token].remove(removed["id"])

        return doc_id

    def search(self, query, top_k=5):
        """Search for relevant documents."""
        query_emb = self._simple_embedding(query)
        query_tokens = self._tokenize(query)

        # Score documents
        scores = {}
        for doc in self.documents:
            # Cosine similarity
            emb_score = sum(a * b for a, b in zip(query_emb, doc["embedding"]))

            # Keyword overlap
            doc_tokens = set(self._tokenize(doc["text"]))
            keyword_score = len(set(query_tokens) & doc_tokens) / max(len(query_tokens), 1)

            # Combined score
            scores[doc["id"]] = emb_score * 0.6 + keyword_score * 0.4

        # Return top_k
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_k]
        return [
            {**doc, "score": scores[doc["id"]]}
            for doc in self.documents
            if doc["id"] in sorted_ids
        ]

    def get_stats(self):
        return {
            "total_documents": len(self.documents),
            "index_size": len(self.index),
            "memory_estimate_mb": len(self.documents) * 2,  # ~2KB per doc
        }


class HermesSessionLearner:
    """Learns from Hermes Agent session history."""

    def __init__(self, vector_db):
        self.db = vector_db

    def learn_from_clawmem(self):
        """Extract knowledge from ClawMem MCP server."""
        try:
            # Query ClawMem for recent memories
            result = subprocess.run(
                ["node", "-e", """
const {execSync} = require('child_process');
try {
  const out = execSync('clawmem query "hermes agent" --limit 50 --json 2>/dev/null', {timeout: 5000});
  console.log(out.toString());
} catch(e) { console.log('[]'); }
"""],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                try:
                    memories = json.loads(result.stdout.strip())
                    for mem in memories:
                        text = mem.get("content", mem.get("text", ""))
                        if text and len(text) > 20:
                            self.db.add(text, {"source": "clawmem", "type": "memory"})
                    log.info(f"Learned {len(memories)} memories from ClawMem")
                    return len(memories)
                except:
                    pass
        except Exception as e:
            log.warning(f"ClawMem learning failed: {e}")
        return 0

    def learn_from_sessions(self):
        """Learn from Hermes session transcripts."""
        try:
            # Read recent session files
            result = subprocess.run(
                "find /root/.hermes/sessions -name '*.json' -mmin -1440 2>/dev/null | head -10",
                shell=True, capture_output=True, text=True, timeout=5
            )
            files = result.stdout.strip().split("\n") if result.returncode == 0 else []
            count = 0
            for f in files:
                if not f:
                    continue
                try:
                    with open(f, 'r') as fh:
                        data = json.load(fh)
                    # Extract conversations
                    if isinstance(data, list):
                        for item in data:
                            text = str(item.get("content", ""))
                            if text and len(text) > 30:
                                self.db.add(text[:1000], {"source": "session", "file": f})
                                count += 1
                    elif isinstance(data, dict):
                        for key in ["messages", "history", "conversation"]:
                            if key in data and isinstance(data[key], list):
                                for item in data[key]:
                                    text = str(item.get("content", item if isinstance(item, str) else ""))
                                    if text and len(text) > 30:
                                        self.db.add(text[:1000], {"source": "session", "file": f})
                                        count += 1
                except:
                    pass
            log.info(f"Learned {count} items from session files")
            return count
        except Exception as e:
            log.warning(f"Session learning failed: {e}")
        return 0

    def learn_from_telegram(self):
        """Learn from Telegram conversation history stored in Redis."""
        try:
            result = subprocess.run(
                "redis-cli LRANGE telegram:history 0 99 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                messages = result.stdout.strip().split("\n")
                count = 0
                for msg in messages:
                    if msg and len(msg) > 20:
                        self.db.add(msg[:1000], {"source": "telegram"})
                        count += 1
                log.info(f"Learned {count} messages from Telegram history")
                return count
        except Exception as e:
            log.warning(f"Telegram learning failed: {e}")
        return 0

    def learn_from_github(self, token=None):
        """Learn from GitHub repositories, issues, PRs."""
        if not token:
            return 0
        try:
            headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            count = 0

            # Get user repos
            req = urllib.request.Request("https://api.github.com/user/repos?per_page=10", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                repos = json.loads(resp.read().decode())
            for repo in repos[:5]:
                desc = repo.get("description", "")
                name = repo.get("name", "")
                if desc:
                    self.db.add(f"GitHub repo {name}: {desc}", {"source": "github", "type": "repo"})
                    count += 1

            # Get recent issues
            req = urllib.request.Request(
                "https://api.github.com/user/issues?state=all&per_page=10", headers=headers
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                issues = json.loads(resp.read().decode())
            for issue in issues[:10]:
                title = issue.get("title", "")
                body = issue.get("body", "")[:500] if issue.get("body") else ""
                if title:
                    self.db.add(f"Issue: {title}\n{body}", {"source": "github", "type": "issue"})
                    count += 1

            log.info(f"Learned {count} items from GitHub")
            return count
        except Exception as e:
            log.warning(f"GitHub learning failed: {e}")
        return 0

    def learn_all(self, github_token=None):
        """Learn from all available sources."""
        total = 0
        total += self.learn_from_clawmem()
        total += self.learn_from_sessions()
        total += self.learn_from_telegram()
        total += self.learn_from_github(github_token)
        log.info(f"Total learned: {total} items")
        return total


class RAGServer:
    """Main RAG server combining all components."""

    def __init__(self):
        self.vector_db = InMemoryVectorDB()
        self.learner = HermesSessionLearner(self.vector_db)
        self.github_token = self._load_github_token()
        self._start_background_learning()

    def _load_github_token(self):
        """Load GitHub token from env."""
        try:
            with open('/root/.hermes/.env', 'r') as f:
                for line in f:
                    if line.strip().startswith('GITHUB_TOKEN'):
                        return line.strip().split('=', 1)[1]
                    elif line.strip().startswith('GITHUB_PAT'):
                        return line.strip().split('=', 1)[1]
        except:
            pass
        return None

    def _start_background_learning(self):
        """Start background learning thread."""
        def learn_loop():
            while True:
                try:
                    self.learner.learn_all(self.github_token)
                except Exception as e:
                    log.error(f"Background learning error: {e}")
                time.sleep(300)  # Learn every 5 minutes

        t = threading.Thread(target=learn_loop, daemon=True)
        t.start()
        log.info("Background learning started")

    def query(self, question, top_k=5):
        """Query the RAG system."""
        results = self.vector_db.search(question, top_k)
        return {
            "question": question,
            "results": [
                {
                    "text": r["text"][:500],
                    "score": round(r["score"], 3),
                    "source": r["metadata"].get("source", "unknown"),
                    "type": r["metadata"].get("type", "unknown"),
                }
                for r in results
            ],
            "total_docs": len(self.vector_db.documents),
        }

    def add_knowledge(self, text, source="manual"):
        """Add knowledge to the RAG system."""
        doc_id = self.vector_db.add(text, {"source": source, "type": "manual"})
        return {"id": doc_id, "status": "added"}

    def get_stats(self):
        """Get RAG system stats."""
        return {
            "vector_db": self.vector_db.get_stats(),
            "github_token": bool(self.github_token),
            "uptime": time.time(),
        }


class RAGHandler(BaseHTTPRequestHandler):
    rag = RAGServer()

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
            return self._json({"status": "ok", "service": "rag-server", "version": "1.0"})
        if p == '/stats':
            return self._json(self.rag.get_stats())
        if p.startswith('/search'):
            import urllib.parse
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            query = params.get('q', [''])[0]
            top_k = int(params.get('k', [5])[0])
            if query:
                return self._json(self.rag.query(query, top_k))
            return self._json({"error": "Query parameter 'q' required"}, 400)
        self._json({"error": f"Unknown: {p}"}, 404)

    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(cl)) if cl > 0 else {}
        p = self.path.rstrip('/')

        if p == '/query':
            query = body.get("query", "")
            top_k = body.get("top_k", 5)
            if query:
                return self._json(self.rag.query(query, top_k))
            return self._json({"error": "query required"}, 400)

        if p == '/add':
            text = body.get("text", "")
            source = body.get("source", "manual")
            if text:
                return self._json(self.rag.add_knowledge(text, source))
            return self._json({"error": "text required"}, 400)

        if p == '/learn':
            count = self.rag.learner.learn_all(self.rag.github_token)
            return self._json({"learned": count})

        self._json({"error": f"Unknown: {p}"}, 404)


def main():
    log.info(f"RAG Server on port {RAG_PORT}")
    srv = HTTPServer(("0.0.0.0", RAG_PORT), RAGHandler)
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.shutdown()

if __name__ == "__main__":
    main()
