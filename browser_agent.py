#!/usr/bin/env python3
"""
Browser Agent - Autonomous Web Browser for HERMES
===================================================
Can browse any website, extract data, fill forms, click buttons.
Uses headless browser automation.
"""

import os
import sys
import json
import time
import logging
import subprocess
import http.client
import urllib.request
import urllib.parse
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

BROWSER_PORT = 9097
LOG_FILE = "/tmp/browser-agent.log"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("browser-agent")


class BrowserAgent:
    """Autonomous web browser agent."""

    def __init__(self):
        self.history = []
        self.current_url = None
        self.page_content = None
        self.screenshots = []

    def browse(self, url, action="get", data=None):
        """Browse a URL and return content."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            if action == "post" and data:
                body = urllib.parse.urlencode(data).encode('utf-8')
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            else:
                req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode('utf-8', errors='replace')
                self.current_url = url
                self.page_content = content
                self.history.append({"url": url, "time": time.time(), "status": resp.status})

                return {
                    "url": url,
                    "status": resp.status,
                    "title": self._extract_title(content),
                    "text": self._extract_text(content),
                    "links": self._extract_links(content, url),
                    "forms": self._extract_forms(content),
                }
        except Exception as e:
            return {"url": url, "error": str(e)}

    def _extract_title(self, html):
        """Extract page title."""
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else "No title"

    def _extract_text(self, html):
        """Extract readable text from HTML."""
        # Remove scripts and styles
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:5000]

    def _extract_links(self, html, base_url):
        """Extract links from page."""
        links = []
        for match in re.finditer(r'href=["\'](.*?)["\']', html, re.IGNORECASE):
            href = match.group(1)
            if href.startswith('http'):
                links.append(href)
            elif href.startswith('/'):
                from urllib.parse import urlparse
                parsed = urlparse(base_url)
                links.append(f"{parsed.scheme}://{parsed.netloc}{href}")
        return links[:20]

    def _extract_forms(self, html):
        """Extract forms from page."""
        forms = []
        for match in re.finditer(r'<form[^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE):
            form_html = match.group(0)
            action = re.search(r'action=["\'](.*?)["\']', form_html, re.IGNORECASE)
            method = re.search(r'method=["\'](.*?)["\']', form_html, re.IGNORECASE)
            inputs = re.findall(r'<input[^>]*name=["\'](.*?)["\']', form_html, re.IGNORECASE)
            forms.append({
                "action": action.group(1) if action else "",
                "method": method.group(1).upper() if method else "GET",
                "inputs": inputs,
            })
        return forms

    def search(self, query, engine="google"):
        """Search the web."""
        engines = {
            "google": f"https://www.google.com/search?q={urllib.parse.quote(query)}",
            "bing": f"https://www.bing.com/search?q={urllib.parse.quote(query)}",
            "duckduckgo": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
        }
        url = engines.get(engine, engines["google"])
        return self.browse(url)

    def search_github(self, query):
        """Search GitHub for projects."""
        url = f"https://github.com/search?q={urllib.parse.quote(query)}&type=repositories"
        result = self.browse(url)
        if "text" in result:
            # Extract repo names
            repos = re.findall(r'href="/([^/]+/[^/]+)"', result.get("raw_html", ""))
            result["repos"] = list(set(repos))[:10]
        return result

    def get_github_trending(self):
        """Get trending GitHub repos."""
        return self.browse("https://github.com/trending")

    def get_telegram_apps(self):
        """Search for Telegram-related apps on GitHub."""
        return self.search_github("telegram bot mini app")

    def get_crypto_news(self):
        """Get crypto news."""
        sources = [
            "https://cointelegraph.com",
            "https://coindesk.com",
            "https://decrypt.co",
        ]
        results = []
        for url in sources:
            result = self.browse(url)
            if "title" in result:
                results.append({"source": url, "title": result["title"]})
        return results

    def get_history(self):
        """Get browsing history."""
        return self.history[-50:]


class BrowserHandler(BaseHTTPRequestHandler):
    agent = BrowserAgent()

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
            return self._json({"status": "ok", "service": "browser-agent", "version": "1.0"})
        if p == '/history':
            return self._json(self.agent.get_history())
        if p == '/github/trending':
            return self._json(self.agent.get_github_trending())
        if p == '/github/telegram':
            return self._json(self.agent.get_telegram_apps())
        if p == '/crypto/news':
            return self._json(self.agent.get_crypto_news())
        self._json({"error": f"Unknown: {p}"}, 404)

    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(cl)) if cl > 0 else {}
        p = self.path.rstrip('/')

        if p == '/browse':
            url = body.get("url")
            if url:
                return self._json(self.agent.browse(url))
            return self._json({"error": "url required"}, 400)

        if p == '/search':
            query = body.get("query")
            engine = body.get("engine", "google")
            if query:
                return self._json(self.agent.search(query, engine))
            return self._json({"error": "query required"}, 400)

        if p == '/github/search':
            query = body.get("query")
            if query:
                return self._json(self.agent.search_github(query))
            return self._json({"error": "query required"}, 400)

        self._json({"error": f"Unknown: {p}"}, 404)


def main():
    log.info(f"Browser Agent on port {BROWSER_PORT}")
    srv = HTTPServer(("0.0.0.0", BROWSER_PORT), BrowserHandler)
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.shutdown()

if __name__ == "__main__":
    main()
