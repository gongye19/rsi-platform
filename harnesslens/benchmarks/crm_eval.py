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
from harnesslens.harnesses.harness_workspace import materialize_workspace, normalize_workspace_snapshot
from harnesslens.harnesses.native_harness_driver import parse_opencode_text, stable_hash, summarize_records, stop_process
from harnesslens.harnesses.native_candidate_runtime import candidate_workspace
from harnesslens.harnesses.candidate_config_runtime import load_json_configs, deep_merge, merge_candidate_config, relocate_opencode_instruction_paths, compile_opencode_agent_definitions
from harnesslens.harnesses.channel_preflight import build_runtime_load_report
from harnesslens.harnesses.opencode_runtime import _start_proxy, _stop_process, validate_api_trace
from harnesslens.evaluation.rollout_outcome import harness_execution_error
from harnesslens.harnesses.opencode_components import PROMPT_LANE_COMPONENTS, validate_config, validate_bundle, protocol_manifest


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
    return CrmLimits(timeout_s=business["agent"]["timeout"]) if business else CrmLimits()


def executable() -> Path:
    from harnesslens.core.config import resolve_opencode_binary
    return resolve_opencode_binary()


def runtime_fingerprint(repo_root: Path) -> dict:
    from harnesslens.benchmarks.adapters import runtime_sources
    shared = {name: sha(Path(name)) for name in runtime_sources()}
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
    if manifest.get("tool_desc_patches"):
        raise ValueError("CRM uses fixed CLI tools; MCP tool-description patches are unavailable")
    declared = {"home": {}, "project": {}}
    for item in candidate_workspace(manifest)["files"]:
        declared[item["scope"]][item["path"]] = item["content"]
    for item in manifest.get("files") or []:
        declared["project"][item["path"]] = item["content"]
    # Validate every declared config file independently, including files shadowed
    # by a later config path. A forbidden edit must not disappear during merging.
    config_names = {"config.json", "opencode.json", ".opencode/opencode.json"}
    configs = {}
    import json
    for scope, files in declared.items():
        for name, content in files.items():
            if name in config_names:
                value = json.loads(content)
                validate_config(value, PROMPT_LANE_COMPONENTS)
                configs = deep_merge(configs, value)
    from harnesslens.harnesses.native_candidate_runtime import apply_flat_config
    configs = apply_flat_config(configs, manifest.get("config_patch") or {})
    validate_bundle(declared, configs, PROMPT_LANE_COMPONENTS)
    for item in candidate_workspace(manifest)["files"]:
        name = item["path"]
        if item["scope"] == "project" and (name.split("/")[0] in {"source", "output", ".runtime", ".git"}):
            raise ValueError("Candidate cannot replace task inputs, output, or runtime files")
        if "/plugins/" in "/" + name or "/tools/" in "/" + name:
            raise ValueError("CRM does not enable executable plugins or custom tools")
    # Legacy manifest files are project-relative too.
    normalize_workspace_snapshot({"files": [{"scope": "project", "path": item["path"], "content": item["content"]} for item in manifest.get("files") or []]})
    for item in manifest.get("files") or []:
        if item["path"].split("/")[0] in {"source", "output", ".runtime", ".git"}:
            raise ValueError("Candidate cannot replace protected task files")
        if "/plugins/" in "/" + item["path"] or "/tools/" in "/" + item["path"]:
            raise ValueError("CRM does not enable executable plugins or custom tools")


def prepare_harness(trial: Path, manifest: dict, port: int, limits: CrmLimits) -> tuple[Path, dict, dict]:
    _validate_manifest(manifest)
    workspace = trial / "workspace"
    home = workspace / ".runtime/config/opencode"
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
    config_paths = (home / "config.json", home / "opencode.json", workspace / ".opencode/opencode.json", workspace / "opencode.json")
    candidate = load_json_configs(config_paths)
    candidate = relocate_opencode_instruction_paths(candidate, project_root=workspace)
    candidate = deep_merge(candidate, {"agent": compile_opencode_agent_definitions(workspace)})
    candidate = merge_candidate_config(candidate, legacy_flat_patch=manifest.get("config_patch") or {}, fixed={})
    validate_config(candidate, PROMPT_LANE_COMPONENTS)
    provider_id, model_id = model().split("/", 1)
    config = deep_merge(candidate, {
        "$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled",
        "model": model(), "small_model": model(), "enabled_providers": [provider_id],
        "provider": {provider_id: {"npm": "@ai-sdk/openai-compatible", "name": "CRM provider",
            "options": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "local-proxy", "timeout": 300000},
            "models": {model_id: {"name": model_id, "limit": {"context": 200000, "output": limits.output_tokens},
                                    "options": {"thinking": {"type": "disabled"}}}}}},
        "agent": {"build": {"steps": limits.max_steps}},
        "permission": {"*": "allow", "question": "deny", "webfetch": "deny", "websearch": "deny"},
        "tools": {"webfetch": False, "websearch": False},
    })
    # These are complete replacements: merging must not leave alternate providers,
    # extra MCP servers, plugin code, or candidate capability/permission overrides.
    config["provider"] = {provider_id: config["provider"][provider_id]}
    config["mcp"] = {}
    config["plugin"] = []
    config["tools"] = {name: name not in {"webfetch", "websearch"} for name in (
        "bash", "read", "write", "edit", "glob", "grep", "list", "task", "skill", "todowrite", "webfetch", "websearch")}
    config["permission"] = {"*": "allow", "question": "deny", "webfetch": "deny", "websearch": "deny"}
    config["instructions"] = list(dict.fromkeys([str(agents.resolve()), *config.get("instructions", [])]))
    for name, agent in config.get("agent", {}).items():
        if isinstance(agent, dict):
            for key in ("model", "provider", "tools", "permission", "steps"):
                agent.pop(key, None)
            agent["steps"] = limits.max_steps
    write_json(workspace / "opencode.json", config)
    for path in config_paths[:-1]:
        if path.is_file():
            write_json(path, config)
    report = build_runtime_load_report(harness="opencode", project_root=workspace, home_root=home,
                                       manifest=manifest, tool_definitions=[])
    return home, config, report


def sandbox_command(command: list[str], workspace: Path, ports: list[int]) -> list[str]:
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("CRM native adapter currently requires macOS Seatbelt")
    binary = executable()
    runtime = Path(os.environ.get("HAI_CRM_RUNTIME_ROOT") or binary.parent.parent).resolve()
    roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), runtime,
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
    for path in [workspace / "source", workspace / "AGENTS.md", workspace / "opencode.json", *[p for p in (workspace / ".opencode").rglob("*") if p.is_file()]]:
        rules.append(f"(deny file-write* (subpath {q(str(path))}))")
    rules += ["(deny network-outbound)", "(allow network-outbound " + " ".join(f'(remote tcp "localhost:{port}")' for port in ports) + ")"]
    return ["/usr/bin/sandbox-exec", "-p", "\n".join(rules), *command]


def _messages(events: list[dict]) -> list[dict]:
    completed = [item for item in events if isinstance(item.get("request"), dict)]
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
    """Stop on the first authentication/quota error, retaining failed evidence."""
    root = cwd.parent
    process = None
    error = ""
    try:
        with (root / "stdout.jsonl").open("w") as out, (root / "stderr.log").open("w") as err:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
            deadline = time.monotonic() + timeout_s
            while process.poll() is None:
                trace = root / "api_calls.jsonl"
                if trace.is_file():
                    for line in trace.read_text(errors="replace").splitlines():
                        try:
                            status = json.loads(line).get("upstream_status")
                        except ValueError:
                            continue
                        if status in (401, 402, 403, 429):
                            error = f"provider unavailable: HTTP {status}; execution paused"
                            break
                if error or time.monotonic() >= deadline:
                    error = error or "native OpenCode timeout"
                    stop_process(process)
                    break
                time.sleep(0.2)
    finally:
        stop_process(process)
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
            env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TZ") if k in os.environ}
            for name in ("home", "tmp", "cache", "data", "state"):
                (workspace / ".runtime" / name).mkdir(parents=True, exist_ok=True)
            env.update(HOME=str(workspace / ".runtime/home"), TMPDIR=str(workspace / ".runtime/tmp"),
                       XDG_CONFIG_HOME=str(home.parent), XDG_DATA_HOME=str(workspace / ".runtime/data"),
                       XDG_CACHE_HOME=str(workspace / ".runtime/cache"), XDG_STATE_HOME=str(workspace / ".runtime/state"),
                       OPENCODE_CONFIG=str(workspace / "opencode.json"), OPENCODE_DISABLE_PROJECT_CONFIG="1",
                       OPENCODE_DISABLE_AUTOCOMPACT="1", OPENCODE_DISABLE_PRUNE="1", OPENCODE_DISABLE_DEFAULT_PLUGINS="1")
            env["OPENCODE_DISABLE_MODELS_FETCH"] = "1"
            env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
            env["OPENCODE_CONFIG_DIR"] = str(workspace / ".opencode")
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            command = [str(executable()), "run", "--pure", "--format", "json", "--model", model(), "--dir", str(workspace), prompt]
            stdout, stderr, code = run_process(sandbox_command(command, workspace, [port, pg_port]),
                                              cwd=workspace, env=env, timeout_s=limits.timeout_s)
            (trial_root / "stdout.jsonl").write_text(stdout)
            (trial_root / "stderr.log").write_text(stderr)
            _stop_process(proxy)
            proxy = None
            trace = trial_root / "api_calls.jsonl"
            events = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()] if trace.is_file() else []
            row.update(api_calls_jsonl=str(trace), messages=_messages(events), runtime_load_report=report, model_context=report,
                       n_messages=len(_messages(events)), n_tool_calls=sum(len(m.get("tool_calls", [])) for m in _messages(events)))
            errors = [value for value in [validate_api_trace(trace), harness_execution_error(stdout, stderr),
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
                if row.get("infrastructure_error"):
                    raise RuntimeError(f"CRM execution paused: {row.get('error')}; retained at {directory}")
            return {"task_id": tid, "harness_version": harness_version, "rewards": [row["reward"] for row in rows],
                    "trajectory_paths": paths, "worker_errors": [],
                    "trial_summaries": [{k: row.get(k) for k in ("trial", "pairing_slot", "reward", "n_messages", "n_tool_calls", "termination", "usage")} for row in rows]}
        # Small default width keeps the same provider within its local quota.
        with ThreadPoolExecutor(max_workers=max(1, min(int(max_concurrency), len(task_repeats), 2))) as pool:
            records = list(pool.map(run_task, task_repeats))
    if signature != runtime_fingerprint(root):
        raise RuntimeError("CRM environment changed during execution")
    per_task = {r["task_id"]: {"repeats": len(r["rewards"]), **{k: r[k] for k in ("rewards", "trajectory_paths", "worker_errors", "trial_summaries")}} for r in records}
    return {"records": records, "per_task": per_task, "metrics": summarize_records(records)}
