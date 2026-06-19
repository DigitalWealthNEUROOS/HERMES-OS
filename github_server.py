#!/usr/bin/env python3
"""
GitHub Integration Server
==========================
Manages GitHub OAuth, Codespace, and API access for Hermes + Qwen.
Provides token management, codespace control, and repo operations.
"""

import os
import sys
import json
import time
import logging
import subprocess
import http.client
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

GITHUB_PORT = 9094
LOG_FILE = "/tmp/github-server.log"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("github-server")


class GitHubManager:
    """Manages GitHub operations via gh CLI."""

    def __init__(self):
        self._verify_auth()

    def _verify_auth(self):
        """Verify GitHub authentication."""
        try:
            r = subprocess.run("gh auth status 2>&1", shell=True, capture_output=True, text=True, timeout=10)
            self.authenticated = "Logged in" in r.stdout
            if self.authenticated:
                # Get token
                r2 = subprocess.run("gh auth token 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
                self.token = r2.stdout.strip()
                # Get username
                r3 = subprocess.run("gh api user --jq '.login' 2>/dev/null", shell=True, capture_output=True, text=True, timeout=10)
                self.username = r3.stdout.strip()
                # Get email
                r4 = subprocess.run("gh api user --jq '.email' 2>/dev/null", shell=True, capture_output=True, text=True, timeout=10)
                self.email = r4.stdout.strip()
            else:
                self.token = None
                self.username = None
                self.email = None
        except:
            self.authenticated = False
            self.token = None
            self.username = None
            self.email = None

    def _gh(self, cmd, timeout=30):
        """Run gh CLI command."""
        try:
            r = subprocess.run(f"gh {cmd}", shell=True, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip(), r.returncode
        except:
            return "", -1

    def _api(self, path, method="GET", data=None):
        """Make GitHub API request."""
        if not self.token:
            return None
        try:
            url = f"https://api.github.com{path}"
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
            }
            body = json.dumps(data).encode('utf-8') if data else None
            if body:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            log.error(f"API error: {e}")
            return None

    def get_status(self):
        """Get GitHub status."""
        self._verify_auth()
        return {
            "authenticated": self.authenticated,
            "username": self.username,
            "email": self.email,
            "token_scopes": self._get_scopes(),
        }

    def _get_scopes(self):
        """Get token scopes."""
        if not self.token:
            return []
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={"Authorization": f"token {self.token}"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.headers.get("X-OAuth-Scopes", "").split(", ")
        except:
            return []

    def get_repos(self, per_page=10):
        """Get user repositories."""
        out, rc = self._gh(f"repo list --limit {per_page} --json name,description,language,updatedAt,stargazerCount")
        if rc == 0 and out:
            try:
                return json.loads(out)
            except:
                pass
        return []

    def get_repo(self, name):
        """Get repository details."""
        out, rc = self._gh(f"repo view {name} --json name,description,language,defaultBranchRef,stargazerCount,forkCount")
        if rc == 0 and out:
            try:
                return json.loads(out)
            except:
                pass
        return None

    def create_repo(self, name, description="", private=False):
        """Create a new repository."""
        visibility = "--private" if private else "--public"
        out, rc = self._gh(f"repo create {name} {visibility} --description '{description}'")
        return rc == 0

    def get_codespaces(self):
        """List codespaces."""
        out, rc = self._gh("codespace list --json name,state,repository,createdAt")
        if rc == 0 and out:
            try:
                return json.loads(out)
            except:
                pass
        return []

    def create_codespace(self, repo, branch="main"):
        """Create a new codespace."""
        out, rc = self._gh(f"codespace create -r {repo} -b {branch}", timeout=60)
        return rc == 0, out

    def get_issues(self, repo=None, state="open", per_page=10):
        """Get issues."""
        if repo:
            out, rc = self._gh(f"issue list -R {repo} --state {state} --limit {per_page} --json number,title,state,createdAt")
        else:
            out, rc = self._gh(f"issue list --state {state} --limit {per_page} --json number,title,state,createdAt")
        if rc == 0 and out:
            try:
                return json.loads(out)
            except:
                pass
        return []

    def get_prs(self, repo, state="open"):
        """Get pull requests."""
        out, rc = self._gh(f"pr list -R {repo} --state {state} --json number,title,state,createdAt")
        if rc == 0 and out:
            try:
                return json.loads(out)
            except:
                pass
        return []

    def run_workflow(self, repo, workflow, ref="main", inputs=None):
        """Trigger a workflow."""
        cmd = f"workflow run -R {repo} {workflow} --ref {ref}"
        if inputs:
            for k, v in inputs.items():
                cmd += f" -f {k}={v}"
        out, rc = self._gh(cmd, timeout=30)
        return rc == 0

    def get_rate_limit(self):
        """Get API rate limit status."""
        return self._api("/rate_limit")


class GitHubHandler(BaseHTTPRequestHandler):
    gh = GitHubManager()

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
            return self._json({"status": "ok", "service": "github-server", "version": "1.0"})
        if p == '/status':
            return self._json(self.gh.get_status())
        if p == '/repos':
            return self._json(self.gh.get_repos())
        if p == '/codespaces':
            return self._json(self.gh.get_codespaces())
        if p == '/issues':
            return self._json(self.gh.get_issues())
        if p == '/rate_limit':
            return self._json(self.gh.get_rate_limit())
        self._json({"error": f"Unknown: {p}"}, 404)

    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(cl)) if cl > 0 else {}
        p = self.path.rstrip('/')

        if p == '/repo/create':
            name = body.get("name", "")
            desc = body.get("description", "")
            private = body.get("private", False)
            if name:
                return self._json({"success": self.gh.create_repo(name, desc, private)})
            return self._json({"error": "name required"}, 400)

        if p == '/codespace/create':
            repo = body.get("repo", "")
            branch = body.get("branch", "main")
            if repo:
                success, msg = self.gh.create_codespace(repo, branch)
                return self._json({"success": success, "message": msg})
            return self._json({"error": "repo required"}, 400)

        self._json({"error": f"Unknown: {p}"}, 404)


def main():
    log.info(f"GitHub Server on port {GITHUB_PORT}")
    srv = HTTPServer(("0.0.0.0", GITHUB_PORT), GitHubHandler)
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.shutdown()

if __name__ == "__main__":
    main()
