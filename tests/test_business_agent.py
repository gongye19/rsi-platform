import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from harnesslens.harnesses.business_agent import AgentError, invoke, load_config, template
from harnesslens.harnesses.channel_preflight import ChannelPreflightError, validate_channel_preflight


def context():
    return {"prompt": "Public task", "instructions": "New candidate instruction", "harness_files": {"project": {"AGENTS.md": "New candidate instruction"}},
            "harness_dir": "/candidate", "workspace": "/task", "harness_digest": "digest", "task": {"query": "Public task"},
            "task_id": "sample", "request_id": "stable-request-id", "trial_id": "trial", "scope": "TRAIN",
            "seed": 42, "model": "business", "steps": 40, "timeout": 10,
            "harness_version": "v-probe", "component_protocol": {"schema": "harnesslens.opencode-components.v1"}}


def config_file(tmp_path, content):
    path = tmp_path / "agent.toml"
    path.write_text(content)
    return path


@pytest.fixture
def python_config(tmp_path):
    code = tmp_path / "business"
    code.mkdir()
    (code / "my_agent.py").write_text('''from dataclasses import dataclass
import os
@dataclass
class Reply:
    result: dict
    metrics: dict
    events: list
async def solve(question, settings, seed):
    print("Business log", os.environ.get("BUSINESS_KEY", ""))
    return Reply({"text": question + settings["project"]["AGENTS.md"]}, {"tokens": seed},
                 [{"role":"user","content":question},{"role":"assistant","content":"response"}])
''')
    return config_file(tmp_path, f'''[agent]
type = "python"
function = "my_agent:solve"
python = "{sys.executable}"
python_paths = ["business"]
answer_path = "result.text"
usage_path = "metrics.tokens"
trace_path = "events"
pass_env = ["BUSINESS_KEY"]
timeout = 3
[agent.arguments]
question = "{{prompt}}"
settings = "{{harness_files}}"
seed = "{{seed}}"
''')


def test_python_async_dataclass_mapping_and_credentials(python_config, tmp_path, monkeypatch):
    monkeypatch.setenv("BUSINESS_KEY", "very-private-business-key")
    config = load_config(python_config)
    result = invoke(config, context(), tmp_path / "work")
    assert result["answer"] == "Public taskNew candidate instruction"
    assert result["usage"]["total_tokens"] == 42
    assert result["messages"][0]["role"] == "user"
    assert result["api_calls"] == []
    for p in (tmp_path / "work").rglob("*"):
        if p.is_file() and p.suffix in {".json", ".log", ".jsonl"}:
            assert "very-private-business-key" not in p.read_text()


def test_python_timeout_retains_failed_status_without_retry(python_config, tmp_path, monkeypatch):
    monkeypatch.setenv("BUSINESS_KEY", "secret-for-this-test")
    (tmp_path / "business/my_agent.py").write_text("import time\ndef solve(**kwargs):\n time.sleep(30)\n")
    config = load_config(python_config)
    config["agent"]["timeout"] = 0.15
    start = time.monotonic()
    with pytest.raises(AgentError, match="timed out"):
        invoke(config, context(), tmp_path / "work")
    assert time.monotonic() - start < 5
    assert json.loads((tmp_path / "work/agent_status.json").read_text())["status"] == "failed"


def test_python_interpreter_keeps_venv_symlink_path(tmp_path):
    path = tmp_path / "venv/bin/python"
    path.parent.mkdir(parents=True)
    path.symlink_to(sys.executable)
    config = load_config(config_file(tmp_path, '[agent]\ntype="python"\nfunction="module:solve"\npython="venv/bin/python"\n'))
    assert config["agent"]["python"] == str(path)


class Handler(BaseHTTPRequestHandler):
    requests = []
    status = 200
    response = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append((body, dict(self.headers)))
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(type(self).response).encode())

    def do_GET(self):
        type(self).requests.append((self.path, dict(self.headers)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(type(self).trace).encode())

    def log_message(self, *_):
        pass


@pytest.fixture
def http_config(tmp_path):
    Handler.requests, Handler.status = [], 200
    Handler.response = {"data": {"answer": "answer", "usage": 123, "messages": [{"role": "assistant", "content": "answer"}]}}
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config_file(tmp_path, f'''[agent]
type="http"
url="http://127.0.0.1:{server.server_address[1]}/solve"
token_env="BUSINESS_TOKEN"
answer_path="data.answer"
usage_path="data.usage"
trace_path="data.messages"
[agent.headers_env]
X-API-Key="BUSINESS_KEY"
[agent.body]
question="{{prompt}}"
request_id="{{request_id}}"
[agent.body.options]
instructions="{{harness_files}}"
''')
    try:
        yield path
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_http_nested_body_mappings_and_secret_headers(http_config, tmp_path, monkeypatch):
    monkeypatch.setenv("BUSINESS_TOKEN", "top-secret-bearer")
    monkeypatch.setenv("BUSINESS_KEY", "top-secret-api-key")
    config = load_config(http_config)
    result = invoke(config, context(), tmp_path / "work")
    body, headers = Handler.requests[0]
    assert body["options"]["instructions"] == context()["harness_files"]
    assert body["request_id"] == "stable-request-id"
    assert headers["Authorization"] == "Bearer top-secret-bearer"
    assert result["answer"] == "answer"
    text = "".join(p.read_text() for p in (tmp_path / "work").glob("*.json*"))
    assert "top-secret" not in text


def test_http_quota_pauses_once_and_records_status(http_config, tmp_path, monkeypatch):
    monkeypatch.setenv("BUSINESS_TOKEN", "secret-token")
    monkeypatch.setenv("BUSINESS_KEY", "secret-api-key")
    Handler.status = 429
    with pytest.raises(AgentError, match="HTTP 429"):
        invoke(load_config(http_config), context(), tmp_path / "work")
    assert len(Handler.requests) == 1
    assert json.loads((tmp_path / "work/agent_status.json").read_text())["http_status"] == 429


@pytest.mark.parametrize("usage", [None, 0, -1, True, "123"])
def test_missing_or_invalid_usage_is_not_zero_filled(http_config, tmp_path, monkeypatch, usage):
    monkeypatch.setenv("BUSINESS_TOKEN", "secret-token")
    monkeypatch.setenv("BUSINESS_KEY", "secret-api-key")
    Handler.response["data"]["usage"] = usage
    with pytest.raises(AgentError, match="usage"):
        invoke(load_config(http_config), context(), tmp_path / "work")


def test_config_validation_rejects_unknown_keys_and_placeholders(tmp_path):
    with pytest.raises(ValueError, match="Unknown agent"):
        load_config(config_file(tmp_path, '[agent]\ntype="python"\nfunction="module:solve"\ntimeuot=1\n'))
    with pytest.raises(ValueError, match="Unknown agent placeholder"):
        load_config(config_file(tmp_path, '[agent]\ntype="python"\nfunction="module:solve"\n[agent.arguments]\ninput="{reference_answer}"\n'))


def test_transport_delivery_does_not_pass_harness_preflight(tmp_path):
    row = tmp_path / "trial.jsonl"
    row.write_text(json.dumps({"agent_transport": "http", "model_request_evidence": False,
        "model_context": {"schema": "harnesslens.channel-load-report.v1", "harness": "opencode"}}))
    with pytest.raises(ChannelPreflightError):
        validate_channel_preflight(decision={"candidate": {"channel_diffs": [{"channel_id": "instructions_rules"}]}},
            rollout={"per_task": {"sample": {"trajectory_paths": [str(row)]}}}, output_path=tmp_path / "report.json")
    report = json.loads((tmp_path / "report.json").read_text())
    assert any(item["channel_id"] == "business_agent_evidence" and not item["passed"] for item in report["checks"])


def test_string_only_python_function_can_explicitly_use_wall_time(python_config, tmp_path, monkeypatch):
    monkeypatch.setenv("BUSINESS_KEY", "private-example-key")
    (tmp_path / "business/my_agent.py").write_text("def solve(**kwargs):\n return 'plain answer'\n")
    config = load_config(python_config)
    config["agent"].update(answer_path="", cost_metric="wall_seconds", require_trace=False)
    result = invoke(config, context(), tmp_path / "work")
    assert result["answer"] == "plain answer"
    assert result["usage"]["total_tokens"] is None
    assert result["usage"]["wall_seconds"] > 0
    assert result["api_calls"] == []


def test_existing_opencode_trace_format_preserves_real_tool_results():
    from harnesslens.harnesses.business_agent import normalize_messages
    messages = normalize_messages([{"info": {"role": "assistant"}, "parts": [
        {"type": "text", "text": "checking"}, {"type": "tool", "tool": "bash", "callID": "call-1",
          "state": {"status": "completed", "input": {"command": "query"}, "output": "rows"}}]}], "opencode")
    assert messages[0]["tool_calls"][0]["name"] == "bash"
    assert messages[1] == {"role": "tool", "tool_call_id": "call-1", "content": "rows"}


@pytest.mark.parametrize("mismatch", [None, "request_id", "session_id", "harness_digest", "harness_version", "opencode_version", "component_protocol"])
def test_answer_only_http_collects_separate_trace_and_rejects_wrong_identity(http_config, tmp_path, monkeypatch, mismatch):
    monkeypatch.setenv("BUSINESS_TOKEN", "trace-and-business-secret")
    monkeypatch.setenv("BUSINESS_KEY", "api-key-secret")
    config = load_config(http_config)
    Handler.response = {"data": {"answer": "answer"}, "session": "ses-probe"}
    Handler.trace = {"request_id": "stable-request-id", "session_id": "ses-probe", "harness_digest": "digest",
        "harness_version": "v-probe", "opencode_version": "1.18.32", "component_protocol": "harnesslens.opencode-components.v1",
        "messages": [{"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "answer"}]}],
        "usage": {"total_tokens": 12}, "api_calls": [{"request": {"messages": [{"role": "user", "content": "task"}]},
            "response": {"choices": [{"message": {"role": "assistant", "content": "answer"}}]}, "upstream_status": 200}]}
    if mismatch:
        Handler.trace[mismatch] = "wrong"
    # Exercise the real configuration parser, URL mapping and authenticated GET.
    with http_config.open("a") as out:
        out.write(f'\n[trace]\nurl="{config["agent"]["url"].removesuffix("/solve")}/traces/{{session_id}}"\n'
                  'session_id_path="session"\ntoken_env="BUSINESS_TOKEN"\n')
    config = load_config(http_config)
    if mismatch:
        with pytest.raises(AgentError, match="mismatch|different"):
            invoke(config, context(), tmp_path / "work")
        assert json.loads((tmp_path / "work/agent_status.json").read_text())["status"] == "failed"
    else:
        result = invoke(config, context(), tmp_path / "work")
        assert result["usage"]["total_tokens"] == 12
        assert result["messages"][0]["content"] == "answer"
        assert result["api_calls"][0]["request"]["messages"]
        assert Handler.requests[-1][0] == "/traces/ses-probe"
        assert Handler.requests[-1][1]["Authorization"] == "Bearer trace-and-business-secret"
        assert (tmp_path / "work/collected_trace.json").is_file()
        assert "trace-and-business-secret" not in "".join(p.read_text() for p in (tmp_path / "work").glob("*.json*"))


def test_python_answer_only_uses_same_separate_trace_collector(python_config, http_config, tmp_path, monkeypatch):
    monkeypatch.setenv("BUSINESS_KEY", "business-secret")
    (tmp_path / "business/my_agent.py").write_text("def solve(**kwargs):\n return {'answer':'python-answer'}\n")
    base = load_config(http_config)["agent"]["url"].removesuffix("/solve")
    Handler.trace = {"request_id": "stable-request-id", "session_id": "python-session", "harness_digest": "digest",
        "harness_version": "v-probe", "opencode_version": "1.18.32", "component_protocol": "harnesslens.opencode-components.v1",
        "messages": [{"role": "assistant", "content": "python-answer"}], "usage": {"total_tokens": 5},
        "api_calls": [{"request": {"messages": []}, "response": {"choices": []}}]}
    # Both fixtures use agent.toml, so write an independent Python config explicitly.
    path = tmp_path / "python-traced.toml"
    path.write_text(f'[agent]\ntype="python"\nfunction="my_agent:solve"\npython="{sys.executable}"\npython_paths=["business"]\n'
        f'[trace]\nurl="{base}/requests/{{request_id}}"\ntrace_format="messages"\n')
    result = invoke(load_config(path), context(), tmp_path / "python-work")
    assert result["answer"] == "python-answer"
    assert result["usage"]["total_tokens"] == 5
    assert Handler.requests[-1][0] == "/requests/stable-request-id"
