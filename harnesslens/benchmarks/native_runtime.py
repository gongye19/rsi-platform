"""Native OpenCode 运行通用助手：harness 准备、进程执行与消息提取。

从早期 CRM 评测模块中抽出的与具体 benchmark 无关的部分，
供 FDABench 等原生 OpenCode 生命周期复用。
"""
from __future__ import annotations
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from harnesslens.core.artifacts import write_json
from harnesslens.harnesses.harness_workspace import materialize_workspace
from harnesslens.harnesses.native_harness_driver import stop_process
from harnesslens.harnesses.native_candidate_runtime import candidate_workspace
from harnesslens.harnesses.candidate_config_runtime import deep_merge
from harnesslens.harnesses.channel_preflight import build_runtime_load_report
from harnesslens.harnesses.opencode_execution import (
    validate_manifest,
    candidate_config,
    relocate,
    prepare_extensions,
    lower_tool_visibility,
)


@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 40
    timeout_s: int = 600
    output_tokens: int = 8192

    def to_dict(self):
        return asdict(self)


def model() -> str:
    from harnesslens.harnesses.business_agent import load_config
    business = load_config()
    if business:
        return business["agent"]["name"]
    from harnesslens.core.model_config import connection
    return connection("execution")["model"] or "deepseek/deepseek-v4-flash"


def executable() -> Path:
    from harnesslens.core.config import resolve_opencode_binary
    return resolve_opencode_binary()


def _inventory(root: Path) -> dict:
    from .adapters import sha
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def prepare_harness(trial: Path, manifest: dict, port: int, limits: RunLimits) -> tuple[Path, dict, dict]:
    validate_manifest(manifest, max_steps=limits.max_steps)
    workspace = trial / "workspace"
    home = workspace / ".runtime/candidate-home"
    home.mkdir(parents=True)
    (workspace / ".opencode").mkdir(exist_ok=True)
    materialize_workspace(candidate_workspace(manifest), home_root=home, project_root=workspace)
    for item in manifest.get("files") or []:
        path = workspace / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["content"])
    agents = workspace / "AGENTS.md"
    instructions = [agents.read_text() if agents.is_file() else "", *manifest.get("instructions", []), *manifest.get("prompt_appends", [])]
    agents.write_text("\n\n".join(instructions) + "\n")
    candidate = relocate(candidate_config(home, workspace, manifest), home=home, project=workspace)
    from harnesslens.core.model_config import connection
    selected = connection("execution")
    provider_id, model_id = model().split("/", 1)
    # Defaults are below candidate behavioral edits. Only infrastructure/model
    # settings are fixed above them; the sandbox enforces data/network boundaries.
    defaults = {"agent": {"build": {"steps": limits.max_steps}},
        "permission": {"*": "allow", "question": "deny", "webfetch": "deny", "websearch": "deny"},
        "compaction": {"auto": False, "prune": False}, "mcp": {}, "plugin": [],
        "tools": {name: name not in {"webfetch", "websearch"} for name in (
            "bash", "read", "write", "edit", "glob", "grep", "list", "task", "skill", "todowrite", "webfetch", "websearch")}}
    config = deep_merge(defaults, candidate)
    fixed = {"$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled",
        "model": model(), "small_model": model(), "enabled_providers": [provider_id],
        "provider": {provider_id: {"npm": "@ai-sdk/openai" if selected["api"] == "responses" else "@ai-sdk/openai-compatible", "name": "Execution provider",
            "options": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "local-proxy", "timeout": 300000},
            "models": {model_id: {"name": model_id, "limit": {"context": 200000, "output": limits.output_tokens},
                                    "options": {"thinking": {"type": "disabled"}} if "/glm-" in model() else ({"store": False} if selected["api"] == "responses" else {})}}}}}
    config = deep_merge(config, fixed)
    config["instructions"] = list(dict.fromkeys([str(agents.resolve()), *config.get("instructions", [])]))
    # Skills delivered in HOME remain discoverable without loading uncontrolled
    # config/plugin directories from the machine running the experiment.
    skill_paths = list(config.get("skills", {}).get("paths", []))
    for folder in (home / "skills", home / "skill", workspace / ".opencode/skills", workspace / ".opencode/skill"):
        if folder.is_dir(): skill_paths.append(str(folder.resolve()))
    if skill_paths: config.setdefault("skills", {})["paths"] = list(dict.fromkeys(skill_paths))
    lower_tool_visibility(config)
    prepare_extensions(workspace=workspace, home=home, config=config, manifest=manifest, max_steps=limits.max_steps)
    write_json(workspace / "opencode.json", config)
    report = build_runtime_load_report(harness="opencode", project_root=workspace, home_root=home,
                                       manifest=manifest, tool_definitions=[])
    return home, config, report


def _messages(events: list[dict], session_id=None) -> list[dict]:
    completed = [item for item in events if isinstance(item.get("request"), dict)]
    primary = [item for item in completed if item.get("agent_name") not in {"title", "summary", "compaction"}]
    if primary: completed = primary
    if session_id:
        matching = [item for item in completed if item.get("session_id") == session_id]
        if matching: completed = matching
    if not completed:
        return []
    last = completed[-1]
    from harnesslens.core.model_trace import conversation
    messages = conversation(last["request"], last.get("response"))
    normalized = []
    for raw in messages:
        item = dict(raw)
        if item.get("tool_calls"):
            item["tool_calls"] = [{"id": call.get("id"), "name": call.get("function", {}).get("name"),
                                   "arguments": call.get("function", {}).get("arguments")} for call in item["tool_calls"]]
        normalized.append(item)
    return normalized


def run_process(command, *, cwd, env, timeout_s):
    """Stop on terminal provider failure; allow bounded upstream retries to finish."""
    root = cwd.parent
    process = None
    error = ""
    from harnesslens.infrastructure.trace_watch import ProviderTraceWatch
    watch = ProviderTraceWatch(root / "api_calls.jsonl")
    try:
        with (root / "stdout.jsonl").open("w") as out, (root / "stderr.log").open("w") as err:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
            deadline = time.monotonic() + timeout_s
            while process.poll() is None:
                error = watch.error()
                if error or time.monotonic() >= deadline:
                    error = error or "native OpenCode timeout"
                    stop_process(process)
                    break
                time.sleep(0.2)
    finally:
        stop_process(process)
        if process is not None:
            # MCP/tool descendants may outlive a normally exited CLI. This
            # group was created exclusively for this trial with setsid.
            import signal
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
    return ((root / "stdout.jsonl").read_text(), (root / "stderr.log").read_text() + error,
            process.returncode if process and not error else None)
