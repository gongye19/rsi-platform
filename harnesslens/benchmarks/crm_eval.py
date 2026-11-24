"""Native OpenCode execution for the same 13 DAB CRM tasks used by RRSI.

Only public task data enters each Seatbelt workspace. Official validators run
in the host after the agent exits. The model proxy retains complete requests,
responses and usage; source data and the PostgreSQL snapshot remain immutable.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from .crm import TASK_IDS, PG_DATABASE, PG_READER, dataset_root, load_tasks, data_fingerprint, grade, sha
from .crm_postgres import ReadOnlyPostgresProxy, fingerprint as pg_fingerprint
from harnesslens.core.artifacts import write_json
from harnesslens.harnesses.harness_workspace import materialize_workspace
from harnesslens.harnesses.native_harness_driver import parse_opencode_text, stable_hash, summarize_records, stop_process
from harnesslens.harnesses.native_candidate_runtime import candidate_workspace
from harnesslens.harnesses.candidate_config_runtime import deep_merge
from harnesslens.harnesses.channel_preflight import build_runtime_load_report
from harnesslens.harnesses.opencode_runtime import _start_proxy, _stop_process, validate_api_trace
from harnesslens.evaluation.rollout_outcome import harness_execution_error
from harnesslens.harnesses.opencode_components import protocol_manifest


@dataclass(frozen=True)
class CrmLimits:
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
    return os.environ.get("HAI_CRM_MODEL", "crm/glm-5.2")


def effective_limits():
    from harnesslens.harnesses.business_agent import load_config
    business = load_config()
    if business:
        return CrmLimits(timeout_s=business["agent"]["timeout"])
    timeout = int(os.environ.get("HAI_CRM_TIMEOUT_S", "600"))
    if not 30 <= timeout <= 7200:
        raise ValueError("HAI_CRM_TIMEOUT_S must be between 30 and 7200")
    return CrmLimits(timeout_s=timeout)


def crm_workers(requested, task_count):
    cap = int(os.environ.get("HAI_CRM_MAX_CONCURRENCY", "2"))
    if not 1 <= cap <= 30:
        raise ValueError("HAI_CRM_MAX_CONCURRENCY must be between 1 and 30")
    return max(1, min(int(requested), int(task_count), cap))


def executable() -> Path:
    from harnesslens.core.config import resolve_opencode_binary
    return resolve_opencode_binary()


def runtime_fingerprint(repo_root: Path) -> dict:
    from harnesslens.benchmarks.adapters import runtime_sources
    shared = {name: sha(Path(name)) for name in runtime_sources()}
    from harnesslens.harnesses.component_policy import policy_contract
    shared["experiment_component_policy"] = policy_contract()
    shared["plugin_helper_pin"] = json.loads((repo_root / "configs/opencode-plugin-runtime.json").read_text())
    from harnesslens.harnesses.business_agent import load_config, fingerprint
    business = load_config()
    if business:
        return {"model": business["agent"]["name"], "business_agent": fingerprint(business), "component_protocol": protocol_manifest(), "shared_runtime_sources": shared,
                "adapter_sources": {name: sha(Path(__file__).with_name(name)) for name in ("crm.py", "crm_eval.py", "crm_business.py", "crm_query.py", "crm_postgres.py")},
                "database": pg_fingerprint(repo_root), "data": data_fingerprint(repo_root)}
    from harnesslens.core.config import opencode_version
    binary = executable()
    runtime_root = Path(os.environ.get("HAI_CRM_RUNTIME_ROOT") or binary.parent.parent).resolve()
    entry = runtime_root / "app/src/index.js"
    return {"model": model(), "provider_base_url": os.environ.get("DEEPSEEK_BASE_URL", ""), "component_protocol": protocol_manifest(), "shared_runtime_sources": shared,
            "opencode_version": opencode_version(binary),
            "binary": str(binary), "binary_sha256": sha(binary),
            "runtime_entry_sha256": sha(entry) if entry.is_file() else None,
            "runtime_files": {str(p.relative_to(runtime_root)): sha(p) for p in sorted(runtime_root.rglob("*.js"))},
            "runtime_engine_sha256": sha(runtime_root / "bin/bun") if (runtime_root / "bin/bun").is_file() else None,
            "adapter_sources": {name: sha(Path(__file__).with_name(name)) for name in ("crm.py", "crm_eval.py", "crm_query.py", "crm_postgres.py")},
            "database": pg_fingerprint(repo_root), "data": data_fingerprint(repo_root)}


def _inventory(root: Path) -> dict:
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def prepare_task(repo_root: Path, workspace: Path, task_id: str, pg_proxy_port: int) -> str:
    task = load_tasks(repo_root)[task_id]
    root = dataset_root(repo_root)
    source = workspace / "source"
    source.mkdir()
    (workspace / "output").mkdir()
    write_json(source / "task.json", task)
    shutil.copyfile(root / "db_description.txt", source / "db_description.txt")
    shutil.copyfile(Path(__file__).with_name("crm_query.py"), source / "query.py")
    data = source / "data"
    data.mkdir()
    connections = {}
    for name, kind in (("core_crm", "sqlite"), ("products_orders", "sqlite"), ("territory", "sqlite"),
                       ("sales_pipeline", "duckdb"), ("activities", "duckdb")):
        filename = name + (".db" if kind == "sqlite" else ".duckdb")
        shutil.copyfile(root / "query_dataset" / filename, data / filename)
        connections[name] = {"type": kind, "path": "data/" + filename}
    connections["support"] = {"type": "postgres", "dsn": f"host=127.0.0.1 port={pg_proxy_port} user={PG_READER} dbname={PG_DATABASE} sslmode=disable connect_timeout=5"}
    write_json(source / "connections.json", connections)
    return (str(task["query"]) + "\n\nDatabase descriptions: source/db_description.txt; "
            "connection names: source/connections.json. Use `python source/query.py schema DATABASE` "
            "or `python source/query.py sql DATABASE 'SQL' [--limit N]`. "
            "You may write Python scripts to combine results across databases. "
            "Derive the answer from the source data, save your final response to output/answer.txt, "
            "and finish with the same response. Work autonomously.")


def _validate_manifest(manifest: dict):
    from harnesslens.harnesses.business_agent import load_config
    from harnesslens.harnesses.opencode_execution import validate_manifest
    return validate_manifest(manifest, business=load_config(), max_steps=CrmLimits().max_steps)


def prepare_harness(trial: Path, manifest: dict, port: int, limits: CrmLimits) -> tuple[Path, dict, dict]:
    from harnesslens.harnesses.opencode_execution import (validate_manifest, candidate_config,
        relocate, prepare_extensions, lower_tool_visibility)
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
        "provider": {provider_id: {"npm": "@ai-sdk/openai-compatible", "name": "CRM provider",
            "options": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "local-proxy", "timeout": 300000},
            "models": {model_id: {"name": model_id, "limit": {"context": 200000, "output": limits.output_tokens},
                                    "options": {"thinking": {"type": "disabled"}}}}}}}
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


def sandbox_command(command: list[str], workspace: Path, ports: list[int]) -> list[str]:
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("CRM native adapter currently requires macOS Seatbelt")
    binary = executable()
    runtime = Path(os.environ.get("HAI_CRM_RUNTIME_ROOT") or binary.parent.parent).resolve()
    from harnesslens.harnesses.opencode_execution import install_plugin_helpers
    helper = install_plugin_helpers(workspace / ".runtime/native")
    roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), runtime, helper,
             Path(shutil.which("bun") or binary).resolve().parent.parent]
    q = json.dumps
    rules = ["(version 1)", "(allow default)"]
    for p in (Path.home().resolve(), Path(tempfile.gettempdir()).resolve(), Path("/private/tmp")):
        rules.append(f"(deny file-read* file-write* (subpath {q(str(p))}))")
    rules.append("(allow file-read-metadata)")
    for p in {p for root in [workspace, *roots] for p in root.parents}:
        rules.append(f"(allow file-read* (literal {q(str(p))}))")
    for root in roots:
        rules.append(f"(allow file-read* (subpath {q(str(root))}))")
    rules.append(f"(allow file-read* file-write* (subpath {q(str(workspace))}))")
    settings = workspace / ".runtime/harnesslens/settings.json"
    protected = json.loads(settings.read_text()).get("protected_files", []) if settings.is_file() else []
    for path in protected:
        rules.append(f"(deny file-write* (subpath {q(str(Path(path).resolve()))}))")
    for path in [workspace / "source", workspace / "AGENTS.md", workspace / "opencode.json", workspace / "node_modules",
                 workspace / ".runtime/candidate-home", workspace / ".runtime/native",
                 *[p for p in (workspace / ".opencode").rglob("*") if p.is_file()],
                 *[p for p in (workspace / ".runtime/harnesslens").glob("*") if p.suffix != ".jsonl"]]:
        rules.append(f"(deny file-write* (subpath {q(str(path))}))")
    rules += ["(deny network-outbound)", "(allow network-outbound " + " ".join(f'(remote tcp "localhost:{port}")' for port in ports) + ")"]
    return ["/usr/bin/sandbox-exec", "-p", "\n".join(rules), *command]


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
    messages = list(last["request"].get("messages", []))
    choices = (last.get("response") or {}).get("choices", [])
    if choices and choices[0].get("message"):
        messages.append(choices[0]["message"])
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


def _trial(*, repo_root: Path, trial_root: Path, task_id: str, trial: int, pairing_slot: int,
           scope: str, version: str, manifest: dict, limits: CrmLimits, signature: dict, pg_port: int) -> dict:
    trial_root.mkdir(parents=True, exist_ok=True)
    with (trial_root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        row_path = trial_root / "trial.jsonl"
        identity = {"environment": signature, "task_id": task_id, "trial": trial, "pairing_slot": pairing_slot,
                    "scope": scope, "version": version, "manifest": manifest, "limits": limits.to_dict()}
        identity_hash = stable_hash(identity)
        if row_path.exists():
            row = json.loads(row_path.read_text())
            if row.get("identity_sha256") != identity_hash:
                raise ValueError("CRM cached trial configuration changed; choose a new run-id")
            if row.get("candidate_execution_failed"):
                from harnesslens.harnesses.channel_preflight import CandidateRuntimeError
                raise CandidateRuntimeError(row.get("error", "Candidate component failed"), trial_root)
            if row.get("infrastructure_error"):
                raise RuntimeError("Prior CRM infrastructure failure retained; use a new run-id after resolving it")
            if validate_api_trace(trial_root / "api_calls.jsonl") or row.get("api_trace_sha256") != sha(trial_root / "api_calls.jsonl"):
                raise ValueError("CRM cached API trace changed")
            return row
        workspace = trial_root / "workspace"
        if workspace.exists():
            raise RuntimeError("Interrupted CRM trial has artifacts; preserve them and use a new run-id")
        workspace.mkdir()
        proxy = None
        started = time.monotonic()
        row = {"task_id": task_id, "trial": trial, "pairing_slot": pairing_slot, "harness": "opencode",
               "harness_version": version, "scope": scope, "identity_sha256": identity_hash,
               "environment_fingerprint": signature,
               "reward": 0.0, "messages": [], "infrastructure_error": True}
        try:
            prompt = prepare_task(repo_root, workspace, task_id, pg_port)
            before = _inventory(workspace / "source")
            proxy, port = _start_proxy(run_root=trial_root, call_id=f"crm/{task_id}/slot-{pairing_slot}")
            home, config, report = prepare_harness(trial_root, manifest, port, limits)
            fixed = {str(p.relative_to(workspace)): sha(p) for p in [workspace / "AGENTS.md", workspace / "opencode.json", *[p for p in home.rglob("*") if p.is_file()], *[p for p in (workspace / ".opencode").rglob("*") if p.is_file()]]}
            settings = json.loads((workspace / ".runtime/harnesslens/settings.json").read_text())
            fixed.update({str(Path(p).relative_to(workspace)): sha(Path(p)) for p in settings["protected_files"]})
            env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TZ") if k in os.environ}
            for name in ("home", "tmp", "cache", "data", "state"):
                (workspace / ".runtime" / name).mkdir(parents=True, exist_ok=True)
            env.update(HOME=str(workspace / ".runtime/home"), TMPDIR=str(workspace / ".runtime/tmp"),
                       XDG_CONFIG_HOME=str(workspace / ".runtime/platform-config"), XDG_DATA_HOME=str(workspace / ".runtime/data"),
                       XDG_CACHE_HOME=str(workspace / ".runtime/cache"), XDG_STATE_HOME=str(workspace / ".runtime/state"),
                       OPENCODE_CONFIG=str(workspace / "opencode.json"), OPENCODE_DISABLE_PROJECT_CONFIG="1",
                       OPENCODE_DISABLE_DEFAULT_PLUGINS="1")
            env["OPENCODE_DISABLE_MODELS_FETCH"] = "1"
            env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
            env["OPENCODE_CONFIG_DIR"] = str(workspace / ".runtime/native")
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            from harnesslens.harnesses.opencode_execution import ENTRY_COMMAND, refresh_report
            command = [str(executable()), "run", "--format", "json", "--model", model(), "--dir", str(workspace),
                       "--command", ENTRY_COMMAND, prompt]
            stdout, stderr, code = run_process(sandbox_command(command, workspace, [port, pg_port]),
                                              cwd=workspace, env=env, timeout_s=limits.timeout_s)
            (trial_root / "stdout.jsonl").write_text(stdout)
            (trial_root / "stderr.log").write_text(stderr)
            _stop_process(proxy)
            proxy = None
            trace = trial_root / "api_calls.jsonl"
            component_errors = refresh_report(report, workspace, trace)
            if version != "v0" and any(e.get("kind") in {"component_error", "policy_violation"}
                                        for e in report.get("native_component_events", [])):
                row["candidate_execution_failed"] = True
            events = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()] if trace.is_file() else []
            primary_session = next((e.get("session_id") for e in report.get("native_component_events", []) if e.get("kind") == "command_invoked"), None)
            messages = _messages(events, primary_session)
            sessions = {}
            for event in events:
                if not event.get("session_id") or not isinstance(event.get("request"), dict): continue
                session = sessions.setdefault(event["session_id"], {"agent_name": None, "agent_names": [], "request_indices": []})
                name = event.get("agent_name")
                if name and name not in session["agent_names"]: session["agent_names"].append(name)
                if name not in {None, "title", "summary", "compaction"}: session["agent_name"] = name
                session["request_indices"].append(event.get("call_index"))
            for event in report.get("native_component_events", []):
                info = (event.get("event", {}).get("properties") or {}).get("info", {})
                if info.get("id") in sessions:
                    sessions[info["id"]]["parent_session_id"] = info.get("parentID")
            row.update(api_calls_jsonl=str(trace), primary_session_id=primary_session, model_sessions=sessions,
                       messages=messages, runtime_load_report=report, model_context=report,
                       n_messages=len(messages), n_tool_calls=sum(len(choice.get("message", {}).get("tool_calls", []))
                           for event in events for choice in (event.get("response") or {}).get("choices", [])))
            errors = [value for value in [*component_errors, validate_api_trace(trace), harness_execution_error(stdout, stderr),
                      "native OpenCode exited unsuccessfully" if code != 0 else ""] if value]
            if before != _inventory(workspace / "source") or any(not (workspace / p).is_file() or sha(workspace / p) != value for p, value in fixed.items()):
                errors.append("fixed task/harness files changed")
            if errors:
                raise RuntimeError("; ".join(errors))
            usages = [event.get("usage") for event in events if "request" in event]
            if not usages or any(not isinstance(u, dict) or not isinstance(u.get("total_tokens"), (int, float)) for u in usages):
                raise RuntimeError("provider returned incomplete token usage")
            answer_file = workspace / "output/answer.txt"
            answer = answer_file.read_text() if answer_file.is_file() else parse_opencode_text(stdout)
            (trial_root / "answer.txt").write_text(answer)
            result = grade(repo_root, task_id, answer)
            write_json(trial_root / "grading.json", result)
            row.update(reward=result["reward"], termination="completed", infrastructure_error=False,
                       verifier_completed=True, grader_diagnostic={"completed": True, "passed": bool(result["reward"]),
                                                                  "validator_sha256": result["validator_sha256"]}, answer=answer,
                       api_trace_sha256=sha(trace), usage={"total_tokens": sum(u["total_tokens"] for u in usages), "request_count": len(usages)})
        except Exception as exc:
            row.update(error=f"{type(exc).__name__}: {exc}", termination="infrastructure_error")
        finally:
            _stop_process(proxy)
            row["elapsed_s"] = round(time.monotonic() - started, 3)
            row_path.write_text(json.dumps(row, ensure_ascii=False) + "\n")
        return row


def run_crm_batch(*, repo_root, run_root, scope, harness, harness_version, harness_manifest,
                  task_repeats, pairing_offsets, max_concurrency, limits=None) -> dict:
    from harnesslens.benchmarks.benchmark_splits import load_benchmark_split
    if harness != "opencode":
        raise ValueError("CRM currently supports OpenCode only")
    split = load_benchmark_split("crm")
    allowed = split.train if scope == "TRAIN" else split.test if scope == "TEST" else ()
    if not task_repeats or set(task_repeats) - set(allowed) or any(type(k) is not int or k < 1 for k in task_repeats.values()):
        raise ValueError("CRM requested tasks/repeats are outside the declared scope")
    if set(pairing_offsets) - set(task_repeats) or any(type(k) is not int or k < 0 for k in pairing_offsets.values()):
        raise ValueError("CRM pairing slots must be nonnegative integers")
    _validate_manifest(harness_manifest)
    root, output = Path(repo_root).resolve(), Path(run_root).resolve()
    limits = limits or effective_limits()
    signature = runtime_fingerprint(root)
    from harnesslens.harnesses.business_agent import load_config
    if load_config():
        from .crm_business import run_trial
    else:
        run_trial = _trial
    records = []
    with ReadOnlyPostgresProxy() as proxy:
        def run_task(tid):
            rows = []
            paths = []
            for trial in range(task_repeats[tid]):
                directory = output / "trials" / tid.replace("/", "_") / f"trial_{trial:04d}"
                row = run_trial(repo_root=root, trial_root=directory, task_id=tid, trial=trial,
                             pairing_slot=pairing_offsets.get(tid, 0) + trial, scope=scope, version=harness_version,
                             manifest=harness_manifest, limits=limits, signature=signature, pg_port=proxy.port)
                rows.append(row)
                paths.append(str(directory / "trial.jsonl"))
                if row.get("candidate_execution_failed"):
                    from harnesslens.harnesses.channel_preflight import CandidateRuntimeError
                    raise CandidateRuntimeError(row.get("error", "Candidate component failed"), directory)
                if row.get("infrastructure_error"):
                    raise RuntimeError(f"CRM execution paused: {row.get('error')}; retained at {directory}")
            return {"task_id": tid, "harness_version": harness_version, "rewards": [row["reward"] for row in rows],
                    "trajectory_paths": paths, "worker_errors": [],
                    "trial_summaries": [{k: row.get(k) for k in ("trial", "pairing_slot", "reward", "n_messages", "n_tool_calls", "termination", "usage")} for row in rows]}
        with ThreadPoolExecutor(max_workers=crm_workers(max_concurrency, len(task_repeats))) as pool:
            records = list(pool.map(run_task, task_repeats))
    if signature != runtime_fingerprint(root):
        raise RuntimeError("CRM environment changed during execution")
    per_task = {r["task_id"]: {"repeats": len(r["rewards"]), **{k: r[k] for k in ("rewards", "trajectory_paths", "worker_errors", "trial_summaries")}} for r in records}
    return {"records": records, "per_task": per_task, "metrics": summarize_records(records)}
