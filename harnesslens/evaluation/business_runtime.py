"""Benchmark-independent business execution, delivery, evidence and cache validation."""
from __future__ import annotations
import fcntl
import json
import time
from pathlib import Path

from harnesslens.core.artifacts import write_json
from harnesslens.harnesses.business_agent import load_config, invoke, field
from harnesslens.harnesses.native_candidate_runtime import candidate_workspace
from harnesslens.harnesses.harness_workspace import materialize_workspace
from harnesslens.harnesses.candidate_config_runtime import load_json_configs, merge_candidate_config
from harnesslens.harnesses.channel_preflight import build_runtime_load_report
from harnesslens.harnesses.native_harness_driver import stable_hash
from harnesslens.benchmarks.adapters import sha
from harnesslens.harnesses.opencode_components import validate_config, validate_bundle, protocol_manifest
from harnesslens.harnesses.component_policy import allowed_components, policy_contract


def prepare_harness(workspace, manifest):
    from harnesslens.harnesses.native_candidate_runtime import native_manifest
    # OpenCode snapshot bookkeeping has already applied removals/replacements;
    # normalize only executable payload fields and the captured workspace.
    from harnesslens.harnesses.opencode_harness import normalize_opencode_manifest
    captured = manifest.get("_workspace")
    payload = normalize_opencode_manifest({key: value for key, value in manifest.items() if key != "_workspace"})
    manifest = native_manifest("opencode", {key: value for key, value in payload.items()
                              if key not in {"removals", "replace_channels"}} | {"_workspace": captured})
    from harnesslens.harnesses.opencode_execution import validate_manifest
    business = load_config()
    validate_manifest(manifest, business=business)
    if manifest.get("tool_desc_patches") and business:
        mapping = business["agent"]["arguments"] if business["agent"]["type"] == "python" else business["agent"]["body"]
        if "{tool_patches}" not in json.dumps(mapping):
            raise ValueError("Tool patches require a mapped {tool_patches} business argument/body field")
    root = workspace / "harness"
    home, project = root / "home", root / "project"
    home.mkdir(parents=True)
    project.mkdir()
    materialize_workspace(candidate_workspace(manifest), home_root=home, project_root=project)
    for item in manifest.get("files", []):
        p = project / item["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(item["content"])
    config = load_json_configs((home / "config.json", home / "opencode.json", project / ".opencode/opencode.json", project / "opencode.json"))
    config = merge_candidate_config(config, legacy_flat_patch=manifest.get("config_patch") or {}, fixed={})
    allowed = allowed_components(business)
    for path in (home / "config.json", home / "opencode.json", project / ".opencode/opencode.json", project / "opencode.json"):
        if path.is_file():
            validate_config(json.loads(path.read_text()), allowed)
    validate_config(config, allowed)
    # Preserve native system-prompt semantics; do not flatten it into AGENTS.md.
    if config:
        write_json(project / "opencode.json", config)
    agents = project / "AGENTS.md"
    instructions = [agents.read_text() if agents.is_file() else "", *manifest.get("instructions", []), *manifest.get("prompt_appends", [])]
    for name in config.get("instructions", []):
        path = (project / name).resolve()
        if not path.is_relative_to(project.resolve()) or not path.is_file():
            raise ValueError("Business instruction paths must point to delivered project files")
        instructions.append(path.read_text())
    resident = "\n\n".join(item for item in instructions if item.strip())
    agents.write_text(resident + "\n")
    files = {scope: {str(p.relative_to(root / scope)): p.read_text() for p in sorted((root / scope).rglob("*")) if p.is_file()}
             for scope in ("home", "project")}
    validate_bundle(files, config, allowed)
    report = build_runtime_load_report(harness="opencode", project_root=project, home_root=home,
        manifest=manifest, tool_definitions=[])
    report.update(delivery_kind="business-adapter", verification_level="prepared_files_only", component_protocol=protocol_manifest())
    return files, resident, project, report


def run_trial(*, adapter, resources, trial_root, task_id, trial, pairing_slot, scope, version, manifest, limits, signature):
    config = load_config()
    trial_root.mkdir(parents=True, exist_ok=True)
    with (trial_root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        identity = stable_hash({"environment": signature, "task_id": task_id, "pairing_slot": pairing_slot,
                               "scope": scope, "manifest": manifest, "limits": limits.to_dict()})
        target = trial_root / "trial.jsonl"
        if target.exists():
            row = json.loads(target.read_text())
            if row["identity_sha256"] != identity:
                raise ValueError("Business agent configuration changed; choose a new run-id")
            if row.get("infrastructure_error"):
                raise RuntimeError("Prior business-agent failure retained; inspect it before starting a new run")
            validate_record(row, target)
            return row
        workspace = trial_root / "workspace"
        if workspace.exists():
            raise RuntimeError("Interrupted business call retained; use a new run-id after inspecting its status")
        workspace.mkdir()
        start = time.monotonic()
        row = {"task_id": task_id, "trial": trial, "pairing_slot": pairing_slot, "scope": scope,
               "harness": "opencode", "harness_version": version, "identity_sha256": identity,
               "environment_fingerprint": signature, "agent_transport": config["agent"]["type"],
               "reward": 0.0, "messages": [], "infrastructure_error": True}
        try:
            prepared = adapter.prepare_task(workspace, task_id, resources)
            task_prompt = prepared["prompt"]
            files, instructions, harness_dir, report = prepare_harness(workspace, manifest)
            before = {"source": _inventory(workspace / "source"), "harness": _inventory(workspace / "harness")}
            seed = int(stable_hash({"task": task_id, "slot": pairing_slot})[:8], 16) & 0x7fffffff
            context = {"prompt": instructions + "\n\nTask:\n" + task_prompt, "instructions": instructions,
                       "harness_files": files, "harness_dir": str(harness_dir), "workspace": str(workspace),
                       "harness_digest": stable_hash(files), "task": adapter.public_task(task_id), "task_id": task_id,
                       "request_id": identity, "trial_id": f"{identity}-{trial}", "seed": seed, "scope": scope,
                       "model": config["agent"]["name"], "steps": limits.max_steps, "timeout": config["agent"]["timeout"]}
            context.update(harness_version=version, component_protocol=protocol_manifest(),
                           tool_patches=manifest.get("tool_desc_patches") or {}, component_policy=policy_contract(config))
            context.update(_private_roots=prepared.get("private_roots", []), _private_ports=prepared.get("private_ports", []))
            result = invoke(config, context, workspace)
            if result.get("runtime_report"):
                report = result["runtime_report"]
            after = {"source": _inventory(workspace / "source"), "harness": _inventory(workspace / "harness")}
            if before != after:
                raise RuntimeError("Business agent changed fixed task inputs or harness files")
            response_trace = trial_root / "agent_transport.jsonl"
            response_trace.write_bytes(Path(result["transport_jsonl"]).read_bytes())
            row.update(agent_transport_jsonl=str(response_trace), agent_transport_sha256=sha(response_trace),
                       messages=result["messages"], usage=result["usage"], model_context=report,
                       n_messages=len(result["messages"]), n_tool_calls=sum(len(m.get("tool_calls", [])) for m in result["messages"]),
                       model_request_evidence=bool(result["api_calls"]))
            if result["api_calls"]:
                path = trial_root / "api_calls.jsonl"
                path.write_text("".join(json.dumps(call, ensure_ascii=False) + "\n" for call in result["api_calls"]))
                row.update(api_calls_jsonl=str(path), api_trace_sha256=sha(path))
            validate_record(row, target)
            (trial_root / "answer.txt").write_text(result["answer"])
            outcome = adapter.grade(task_id, result["answer"])
            write_json(trial_root / "grading.json", outcome)
            row.update(answer=result["answer"], reward=outcome["reward"], verifier_completed=True,
                       grader_diagnostic={"completed": True, "passed": bool(outcome["reward"]), "validator_sha256": outcome["validator_sha256"]},
                       termination="completed", infrastructure_error=False)
        except Exception as exc:
            row.update(error=f"{type(exc).__name__}: {exc}", termination="infrastructure_error")
        row["elapsed_s"] = round(time.monotonic() - start, 3)
        target.write_text(json.dumps(row, ensure_ascii=False) + "\n")
        return row


def validate_record(row, trajectory):
    def resolve(key):
        path = Path(row[key])
        return path if path.is_absolute() else Path(trajectory).parent / path
    path = resolve("agent_transport_jsonl")
    if row.get("agent_transport_sha256") != sha(path):
        raise ValueError("Business transport evidence changed")
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(events) != 1 or events[0].get("status") != "succeeded" or not isinstance(events[0].get("request"), dict):
        raise ValueError("Business call did not retain a complete transport receipt")
    if row.get("api_calls_jsonl"):
        from harnesslens.evaluation.rollout_outcome import provider_trace_error
        trace = resolve("api_calls_jsonl")
        if row.get("api_trace_sha256") != sha(trace) or provider_trace_error(trace):
            raise ValueError("Business model-request evidence is incomplete or changed")


def _inventory(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


def run_business_batch(*, adapter, run_root, scope, harness, harness_version, harness_manifest,
                       task_repeats, pairing_offsets, max_concurrency, limits=None):
    from concurrent.futures import ThreadPoolExecutor
    from harnesslens.harnesses.native_harness_driver import summarize_records
    from harnesslens.harnesses.business_agent import load_config
    if harness != "opencode" or not load_config():
        raise ValueError("Business benchmark requires an OpenCode agent via --agent-config")
    split = adapter.split()
    allowed = split.train if scope == "TRAIN" else split.test if scope == "TEST" else ()
    if not task_repeats or set(task_repeats) - set(allowed) or any(type(k) is not int or k < 1 for k in task_repeats.values()):
        raise ValueError("Requested tasks/repeats are outside the declared benchmark scope")
    if set(pairing_offsets) - set(task_repeats) or any(type(k) is not int or k < 0 for k in pairing_offsets.values()):
        raise ValueError("Pairing slots must be nonnegative integers")
    signature = adapter.fingerprint()
    limits = limits or adapter.limits()
    output = Path(run_root).resolve()
    from harnesslens.infrastructure.batch_progress import BatchProgress
    progress = BatchProgress(output, scope, harness_version, task_repeats)
    with adapter.execution_context() as resources:
        def execute(tid):
            rows, paths = [], []
            for trial in range(task_repeats[tid]):
                # Task IDs are data; a digest prevents path traversal and sanitized-name collisions.
                directory = output / "trials" / stable_hash({"task": tid}) / f"trial_{trial:04d}"
                with progress.trial(tid, trial):
                    row = run_trial(adapter=adapter, resources=resources, trial_root=directory,
                        task_id=tid, trial=trial, pairing_slot=pairing_offsets.get(tid, 0) + trial,
                        scope=scope, version=harness_version, manifest=harness_manifest, limits=limits, signature=signature)
                    if row.get("infrastructure_error"):
                        raise RuntimeError(f"Business execution paused: {row.get('error')}; retained at {directory}")
                    rows.append(row)
                    paths.append(str(directory / "trial.jsonl"))
            return {"task_id": tid, "harness_version": harness_version, "rewards": [r["reward"] for r in rows],
                "trajectory_paths": paths, "worker_errors": [], "trial_summaries": [{k: r.get(k) for k in
                ("trial", "pairing_slot", "reward", "n_messages", "n_tool_calls", "termination", "usage")} for r in rows]}
        with ThreadPoolExecutor(max_workers=max(1, min(int(max_concurrency), adapter.max_concurrency, len(task_repeats)))) as pool:
            records = list(pool.map(execute, task_repeats))
    if signature != adapter.fingerprint():
        raise RuntimeError("Benchmark or business agent environment changed during execution")
    per_task = {r["task_id"]: {"repeats": len(r["rewards"]), **{k: r[k] for k in
                ("rewards", "trajectory_paths", "worker_errors", "trial_summaries")}} for r in records}
    return {"records": records, "per_task": per_task, "metrics": summarize_records(records)}
