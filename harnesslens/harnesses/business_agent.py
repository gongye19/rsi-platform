"""Configurable Python/HTTP execution of an existing business agent.

The optimizer sends public inputs and a candidate harness. Response mappings
read the agent's existing fields. Transport receipts are never represented as
evidence of a model request or of internal skill loading.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, quote
from harnesslens.harnesses.opencode_components import EDITABLE_IDS, component_id, OPENCODE_VERSION, PROTOCOL

from harnesslens.core.artifacts import write_json
from harnesslens.infrastructure.process_isolation import seatbelt_command, bubblewrap_command
from harnesslens.harnesses.native_harness_driver import stop_process, stable_hash

CONFIG_ENV = "HAI_AGENT_CONFIG"
CHANNELS = EDITABLE_IDS
_MISSING = object()


class AgentError(RuntimeError):
    def __init__(self, message, status=None):
        self.status = status
        super().__init__(message)


def select_config(path):
    if path is not None:
        os.environ[CONFIG_ENV] = str(Path(path).expanduser().resolve())


def field(value, path, default=_MISSING):
    if path in ("", "."):
        return value
    try:
        for key in path.split("."):
            value = value[int(key)] if isinstance(value, list) else value[key]
        return value
    except (KeyError, IndexError, TypeError, ValueError):
        if default is _MISSING:
            raise AgentError(f"Agent response is missing mapped field {path!r}") from None
        return default


def template(value, context):
    if isinstance(value, dict):
        return {k: template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [template(v, context) for v in value]
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"\{([a-z_]+)\}", value)
    if match:
        if match[1] not in context:
            raise ValueError(f"Unknown agent placeholder: {match[1]}")
        return copy.deepcopy(context[match[1]])
    def replace(match):
        name = match[1]
        if name not in context:
            raise ValueError(f"Unknown agent placeholder: {name}")
        item = context[name]
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
    return re.sub(r"\{([a-z_]+)\}", replace, value)


def load_config(path=None):
    raw_path = path or os.environ.get(CONFIG_ENV)
    if not raw_path:
        return None
    target = Path(raw_path).expanduser().resolve()
    raw = tomllib.loads(target.read_text())
    if set(raw) - {"agent", "capabilities", "trace"}:
        raise ValueError("Agent TOML supports only [agent], [capabilities], and [trace]")
    given = raw.get("agent", {})
    allowed = {"type", "name", "revision", "python", "python_paths", "function", "arguments", "pass_env",
               "read_roots", "timeout", "sandbox", "url", "body", "headers", "headers_env", "token_env",
               "answer_path", "usage_path", "trace_path", "trace_format", "api_calls_path", "require_trace", "cost_metric", "require_harness_receipt", "runtime_report_path", "harness_receipt_path"}
    if set(given) - allowed:
        raise ValueError(f"Unknown agent settings: {sorted(set(given) - allowed)}")
    agent = {"type": "python", "name": "business-agent", "revision": "", "python": sys.executable,
             "python_paths": [], "function": "", "arguments": {}, "pass_env": [], "read_roots": [],
             "timeout": 600, "sandbox": "auto", "url": "", "body": {}, "headers": {}, "headers_env": {},
             "token_env": "", "answer_path": "answer", "usage_path": "usage.total_tokens", "trace_path": "messages",
             "api_calls_path": "", "require_trace": True, "trace_format": "messages", "cost_metric": "tokens",
             "require_harness_receipt": False, "runtime_report_path": "", "harness_receipt_path": "harness_receipt", **given}
    if agent["type"] not in {"python", "http"}:
        raise ValueError("agent.type must be python or http")
    for name in ("name", "revision", "python", "function", "url", "token_env", "answer_path", "usage_path", "trace_path", "api_calls_path", "runtime_report_path", "harness_receipt_path"):
        if not isinstance(agent[name], str):
            raise ValueError(f"agent.{name} must be a string")
    if type(agent["timeout"]) not in {int, float} or not math.isfinite(agent["timeout"]) or agent["timeout"] <= 0:
        raise ValueError("agent.timeout must be positive")
    if agent["sandbox"] not in {"auto", "none"} or type(agent["require_trace"]) is not bool:
        raise ValueError("Invalid agent sandbox/trace settings")
    if agent["cost_metric"] not in {"tokens", "wall_seconds"} or agent["trace_format"] not in {"messages", "opencode"}:
        raise ValueError("Unsupported cost_metric or trace_format")
    for name in ("arguments", "body", "headers", "headers_env"):
        if not isinstance(agent[name], dict):
            raise ValueError(f"agent.{name} must be a table")
    for name in ("python_paths", "read_roots", "pass_env"):
        if not isinstance(agent[name], list) or any(not isinstance(v, str) for v in agent[name]):
            raise ValueError(f"agent.{name} must be an array of strings")
    for name in ("python_paths", "read_roots"):
        agent[name] = [str((target.parent / Path(p).expanduser()).resolve()) for p in agent[name]]
    python = Path(agent["python"]).expanduser()
    agent["python"] = str((target.parent / python).absolute()) if "/" in str(python) else shutil.which(str(python)) or str(python)
    if agent["type"] == "python" and not re.fullmatch(r"[\w.]+:[\w.]+", agent["function"]):
        raise ValueError("Python agent requires function='module:function'")
    if agent["type"] == "http":
        url = urlsplit(agent["url"])
        if url.username or url.password or not url.netloc or url.fragment or url.query:
            raise ValueError("Use an HTTP URL without embedded credentials, query, or fragment")
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("Remote business-agent URLs require HTTPS")
    if any(re.search(r"authorization|api.key|token|secret|cookie", k, re.I) for k in agent["headers"]):
        raise ValueError("Sensitive HTTP headers belong in agent.headers_env or token_env")
    if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) for v in agent["headers_env"].values()):
        raise ValueError("headers_env maps headers to environment variable names")
    capabilities = raw.get("capabilities", {})
    if set(capabilities) - {"channels"}:
        raise ValueError("Unknown capability settings")
    channels = capabilities.get("channels", ["instructions_rules"])
    if channels == ["*"]:
        channels = sorted(CHANNELS)
    if not isinstance(channels, list) or any(not isinstance(v, str) for v in channels) or {component_id(v) for v in channels} - CHANNELS:
        raise ValueError("Unsupported business harness channels")
    channels = sorted({component_id(v) for v in channels})
    if type(agent["require_harness_receipt"]) is not bool:
        raise ValueError("require_harness_receipt must be boolean")
    # All templates are checked before a process or HTTP request can be launched.
    names = {n: None for n in ("prompt", "instructions", "harness_files", "harness_dir", "harness_digest", "tool_patches", "component_policy", "workspace",
                               "task", "task_id", "request_id", "trial_id", "seed", "scope", "model", "steps", "timeout", "harness_version", "component_protocol")}
    template(agent["arguments"], names)
    template(agent["body"], names)
    trace = raw.get("trace", {})
    if trace:
        defaults = {"url": "", "session_id_path": "", "headers_env": {}, "token_env": "",
                    "messages_path": "messages", "api_calls_path": "api_calls", "usage_path": "usage.total_tokens",
                    "trace_format": "opencode", "runtime_report_path": "runtime_report"}
        if set(trace) - set(defaults):
            raise ValueError("Unknown trace settings")
        trace = {**defaults, **trace}
        if any(not isinstance(v, str) for k, v in trace.items() if k != "headers_env"):
            raise ValueError("Trace settings must be strings")
        url = urlsplit(trace["url"])
        if url.username or url.password or not url.netloc or url.fragment or url.query or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"})):
            raise ValueError("Trace URL must use HTTPS or local HTTP without credentials/query")
        if "{" in url.netloc or "}" in url.netloc:
            raise ValueError("Trace placeholders belong in the URL path")
        template(trace["url"], {"request_id": "id", "session_id": "id", "harness_version": "version"})
        if "{session_id}" in trace["url"] and not trace["session_id_path"]:
            raise ValueError("Session trace URL requires session_id_path")
        if not isinstance(trace["headers_env"], dict) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) for v in trace["headers_env"].values()):
            raise ValueError("trace.headers_env maps headers to environment variable names")
        if trace["trace_format"] not in {"messages", "opencode"}:
            raise ValueError("Unsupported trace format")
    if set(channels) - {"instructions_rules"}:
        mapping = json.dumps(agent["arguments"] if agent["type"] == "python" else agent["body"])
        if not any(p in mapping for p in ("{harness_files}", "{harness_dir}")):
            raise ValueError("Native channels require harness_files or harness_dir delivery")
        if not agent["require_harness_receipt"] and not trace:
            raise ValueError("Native channels require a verified harness receipt or separate trace endpoint")
    return {"agent": agent, "capabilities": {"channels": channels}, "trace": trace, "config_file": str(target)}


def fingerprint(config):
    agent = config["agent"]
    files = {}
    if agent["type"] == "python":
        for root in agent["python_paths"]:
            for directory, names, filenames in os.walk(root):
                names[:] = [name for name in names if name not in {".git", ".venv", "venv", "node_modules", "__pycache__"}]
                for name in filenames:
                    if name.endswith(".py"):
                        p = Path(directory) / name
                        files[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
                        if len(files) > 10000:
                            raise ValueError("python_paths is too broad; select the business package directory")
    from .component_policy import policy_contract
    return {"agent": agent, "capabilities": config["capabilities"], "component_policy": policy_contract(config), "trace": config.get("trace", {}), "python_sources": files,
            "adapter_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in ("business_agent.py", "business_worker.py")}}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _python(config, arguments, workspace, env, context):
    agent = config["agent"]
    runtime = workspace / ".agent-runtime"
    runtime.mkdir(exist_ok=True)
    worker = runtime / "worker.py"
    shutil.copyfile(Path(__file__).with_name("business_worker.py"), worker)
    request, response = runtime / "call.json", runtime / "response.json"
    write_json(request, {"function": agent["function"], "python_paths": agent["python_paths"],
                         "arguments": arguments, "response_file": str(response)})
    command = [agent["python"], str(worker), str(request)]
    if agent["sandbox"] == "auto":
        probe = subprocess.run([agent["python"], "-c", "import sys,json;print(json.dumps([sys.prefix,sys.base_prefix]))"],
                               text=True, capture_output=True, timeout=10, check=True)
        roots = [*json.loads(probe.stdout), *agent["python_paths"], *agent["read_roots"]]
        command = bubblewrap_command(command, writable_root=workspace, working_directory=workspace, read_only_roots=roots)
        if sys.platform == "darwin":
            policy = command[2]
            for name in ("source", "harness"):
                policy += f'\n(deny file-write* (subpath {json.dumps(str(workspace / name))}))'
            for root in context.get("_private_roots", []):
                policy += f'\n(deny file-read* file-write* (subpath {json.dumps(str(root))}))'
            for port in context.get("_private_ports", []):
                policy += f'\n(deny network-outbound (remote tcp "localhost:{int(port)}"))'
            command[2] = policy
        else:
            if context.get("_private_ports"):
                raise AgentError("Linux Python CRM calls need a network-isolated tool gateway; use the HTTP adapter. Host-network bubblewrap cannot block the PostgreSQL admin port.")
            index = command.index("--")
            for name in ("source", "harness"):
                path = workspace / name
                if path.exists():
                    command[index:index] = ["--ro-bind", str(path), str(path)]
            for private in context.get("_private_roots", []):
                path = Path(private).resolve()
                if path.is_dir():
                    command[index:index] = ["--tmpfs", str(path)]
    process = None
    with (runtime / "stdout.log").open("w") as out, (runtime / "stderr.log").open("w") as err:
        try:
            process = subprocess.Popen(command, cwd=workspace, env=env, stdout=out, stderr=err, start_new_session=True)
            process.wait(timeout=agent["timeout"])
        except subprocess.TimeoutExpired:
            raise AgentError("Python business agent timed out") from None
        finally:
            stop_process(process)
        if process.returncode != 0:
            raise AgentError("Python business agent failed; inspect its retained stderr.log")
    if not response.is_file() or response.stat().st_size > 32_000_000:
        raise AgentError("Python agent did not produce a bounded JSON response")
    return json.loads(response.read_text())


def normalize_messages(messages, format):
    if not isinstance(messages, list):
        raise AgentError("Mapped trace must be a list of conversation messages")
    if format == "opencode":
        output = []
        for entry in messages:
            info, parts = entry.get("info", {}), entry.get("parts", [])
            role = info.get("role")
            if role not in {"user", "assistant"}:
                raise AgentError("OpenCode traces require info.role and parts")
            content = "\n".join(str(p.get("text", "")) for p in parts if p.get("type") == "text")
            calls, results = [], []
            for part in parts:
                state = part.get("state", {})
                if part.get("type") != "tool" or state.get("status") not in {"completed", "error"}:
                    continue
                calls.append({"id": part.get("callID"), "name": part.get("tool"), "arguments": state.get("input", {})})
                results.append({"role": "tool", "tool_call_id": part.get("callID"),
                                "content": state.get("output", state.get("error", ""))})
            output.append({"role": role, "content": content, **({"tool_calls": calls} if calls else {})})
            output.extend(results)
        return output
    if any(not isinstance(m, dict) or m.get("role") not in {"system", "developer", "user", "assistant", "tool"} for m in messages):
        raise AgentError("Mapped trace must be a list of conversation messages")
    output = copy.deepcopy(messages)
    for message in output:
        for call in message.get("tool_calls", []):
            if "function" in call:
                function = call.pop("function")
                call.update(name=function.get("name"), arguments=function.get("arguments"))
    return output


def _verify_harness_receipt(receipt, context):
    if not isinstance(receipt, dict):
        raise AgentError("Business agent did not provide a harness loading receipt")
    expected = {"request_id": context["request_id"], "harness_digest": context["harness_digest"],
                "harness_version": context.get("harness_version"), "opencode_version": OPENCODE_VERSION,
                "component_protocol": PROTOCOL}
    for key, value in expected.items():
        if value is None or receipt.get(key) != value:
            raise AgentError(f"Business harness receipt mismatch: {key}")
    if not isinstance(receipt.get("session_id"), str) or not receipt["session_id"]:
        raise AgentError("Business harness receipt is missing its OpenCode session_id")


def _collect_trace(config, result, context, timeout):
    settings = config["trace"]
    values = {"request_id": context["request_id"], "harness_version": context.get("harness_version", ""),
              "session_id": field(result, settings["session_id_path"], "") if settings["session_id_path"] else ""}
    if settings["session_id_path"] and (not isinstance(values["session_id"], str) or not values["session_id"]):
        raise AgentError("Business response is missing its mapped session_id")
    url = template(settings["url"], {key: quote(str(value), safe="") for key, value in values.items()})
    headers = {name: os.environ[var] for name, var in settings["headers_env"].items()}
    if settings["token_env"]:
        headers["Authorization"] = "Bearer " + os.environ[settings["token_env"]]
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.build_opener(_NoRedirect).open(request, timeout=max(0.01, timeout)) as response:
        raw = response.read(32_000_001)
    if len(raw) > 32_000_000:
        raise AgentError("Business trace response exceeds 32 MB")
    data = json.loads(raw)
    _verify_harness_receipt(data, context)
    if values["session_id"] and data["session_id"] != values["session_id"]:
        raise AgentError("Business trace belongs to a different OpenCode session")
    return data


def invoke(config, context, workspace):
    """One execution; no implicit retries. Returns mapped results and receipts."""
    agent = config["agent"]
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    trace_settings = config.get("trace", {})
    secret_names = [*agent["pass_env"], *agent["headers_env"].values(), *([agent["token_env"]] if agent["token_env"] else []),
                    *trace_settings.get("headers_env", {}).values(), *([trace_settings["token_env"]] if trace_settings.get("token_env") else [])]
    if any(name not in os.environ for name in secret_names):
        raise AgentError("Business-agent credential environment variable is missing")
    secrets = [os.environ[name] for name in secret_names]
    outgoing = template(agent["arguments"] if agent["type"] == "python" else agent["body"], context)
    receipt = {"kind": agent["type"], "request_id": context["request_id"], "request": outgoing}
    write_json(workspace / "agent_request.json", _redact(receipt, secrets))
    started = time.monotonic()
    try:
        if agent["type"] == "python":
            env = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TZ", *agent["pass_env"]) if name in os.environ}
            for sub in ("home", "tmp", "cache"):
                (workspace / ".agent-runtime" / sub).mkdir(parents=True, exist_ok=True)
            env.update(HOME=str(workspace / ".agent-runtime/home"), TMPDIR=str(workspace / ".agent-runtime/tmp"),
                       XDG_CACHE_HOME=str(workspace / ".agent-runtime/cache"), PYTHONDONTWRITEBYTECODE="1")
            result = _python(config, outgoing, workspace, env, context)
            status = 200
        else:
            headers = {"Content-Type": "application/json", **agent["headers"],
                       **{name: os.environ[var] for name, var in agent["headers_env"].items()}}
            if agent["token_env"]:
                headers["Authorization"] = "Bearer " + os.environ[agent["token_env"]]
            request = urllib.request.Request(agent["url"], json.dumps(outgoing).encode(), headers, method="POST")
            try:
                with urllib.request.build_opener(_NoRedirect).open(request, timeout=agent["timeout"]) as response:
                    raw, status = response.read(32_000_001), response.status
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                raise AgentError(f"Business HTTP agent returned HTTP {code}; execution paused", code) from None
            if len(raw) > 32_000_000:
                raise AgentError("Business HTTP response exceeds 32 MB")
            result = json.loads(raw)
        write_json(workspace / "agent_response.json", _redact(result, secrets))
        answer = field(result, agent["answer_path"])
        usage = field(result, agent["usage_path"], None)
        messages = field(result, agent["trace_path"], []) if agent["trace_path"] else []
        api_calls = field(result, agent["api_calls_path"], []) if agent["api_calls_path"] else []
        runtime_report = field(result, agent["runtime_report_path"], None) if agent["runtime_report_path"] else None
        collected = None
        if trace_settings:
            remaining = agent["timeout"] - (time.monotonic() - started)
            if remaining <= 0:
                raise AgentError("Business call exhausted the trace collection deadline")
            collected = _collect_trace(config, result, context, remaining)
            write_json(workspace / "collected_trace.json", _redact(collected, secrets))
            messages = field(collected, trace_settings["messages_path"])
            api_calls = field(collected, trace_settings["api_calls_path"])
            usage = field(collected, trace_settings["usage_path"])
            runtime_report = field(collected, trace_settings["runtime_report_path"], None)
        elif agent["require_harness_receipt"]:
            _verify_harness_receipt(field(result, agent["harness_receipt_path"], None), context)
        if runtime_report is not None and (not isinstance(runtime_report, dict) or runtime_report.get("schema") != "harnesslens.channel-load-report.v1" or runtime_report.get("harness") != "opencode"):
            raise AgentError("Business runtime_report is not an OpenCode channel-load report")
        if set(config["capabilities"]["channels"]) - {"instructions_rules"} and runtime_report is None:
            raise AgentError("Native business channels require the agent's effective runtime_report")
        if not isinstance(answer, str) or not answer.strip():
            raise AgentError("Business agent must return a nonempty answer string")
        known_usage = type(usage) in {int, float} and math.isfinite(usage) and usage > 0
        if not known_usage and agent["cost_metric"] == "tokens":
            raise AgentError("Business agent token usage is missing or invalid; it cannot be counted as zero")
        messages = normalize_messages(messages, trace_settings["trace_format"] if trace_settings else agent["trace_format"])
        if agent["require_trace"] and not messages:
            raise AgentError("Business agent must expose its existing trace via trace_path")
        if not isinstance(api_calls, list) or any(not isinstance(call, dict) or not isinstance(call.get("request"), dict) or call.get("response") is None for call in api_calls):
            raise AgentError("api_calls_path must map actual model requests and responses")
        receipt.update(status="succeeded", response=_redact(result, secrets), elapsed_s=time.monotonic() - started,
                       response_sha256=stable_hash(_redact(result, secrets)))
        if collected is not None:
            receipt["collected_trace"] = _redact(collected, secrets)
        transport = workspace / "agent_transport.jsonl"
        transport.write_text(json.dumps(_redact(receipt, secrets), ensure_ascii=False) + "\n")
        write_json(workspace / "agent_status.json", {"status": "succeeded", "request_id": context["request_id"]})
        return {"answer": _redact(answer, secrets), "messages": _redact(messages, secrets), "api_calls": _redact(api_calls, secrets),
                "runtime_report": _redact(runtime_report, secrets),
                "usage": {"total_tokens": usage if known_usage else None, "wall_seconds": receipt["elapsed_s"], "cost_metric": agent["cost_metric"]},
                "elapsed_s": receipt["elapsed_s"], "transport_jsonl": str(transport)}
    except Exception as exc:
        write_json(workspace / "agent_status.json", {"status": "failed", "request_id": context["request_id"],
            "http_status": getattr(exc, "status", None), "error_type": type(exc).__name__})
        if isinstance(exc, AgentError):
            raise
        raise AgentError(f"Business agent infrastructure failure ({type(exc).__name__}); inspect retained artifacts") from None
    finally:
        for p in (workspace / ".agent-runtime").glob("*"):
            if p.is_file() and p.suffix in {".json", ".log"}:
                p.write_text(_redact(p.read_text(errors="replace"), secrets))
