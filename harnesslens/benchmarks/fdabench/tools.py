# Adapted from the earlier RSI Platform FDABench integration; standalone implementation.
"""Task-scoped local tools; private references are never loaded by this service."""

from __future__ import annotations
import json
import os
import secrets
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .data import schema, sql_query, search, read_document


def parse_mcp(raw):
    text = raw.decode()
    if text.lstrip().startswith("{"):
        value = json.loads(text)
    else:
        messages = [
            json.loads(line[5:].strip())
            for line in text.splitlines()
            if line.startswith("data:")
        ]
        value = next(x for x in reversed(messages) if "result" in x or "error" in x)
    if "error" in value:
        raise RuntimeError("Web-search MCP returned a protocol error")
    result = value["result"]
    if result.get("isError"):
        raise RuntimeError(
            "Web-search MCP returned a tool error: " + str(result.get("content"))[:400]
        )
    return result


def web_search(query):
    # This server binds auth to an initialized MCP session. Calling tools/list
    # without initialize can succeed while tools/call fails with a misleading 401.
    url = "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp"
    headers = {
        "Authorization": "Bearer " + os.environ["ZHIPU_API_KEY"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    deadline = time.monotonic() + 80
    def rpc(method, params, *, notification=False):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            body["id"] = uuid.uuid4().hex
        request = urllib.request.Request(url, json.dumps(body).encode(), headers)
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError('Web search deadline exceeded')
        with urllib.request.urlopen(request, timeout=min(30, remaining)) as response:
            session = response.headers.get("Mcp-Session-Id")
            if session:
                headers["Mcp-Session-Id"] = session
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Search result too large")
        return {} if notification else parse_mcp(raw)

    rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "rsi-platform-fdabench", "version": "1.0"},
        },
    )
    if "Mcp-Session-Id" not in headers:
        raise RuntimeError("Search MCP did not create an authenticated session")
    rpc("notifications/initialized", {}, notification=True)
    result = rpc(
        "tools/call",
        {
            "name": "web_search_prime",
            "arguments": {
                "search_query": query[:200],
                "location": "us",
                "content_size": "medium",
            },
        },
    )
    # The provider sometimes wraps its JSON array in multiple JSON strings.
    # Decode for the solver without dropping source URLs or source text.
    for block in result.get("content", []):
        if block.get("type") == "text":
            value = block.get("text", "")
            for _ in range(4):
                if not isinstance(value, str):
                    break
                try:
                    value = json.loads(value)
                except ValueError:
                    break
            if isinstance(value, list):
                return {"results": value, "provider": "zhipu_web_search_prime"}
    return result


class ToolService:
    def __init__(self, root, task_map, index, output):
        self.root, self.tasks, self.index, self.output = (
            Path(root),
            task_map,
            index,
            Path(output),
        )
        self.output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.web_counts = {}
        self.by_token = {}
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                binding = service.by_token.get(token)
                if self.path != "/tools" or binding is None:
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    self.send_error(400)
                    return
                if not 0 < length <= 100_000:
                    self.send_error(413)
                    return
                try:
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("Expected object")
                except (ValueError, UnicodeError):
                    self.send_error(400)
                    return
                task, trial = binding
                body["trial_id"] = (
                    trial  # Server binding, never a solver-supplied quota identity.
                )
                start = time.monotonic()
                try:
                    value = service.call(task, body)
                    result = {"status": "success", **value}
                except Exception as exc:
                    result = {
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                event = {
                    "task_id": task,
                    "trial_id": str(body.get("trial_id", "unknown"))[:128],
                    "tool": body.get("tool"),
                    "input": body,
                    "result": result,
                    "seconds": round(time.monotonic() - start, 3),
                }
                with (
                    service.lock,
                    (service.output / "tool-events.jsonl").open("a") as stream,
                ):
                    stream.write(
                        json.dumps(event, ensure_ascii=False, default=repr) + "\n"
                    )
                data = json.dumps(result, ensure_ascii=False, default=repr).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

        class Server(ThreadingHTTPServer):
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/tools"

    def register(self, task, trial):
        if task not in self.tasks:
            raise ValueError("Unknown task")
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.by_token[token] = (task, str(trial) + "#" + secrets.token_hex(8))
        return token

    def revoke(self, token):
        with self.lock:
            self.by_token.pop(token, None)

    def call(self, task, body):
        db = self.root / "databases" / (self.tasks[task]["db"] + ".sqlite")
        tool, value = body["tool"], body.get("value", "")
        if tool == "schema":
            return schema(db)
        if tool == "sql":
            return sql_query(db, value, body.get("limit", 200))
        if tool == "document_search":
            return search(self.index, value, min(body.get("limit", 5), 20))
        if tool == "document_read":
            return read_document(self.index, value, body.get("page", 1))
        if tool == "web_search":
            key = (task, body.get("trial_id", "unknown"))
            with self.lock:
                count = self.web_counts.get(key, 0)
                if count >= 15:
                    raise ValueError("Web-search budget reached (15 calls/trial)")
                self.web_counts[key] = count + 1
            return {"query": value, **web_search(value)}
        raise ValueError("Unknown tool")

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
