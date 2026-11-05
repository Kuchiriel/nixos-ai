#!/usr/bin/env python3
"""GitHub MCP Server — exposes GitHub API as MCP tools.

Run: python3 github_mcp.py (stdio) or python3 github_mcp.py --http 8093
Auth: GITHUB_TOKEN env (classic PAT or fine-grained) + GITHUB_REPO (owner/name)
"""

from __future__ import annotations

import json
import os
import sys
import argparse
from typing import Any
from urllib import request, error

GITHUB_API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPO", "")  # "owner/repo"

if not TOKEN or not REPO:
    sys.stderr.write("GITHUB_TOKEN and GITHUB_REPO required\n")
    sys.exit(1)


def _req(method: str, path: str, body: Any = None, params: dict | None = None) -> Any:
    url = f"{GITHUB_API}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{qs}"
    data = json.dumps(body).encode() if body else None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except error.HTTPError as e:
        return {"error": e.code, "message": e.read().decode()}


# ── Tools ────────────────────────────────────────────────────────────────

def github_pr_list(state: str = "open", base: str = "", head: str = "", per_page: int = 30) -> dict:
    """List PRs. state: open|closed|all. base/head optional branch filters."""
    params = {"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"}
    if base:
        params["base"] = base
    if head:
        params["head"] = head
    return _req("GET", f"/repos/{REPO}/pulls", params=params)


def github_pr_get(number: int) -> dict:
    """Get PR details (includes diff_url, mergeable_state, review_decision)."""
    return _req("GET", f"/repos/{REPO}/pulls/{number}")


def github_pr_diff(number: int) -> dict:
    """Get PR diff (raw)."""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github.v3.diff",
    }
    url = f"{GITHUB_API}/repos/{REPO}/pulls/{number}"
    req = request.Request(url, headers=headers)
    try:
        with request.urlopen(req, timeout=30) as resp:
            return {"diff": resp.read().decode()}
    except error.HTTPError as e:
        return {"error": e.code, "message": e.read().decode()}


def github_pr_comment(number: int, body: str) -> dict:
    """Comment on a PR."""
    return _req("POST", f"/repos/{REPO}/issues/{number}/comments", {"body": body})


def github_pr_review(number: int, event: str, body: str = "") -> dict:
    """Submit PR review. event: APPROVE|REQUEST_CHANGES|COMMENT."""
    return _req("POST", f"/repos/{REPO}/pulls/{number}/reviews", {"event": event, "body": body})


def github_issue_create(title: str, body: str = "", labels: list[str] | None = None, assignees: list[str] | None = None) -> dict:
    """Create an issue."""
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees
    return _req("POST", f"/repos/{REPO}/issues", payload)


def github_issue_list(state: str = "open", labels: str = "", per_page: int = 30) -> dict:
    """List issues. labels: comma-separated."""
    params = {"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"}
    if labels:
        params["labels"] = labels
    return _req("GET", f"/repos/{REPO}/issues", params=params)


def github_workflow_list() -> dict:
    """List workflows."""
    return _req("GET", f"/repos/{REPO}/actions/workflows")


def github_workflow_run(workflow_id: str | int, ref: str = "main", inputs: dict | None = None) -> dict:
    """Trigger a workflow_dispatch."""
    return _req("POST", f"/repos/{REPO}/actions/workflows/{workflow_id}/dispatches", {"ref": ref, "inputs": inputs or {}})


def github_workflow_runs(workflow_id: str | int, per_page: int = 20) -> dict:
    """List recent workflow runs."""
    return _req("GET", f"/repos/{REPO}/actions/workflows/{workflow_id}/runs", params={"per_page": per_page})


def github_repo_info() -> dict:
    """Get repo metadata (default_branch, branches_url, etc.)."""
    return _req("GET", f"/repos/{REPO}")


# ── MCP Protocol ────────────────────────────────────────────────────────

TOOLS = {
    "github_pr_list": {
        "description": "List PRs (open/closed/all) with optional base/head filters",
        "parameters": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "base": {"type": "string", "description": "Filter by base branch"},
                "head": {"type": "string", "description": "Filter by head branch"},
                "per_page": {"type": "integer", "default": 30},
            },
        },
    },
    "github_pr_get": {
        "description": "Get PR details (diff_url, mergeable_state, review_decision, etc.)",
        "parameters": {"type": "object", "properties": {"number": {"type": "integer"}}, "required": ["number"]},
    },
    "github_pr_diff": {
        "description": "Get PR diff (raw text)",
        "parameters": {"type": "object", "properties": {"number": {"type": "integer"}}, "required": ["number"]},
    },
    "github_pr_comment": {
        "description": "Comment on a PR",
        "parameters": {"type": "object", "properties": {"number": {"type": "integer"}, "body": {"type": "string"}}, "required": ["number", "body"]},
    },
    "github_pr_review": {
        "description": "Submit PR review (APPROVE/REQUEST_CHANGES/COMMENT)",
        "parameters": {"type": "object", "properties": {"number": {"type": "integer"}, "event": {"type": "string", "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"]}, "body": {"type": "string", "default": ""}}, "required": ["number", "event"]},
    },
    "github_issue_create": {
        "description": "Create an issue",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string", "default": ""}, "labels": {"type": "array", "items": {"type": "string"}}, "assignees": {"type": "array", "items": {"type": "string"}}}, "required": ["title"]},
    },
    "github_issue_list": {
        "description": "List issues with optional label filter",
        "parameters": {"type": "object", "properties": {"state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"}, "labels": {"type": "string", "description": "Comma-separated labels"}, "per_page": {"type": "integer", "default": 30}}},
    },
    "github_workflow_list": {"description": "List workflows", "parameters": {"type": "object", "properties": {}}},
    "github_workflow_run": {
        "description": "Trigger workflow_dispatch",
        "parameters": {"type": "object", "properties": {"workflow_id": {"type": ["string", "integer"]}, "ref": {"type": "string", "default": "main"}, "inputs": {"type": "object"}}, "required": ["workflow_id"]},
    },
    "github_workflow_runs": {
        "description": "List recent workflow runs",
        "parameters": {"type": "object", "properties": {"workflow_id": {"type": ["string", "integer"]}, "per_page": {"type": "integer", "default": 20}}},
    },
    "github_repo_info": {"description": "Get repo metadata", "parameters": {"type": "object", "properties": {}}},
}


def handle_mcp(msg: dict) -> dict:
    """Handle MCP request (stdio JSON-RPC style)."""
    method = msg.get("method")
    params = msg.get("params", {})
    msg_id = msg.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "github-mcp", "version": "1.0.0"}}}
    if method == "tools/list":
        tools = [{"name": k, **v} for k, v in TOOLS.items()]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Tool {name} not found"}}
        try:
            fn = globals()[name]
            result = fn(**args)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}}
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32600, "message": f"Unknown method: {method}"}}


def stdio_loop():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_mcp(msg)
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


def http_server(port: int):
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return
            resp = handle_mcp(msg)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())

        def log_message(self, fmt, *args):
            pass

    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, help="Run HTTP server on port")
    args = ap.parse_args()
    if args.http:
        http_server(args.http)
    else:
        stdio_loop()