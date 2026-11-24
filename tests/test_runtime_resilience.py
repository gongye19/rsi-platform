import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import harnesslens.infrastructure.chat_completions_proxy as proxy
from harnesslens.infrastructure.trace_watch import ProviderTraceWatch
from harnesslens.harnesses.opencode_runtime import _start_proxy, _stop_process, _stream_process
from harnesslens.benchmarks.crm_eval import run_process, crm_workers


@pytest.fixture
def upstream(monkeypatch):
    class Model(BaseHTTPRequestHandler):
        counts = {}; active = 0; peak = 0; lock = threading.Lock()
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            case = body.get("case", "ok")
            with self.lock:
                self.counts[case] = self.counts.get(case, 0) + 1
                count = self.counts[case]
                type(self).active += 1
                type(self).peak = max(self.peak, self.active)
            try:
                time.sleep(.05)
                if case == "quota" or (case in {"rate", "transient"} and count == 1):
                    status = 503 if case == "transient" else 429
                    code = {"quota": "insufficient_quota", "rate": "limit_burst_rate", "transient": "server_error"}[case]
                    data = json.dumps({"error": {"code": code}}).encode()
                    content_type = "application/json"
                elif case == "truncated":
                    status, content_type = 200, "text/event-stream"
                    data = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
                elif case == "completed_stream":
                    status, content_type = 200, "text/event-stream"
                    data = b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}],"usage":{"total_tokens":3}}\n\ndata: [DONE]\n\n'
                else:
                    status, content_type = 200, "application/json"
                    data = json.dumps({"choices": [{"message": {"role": "assistant", "content": "OK"}}],
                                       "usage": {"total_tokens": 3}}).encode()
                self.send_response(status); self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data) + (1 if case == "completed_stream" else 0)))
                self.end_headers(); self.wfile.write(data); self.wfile.flush()
                if case == "completed_stream":
                    time.sleep(.7)
                    try: self.wfile.write(b"\n")
                    except OSError: pass
            finally:
                with self.lock: type(self).active -= 1
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-test-only")
    yield Model
    server.shutdown(); server.server_close(); thread.join()


@pytest.fixture
def local_proxy(upstream, monkeypatch, tmp_path):
    monkeypatch.setattr(proxy, "KEY", "local-test-only")
    monkeypatch.setattr(proxy, "LOG_FILE", str(tmp_path / "api_calls.jsonl"))
    monkeypatch.setenv("HAI_PROVIDER_SLOT_DIR", str(tmp_path / "slots"))
    monkeypatch.setenv("HAI_PROVIDER_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("HAI_PROVIDER_RETRY_ATTEMPTS", "3")
    policy = proxy._upstream_retry_policy
    monkeypatch.setattr(proxy, "_upstream_retry_policy", lambda *a: .03 if policy(*a) is not None else None)
    server = proxy.ThreadingHTTPServer(("127.0.0.1", 0), proxy.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    server.shutdown(); server.server_close(); thread.join()


def post(url, case):
    body = json.dumps({"model": "local", "case": case, "messages": [{"role": "user", "content": "test"}]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as response:
        return response.code, response.read()


@pytest.mark.parametrize("case", ["rate", "transient"])
def test_proxy_recovers_temporary_failure_and_keeps_complete_trace(local_proxy, upstream, tmp_path, case):
    assert post(local_proxy, case)[0] == 200
    assert upstream.counts[case] == 2
    rows = [json.loads(line) for line in (tmp_path / "api_calls.jsonl").read_text().splitlines()]
    assert rows[0]["event"] == "upstream_retry"
    assert rows[-1]["upstream_attempt_count"] == 2 and rows[-1]["response"]
    assert ProviderTraceWatch(tmp_path / "api_calls.jsonl").error() == ""


def test_proxy_does_not_repeat_permanent_quota_or_incomplete_stream(local_proxy, upstream, tmp_path):
    assert post(local_proxy, "quota")[0] == 429
    assert upstream.counts["quota"] == 1
    assert post(local_proxy, "truncated")[0] == 200
    assert upstream.counts["truncated"] == 1
    rows = [json.loads(line) for line in (tmp_path / "api_calls.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert rows[-1]["response"] is None and rows[-1]["partial_response"]


def test_sse_done_is_logged_without_waiting_for_tcp_eof(local_proxy, tmp_path):
    started = time.monotonic()
    assert post(local_proxy, "completed_stream")[0] == 200
    assert time.monotonic() - started < .5
    row = json.loads((tmp_path / "api_calls.jsonl").read_text().strip())
    assert row["response"] and row["usage"]["total_tokens"] == 3


def test_crm_monitor_allows_retry_notices(local_proxy, upstream, tmp_path):
    workspace = tmp_path / "workspace"; workspace.mkdir()
    code = "import urllib.request,sys,time;print(urllib.request.urlopen(urllib.request.Request(sys.argv[1],b'{\"case\":\"rate\"}')).read());time.sleep(.5)"
    _, error, status = run_process([sys.executable, "-c", code, local_proxy], cwd=workspace, env=os.environ.copy(), timeout_s=3)
    assert status == 0 and not error and upstream.counts["rate"] == 2


def test_intelligent_monitor_stops_terminal_provider_failure(local_proxy, tmp_path):
    code = "import urllib.request,sys,time;\ntry: urllib.request.urlopen(urllib.request.Request(sys.argv[1],b'{\"case\":\"quota\"}'))\nexcept Exception: pass\ntime.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", code, local_proxy], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    started = time.monotonic()
    _, _, outcome = _stream_process(child, prompt="input", timeout_s=10, api_trace_path=tmp_path / "api_calls.jsonl")
    assert outcome == "provider_error" and time.monotonic() - started < 4
    assert child.poll() is not None


def test_timeout_covers_a_blocked_prompt_pipe(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    started = time.monotonic()
    _, _, outcome = _stream_process(child, prompt="x" * 3_000_000, timeout_s=.2)
    assert outcome == "timeout" and time.monotonic() - started < 4
    assert child.poll() is not None


def test_trace_watch_handles_partial_records_incrementally(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text('{"request":{},"upstream_status":429,')
    watch = ProviderTraceWatch(path)
    assert watch.error() == ""
    with path.open("a") as stream: stream.write('"response":null}\n')
    assert "429" in watch.error()


def test_global_provider_cap_is_shared_by_real_proxy_processes(upstream, monkeypatch, tmp_path):
    monkeypatch.setenv("HAI_PROVIDER_SLOT_DIR", str(tmp_path / "slots"))
    monkeypatch.setenv("HAI_PROVIDER_MAX_CONCURRENCY", "2")
    processes = []
    try:
        urls = []
        for index in range(2):
            directory = tmp_path / str(index); directory.mkdir()
            child, port = _start_proxy(run_root=directory, call_id=str(index)); processes.append(child)
            urls.append(f"http://127.0.0.1:{port}/v1/chat/completions")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda index: post(urls[index % 2], "ok"), range(8)))
        assert all(result[0] == 200 for result in results)
        assert upstream.peak == 2
        assert sum(len((tmp_path / str(index) / "api_calls.jsonl").read_text().splitlines()) for index in range(2)) == 8
    finally:
        for child in processes: _stop_process(child)


def test_crm_concurrency_honors_configured_cap(monkeypatch):
    monkeypatch.setenv("HAI_CRM_MAX_CONCURRENCY", "4")
    assert crm_workers(10, 10) == 4
    assert crm_workers(1, 10) == 1
    assert crm_workers(4, 2) == 2
