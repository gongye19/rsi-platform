import base64
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from harnesslens.core.config import load_repo_env, resolve_opencode_binary, opencode_version
from harnesslens.core.budget import CreationBudget
from harnesslens.harnesses.native_harness_driver import stop_process
from harnesslens.harnesses.opencode_runtime import OpenCodeIntelligentAdapter, _start_proxy, _stop_process

ROOT = Path(__file__).resolve().parents[1]


def _fake_binary(path, version):
    path.write_text(f"#!/bin/sh\necho {version}\n")
    path.chmod(0o755)
    return path


def test_explicit_runtime_pin_precedes_path(tmp_path, monkeypatch):
    pinned = _fake_binary(tmp_path / "pinned", "1.18.32")
    other = _fake_binary(tmp_path / "other", "2.0.0")
    monkeypatch.setenv("HAI_OPENCODE_BIN", str(pinned))
    monkeypatch.setenv("HAI_OPENCODE_VERSION", "1.18.32")
    monkeypatch.setattr("shutil.which", lambda _: str(other))
    assert resolve_opencode_binary() == pinned


def test_wrong_runtime_version_fails_before_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("HAI_OPENCODE_BIN", str(_fake_binary(tmp_path / "old", "1.14.18")))
    monkeypatch.setenv("HAI_OPENCODE_VERSION", "1.18.32")
    with pytest.raises(RuntimeError, match="version mismatch"):
        resolve_opencode_binary()


def test_checkout_runtime_is_automatically_pinned(tmp_path, monkeypatch):
    binary = tmp_path / "runtime/opencode-1.18.32/bin/opencode"
    binary.parent.mkdir(parents=True)
    _fake_binary(binary, "1.18.32")
    monkeypatch.delenv("HAI_OPENCODE_BIN", raising=False)
    monkeypatch.delenv("HAI_OPENCODE_VERSION", raising=False)
    monkeypatch.setenv("HARNESSLENS_ROOT", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda _: "/other/opencode")
    assert resolve_opencode_binary() == binary


def test_missing_explicit_runtime_cannot_fall_back(tmp_path, monkeypatch):
    monkeypatch.setenv("HAI_OPENCODE_BIN", str(tmp_path / "missing"))
    monkeypatch.setattr("shutil.which", lambda _: "/some/other/opencode")
    with pytest.raises(RuntimeError, match="unavailable"):
        resolve_opencode_binary()


class _Model(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        def chunk(delta, finish=None, usage=None):
            value = {"id": "local-runtime-probe", "object": "chat.completion.chunk", "created": 0,
                "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            if usage:
                value["usage"] = usage
            return "data: " + json.dumps(value) + "\n\n"
        raw = (chunk({"role": "assistant", "content": "OK"}) + chunk({}, "stop",
            {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *_):
        pass


@pytest.mark.skipif(os.environ.get("HAI_RUN_OPENCODE_HTTP_PROBE") != "1", reason="opt in to local native editor runtime probe")
def test_11832_sandboxed_editor_cli_and_usage(monkeypatch):
    load_repo_env(ROOT)
    # Standalone CLI use must derive a bounded runtime root without relying
    # on the service wrapper's environment settings.
    monkeypatch.delenv("HAI_CRM_RUNTIME_ROOT", raising=False)
    root = ROOT / "runs/opencode-1.18.32-editor"
    root.mkdir(parents=True, exist_ok=True)
    model = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-probe-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{model.server_address[1]}/v4")
    try:
        budget = CreationBudget(root / "budget.json", total=200, baseline_used=0)
        call_id = budget.next_attempt_id("editor-probe")
        workspace = root / call_id
        adapter = OpenCodeIntelligentAdapter(model="probe/probe", context_limit=32000,
            output_limit=1024, max_steps=4, timeout_s=30, workspace_root=root)
        result = adapter.run(prompt="editor-trace-sentinel: Reply OK.", workspace=workspace,
            working_directory=workspace, call_id=call_id, budget=budget)
        assert result.outcome == "completed", result
        assert result.returncode == 0
        assert result.usage["total"] == 11
        assert '"text":"OK"' in Path(result.stdout_path).read_text()
        calls = [json.loads(line) for line in Path(result.api_trace_path).read_text().splitlines() if line.strip()]
        assert any("editor-trace-sentinel" in json.dumps(call.get("request", {})) for call in calls)
    finally:
        model.shutdown()
        model.server_close()


@pytest.mark.skipif(os.environ.get("HAI_RUN_OPENCODE_HTTP_PROBE") != "1", reason="opt in to local native HTTP runtime probe")
def test_11832_serve_events_messages_and_model_trace(monkeypatch):
    load_repo_env(ROOT)
    binary = resolve_opencode_binary()
    assert opencode_version(binary) == "1.18.32"
    root = ROOT / "runs/opencode-1.18.32-http"
    root.mkdir(parents=True, exist_ok=True)
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    model = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-probe-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{model.server_address[1]}/v4")
    proxy, port = _start_proxy(run_root=root, call_id="serve-trace-probe")
    config = {"autoupdate": False, "share": "disabled", "model": "probe/probe", "small_model": "probe/probe",
        "enabled_providers": ["probe"], "permission": "allow", "agent": {"build": {"steps": 4}},
        "provider": {"probe": {"npm": "@ai-sdk/openai-compatible", "name": "Local probe",
            "options": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "local-probe-only"},
            "models": {"probe": {"name": "Probe", "limit": {"context": 32000, "output": 1024}}}}}}
    env = {"PATH": os.environ["PATH"], "HOME": str(workspace / "home"), "NO_COLOR": "1",
        "XDG_CONFIG_HOME": str(workspace / "config"), "XDG_DATA_HOME": str(workspace / "data"),
        "XDG_STATE_HOME": str(workspace / "state"), "XDG_CACHE_HOME": str(workspace / "cache"),
        "OPENCODE_CONFIG_CONTENT": json.dumps(config), "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1", "OPENCODE_SERVER_PASSWORD": "local-runtime-probe",
        "OPENCODE_SERVER_USERNAME": "opencode"}
    process = None
    events, errors = [], []
    connected, done = threading.Event(), threading.Event()
    listener = None
    auth = base64.b64encode(b"opencode:local-runtime-probe").decode()
    headers = {"Authorization": "Basic " + auth, "x-opencode-directory": str(workspace)}
    try:
        with (root / "server.log").open("w") as out:
            process = subprocess.Popen([str(binary), "serve", "--pure", "--hostname", "127.0.0.1", "--port", "0"],
                cwd=workspace, env=env, stdout=out, stderr=out, start_new_session=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            match = re.search(r"http://127.0.0.1:(\d+)", (root / "server.log").read_text())
            if match:
                break
            assert process.poll() is None, (root / "server.log").read_text()
            time.sleep(0.1)
        assert match, "OpenCode serve startup timeout"
        url = "http://127.0.0.1:" + match[1]
        with httpx.Client(base_url=url, headers=headers, timeout=10) as client:
            health = client.get("/global/health")
            health.raise_for_status()
            assert health.json()["version"] == "1.18.32"
            session = client.post("/session", json={"title": "serve-trace-probe"})
            session.raise_for_status()
            sid = session.json()["id"]
            def read_events():
                try:
                    with httpx.stream("GET", url + "/event", headers=headers, timeout=15) as stream:
                        stream.raise_for_status()
                        connected.set()
                        for line in stream.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            event = json.loads(line[5:])
                            events.append(event)
                            props = event.get("properties", {})
                            if props.get("sessionID") == sid and event["type"] == "session.status" and props.get("status", {}).get("type") == "idle":
                                done.set()
                                return
                except Exception as exc:
                    errors.append(type(exc).__name__ + ": " + str(exc))
                    connected.set()
            listener = threading.Thread(target=read_events, daemon=True)
            listener.start()
            assert connected.wait(10) and not errors
            response = client.post(f"/session/{sid}/prompt_async", json={"agent": "build",
                "model": {"providerID": "probe", "modelID": "probe"},
                "parts": [{"type": "text", "text": "serve-trace-sentinel: Reply OK."}]})
            response.raise_for_status()
            assert done.wait(25), errors
            messages = client.get(f"/session/{sid}/message")
            messages.raise_for_status()
            exported = messages.json()
            assert any(p.get("text") == "OK" for m in exported for p in m.get("parts", []))
            assert any(m.get("info", {}).get("role") == "assistant" for m in exported)
        _stop_process(proxy)
        proxy = None
        calls = [json.loads(line) for line in (root / "api_calls.jsonl").read_text().splitlines() if line.strip()]
        assert any("serve-trace-sentinel" in json.dumps(call.get("request", {})) for call in calls)
        (root / "messages.json").write_text(json.dumps(exported, indent=2))
        (root / "native-events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (root / "result.json").write_text(json.dumps({"version": "1.18.32", "synthetic_provider": True,
            "event_count": len(events), "message_count": len(exported), "model_call_count": len(calls), "verified": True}, indent=2))
    finally:
        stop_process(process)
        _stop_process(proxy)
        if listener:
            listener.join(timeout=3)
        model.shutdown()
        model.server_close()
