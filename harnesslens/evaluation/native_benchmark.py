"""Native OpenCode lifecycle for data adapters; host-only tools/judges, no Docker."""

from __future__ import annotations
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from harnesslens.core.artifacts import write_json
from harnesslens.benchmarks.adapters import sha
from harnesslens.benchmarks.native_runtime import (
    prepare_harness,
    run_process,
    _messages,
    model,
    executable,
    _inventory,
)
from harnesslens.harnesses.opencode_runtime import (
    _start_proxy,
    _stop_process,
    validate_api_trace,
)
from harnesslens.harnesses.opencode_execution import refresh_report, ENTRY_COMMAND
from harnesslens.harnesses.native_harness_driver import (
    stable_hash,
    parse_opencode_text,
    summarize_records,
)


@contextmanager
def isolated_command(command, workspace, ports, protected):
    from harnesslens.infrastructure.process_isolation import (
        bubblewrap_command,
        seatbelt_command,
    )
    from harnesslens.infrastructure.loopback_gateway import host_gateway

    runtime = executable().resolve().parent
    from harnesslens.harnesses.opencode_execution import install_plugin_helpers

    helper = install_plugin_helpers(workspace / ".runtime/native")
    roots = [sys.prefix, sys.base_prefix, runtime, helper]
    for name in ("bun", "node"):
        binary = shutil.which(name)
        if binary:
            roots.append(str(Path(binary).resolve().parent))
    if sys.platform == "darwin":
        result = seatbelt_command(
            command,
            writable_root=workspace,
            working_directory=workspace,
            read_only_roots=roots,
        )
        result[2] += (
            "\n(deny network-outbound)\n(allow network-outbound "
            + " ".join(f'(remote tcp "localhost:{p}")' for p in ports)
            + ")"
        )
        for path in protected:
            result[2] += "\n(deny file-write* (subpath " + json.dumps(str(path)) + "))"
        yield result
    elif sys.platform == "linux":
        wrapper = workspace / ".runtime/network_gateway.py"
        shutil.copyfile(
            Path(__file__).resolve().parents[1] / "infrastructure/loopback_gateway.py",
            wrapper,
        )
        with host_gateway(ports) as gateway:
            inner = [
                sys.executable,
                str(wrapper),
                str(gateway),
                json.dumps(ports),
                *command,
            ]
            result = bubblewrap_command(
                inner,
                writable_root=workspace,
                working_directory=workspace,
                read_only_roots=[*roots, gateway],
            )
            boundary = result.index("--")
            result[boundary:boundary] = ["--unshare-net"]
            for path in [*protected, wrapper]:
                if Path(path).exists():
                    boundary = result.index("--")
                    result[boundary:boundary] = ["--ro-bind", str(path), str(path)]
            yield result
    else:
        raise RuntimeError(
            "Native FDABench requires Linux bubblewrap or macOS Seatbelt"
        )


def native_attempts():
    value = int(os.environ.get('HAI_NATIVE_EXECUTION_ATTEMPTS', '2'))
    if not 1 <= value <= 3:
        raise ValueError('HAI_NATIVE_EXECUTION_ATTEMPTS must be 1..3')
    return value


def _trace_valid(row, root):
    path = root / "api_calls.jsonl"
    if validate_api_trace(path) or row.get("api_trace_sha256") != sha(path):
        raise ValueError("Native provider trace is incomplete or changed")
    answer = root / "answer.txt"
    if not answer.exists() or sha(answer) != row.get("answer_sha256"):
        raise ValueError("Cached answer changed")


def run_trial(
    adapter,
    resources,
    root,
    task_id,
    trial,
    pairing_slot,
    scope,
    version,
    manifest,
    limits,
    signature,
):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        identity = stable_hash(
            {
                "environment": signature,
                "task": task_id,
                "slot": pairing_slot,
                "scope": scope,
                "manifest": manifest,
                "limits": limits.to_dict(),
            }
        )
        target = root / "trial.jsonl"
        checkpoint = root / "execution.json"
        if target.exists():
            row = json.loads(target.read_text())
            if row["identity_sha256"] != identity:
                raise ValueError(
                    "Cached FDABench configuration changed; choose a new run-id"
                )
            if row.get("candidate_execution_failed"):
                from harnesslens.harnesses.channel_preflight import (
                    CandidateRuntimeError,
                )

                raise CandidateRuntimeError(row.get("error", "Candidate failed"), root)
            if not row.get("infrastructure_error"):
                _trace_valid(row, root)
                return row
        if checkpoint.exists():
            row = json.loads(checkpoint.read_text())
            if row["identity_sha256"] != identity:
                raise ValueError("Execution checkpoint changed")
            _trace_valid(row, root)
        else:
            workspace = root / "workspace"
            if workspace.exists():
                if not target.exists():
                    raise RuntimeError("Interrupted execution has no checkpoint; inspect it and use a new run-id")
                maximum = native_attempts()
                previous = root / 'failed_attempts'
                previous.mkdir(exist_ok=True)
                count = len(list(previous.glob('attempt-*')))
                if count + 1 >= maximum:
                    raise RuntimeError('Native execution attempt limit reached; inspect retained failures')
                archived = previous / f'attempt-{count+1:04d}'
                archived.mkdir()
                for name in ('workspace', 'api_calls.jsonl', 'api_usage.jsonl', 'stdout.jsonl', 'stderr.log', 'trial.jsonl'):
                    path = root / name
                    if path.exists(): path.rename(archived / name)
            workspace.mkdir()
            proxy = None
            started = time.monotonic()
            row = {
                "task_id": task_id,
                "trial": trial,
                "pairing_slot": pairing_slot,
                "scope": scope,
                "harness": "opencode",
                "harness_version": version,
                "identity_sha256": identity,
                "environment_fingerprint": signature,
                "reward": 0.0,
                "infrastructure_error": True,
                "messages": [],
            }
            try:
                # The candidate cannot replace task inputs, tool client or platform runtime.
                from harnesslens.harnesses.native_candidate_runtime import (
                    candidate_workspace,
                )

                entries = [
                    *manifest.get("files", []),
                    *[
                        i
                        for i in candidate_workspace(manifest)["files"]
                        if i["scope"] == "project"
                    ],
                ]
                for item in entries:
                    if str(item.get("path", "")).split("/")[0] in {
                        "source",
                        "output",
                        ".runtime",
                    }:
                        from harnesslens.harnesses.channel_preflight import CandidateRuntimeError
                        row['candidate_execution_failed'] = True
                        raise CandidateRuntimeError('Candidate attempts to replace fixed native inputs',root)
                prepared = adapter.prepare_task(workspace, task_id, resources)
                before = _inventory(workspace / "source")
                proxy, port = _start_proxy(
                    run_root=root,
                    call_id=f"{adapter.cell}/{task_id}/{pairing_slot}",
                    role="execution",
                )
                home, config, report = prepare_harness(root, manifest, port, limits)
                from harnesslens.harnesses.opencode_execution import (
                    install_plugin_helpers,
                )

                install_plugin_helpers(workspace / ".runtime/native")
                settings = json.loads(
                    (workspace / ".runtime/harnesslens/settings.json").read_text()
                )
                protected = [
                    workspace / "source",
                    workspace / "AGENTS.md",
                    workspace / "opencode.json",
                    home,
                    workspace / ".opencode",
                    workspace / "node_modules",
                    workspace / ".runtime/native",
                    *[Path(p) for p in settings["protected_files"]],
                ]
                fixed = {str(p): sha(p) for p in protected if p.is_file()}
                env = {
                    k: os.environ[k]
                    for k in ("PATH", "LANG", "LC_ALL", "TZ")
                    if k in os.environ
                }
                for name in ("home", "tmp", "cache", "data", "state"):
                    (workspace / ".runtime" / name).mkdir(parents=True, exist_ok=True)
                env.update(
                    HOME=str(workspace / ".runtime/home"),
                    TMPDIR=str(workspace / ".runtime/tmp"),
                    XDG_CONFIG_HOME=str(workspace / ".runtime/platform-config"),
                    XDG_DATA_HOME=str(workspace / ".runtime/data"),
                    XDG_CACHE_HOME=str(workspace / ".runtime/cache"),
                    XDG_STATE_HOME=str(workspace / ".runtime/state"),
                    OPENCODE_CONFIG=str(workspace / "opencode.json"),
                    OPENCODE_CONFIG_DIR=str(workspace / ".runtime/native"),
                    OPENCODE_CONFIG_CONTENT=json.dumps(config),
                    OPENCODE_DISABLE_PROJECT_CONFIG="1",
                    OPENCODE_DISABLE_DEFAULT_PLUGINS="1",
                    OPENCODE_DISABLE_MODELS_FETCH="1",
                    OPENCODE_DISABLE_AUTOUPDATE="1",
                )
                env["PATH"] = (
                    str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
                )
                command = [
                    str(executable()),
                    "run",
                    "--format",
                    "json",
                    "--model",
                    model(),
                    "--dir",
                    str(workspace),
                    "--command",
                    ENTRY_COMMAND,
                    prepared["prompt"],
                ]
                with isolated_command(
                    command, workspace, [port, *prepared.get("ports", [])], protected
                ) as isolated:
                    stdout, stderr, code = run_process(
                        isolated, cwd=workspace, env=env, timeout_s=limits.timeout_s
                    )
                (root / "stdout.jsonl").write_text(stdout)
                (root / "stderr.log").write_text(stderr)
                _stop_process(proxy)
                proxy = None
                trace = root / "api_calls.jsonl"
                errors = refresh_report(report, workspace, trace)
                if version != "v0" and any(
                    e.get("kind") in {"component_error", "policy_violation"}
                    for e in report.get("native_component_events", [])
                ):
                    from harnesslens.harnesses.channel_preflight import (
                        CandidateRuntimeError,
                    )

                    row["candidate_execution_failed"] = True
                    raise CandidateRuntimeError(
                        "Candidate native component failed", root
                    )
                events = (
                    [
                        json.loads(line)
                        for line in trace.read_text().splitlines()
                        if line.strip()
                    ]
                    if trace.is_file()
                    else []
                )
                primary = next(
                    (
                        e.get("session_id")
                        for e in report.get("native_component_events", [])
                        if e.get("kind") == "command_invoked"
                    ),
                    None,
                )
                messages = _messages(events, primary)
                from harnesslens.core.model_trace import tool_call_count

                row["primary_session_id"] = primary
                row.update(
                    messages=messages,
                    n_messages=len(messages),
                    n_tool_calls=sum(
                        tool_call_count(e.get("response")) for e in events
                    ),
                    model_context=report,
                    runtime_load_report=report,
                    api_calls_jsonl=str(trace),
                )
                from harnesslens.evaluation.rollout_outcome import (
                    harness_execution_error,
                )

                if (
                    errors
                    or validate_api_trace(trace)
                    or harness_execution_error(stdout, stderr)
                    or code != 0
                ):
                    raise RuntimeError(
                        "Native runtime did not produce a complete valid execution: "
                        + str(errors or stderr[-500:])
                    )
                if before != _inventory(workspace / "source") or any(
                    not Path(p).is_file() or sha(p) != value
                    for p, value in fixed.items()
                ):
                    raise RuntimeError("Fixed native inputs changed")
                usage = [
                    event.get("usage")
                    for event in events
                    if isinstance(event.get("request"), dict)
                ]
                if not usage or any(
                    not isinstance(u, dict)
                    or type(u.get("total_tokens")) not in (int, float)
                    for u in usage
                ):
                    raise ValueError("Missing solver usage")
                answer_path = workspace / "output/answer.txt"
                answer = (
                    answer_path.read_text()
                    if answer_path.exists()
                    else parse_opencode_text(stdout)
                )
                if not answer.strip():
                    raise ValueError("Empty generated report")
                (root / "answer.txt").write_text(answer)
                row.update(
                    answer=answer,
                    answer_sha256=sha(root / "answer.txt"),
                    api_trace_sha256=sha(trace),
                    usage={
                        "total_tokens": sum(u["total_tokens"] for u in usage),
                        "request_count": len(usage),
                    },
                    solver_elapsed_s=round(time.monotonic() - started, 3),
                )
                write_json(checkpoint, row)
            except Exception as exc:
                row.update(
                    error=f"{type(exc).__name__}: {exc}",
                    termination="infrastructure_error",
                )
                write_json(target, row)
                raise
            finally:
                _stop_process(proxy)
        try:
            if hasattr(adapter, 'grade_for_trial'):
                result = adapter.grade_for_trial(task_id, row["answer"], root)
            else:
                result = adapter.grade(task_id, row["answer"])
            write_json(root / "grading.json", result)
            import math

            if (
                type(result.get("reward")) not in (int, float)
                or not math.isfinite(result["reward"])
                or not 0 <= result["reward"] <= 1
            ):
                raise ValueError("Invalid host reward")
            row.update(
                reward=result["reward"],
                termination="completed",
                infrastructure_error=False,
                verifier_completed=True,
                grading_metrics={
                    k: result[k] for k in ("rs", "primary_metric") if k in result
                },
                grader_diagnostic={
                    "completed": True,
                    "passed": result["reward"] >= 1.0,
                    "validator_sha256": result["validator_sha256"],
                },
            )
            row.pop("error", None)
            write_json(target, row)
            return row
        except Exception as exc:
            row.update(
                error=f"{type(exc).__name__}: {exc}",
                termination="grading_error",
                infrastructure_error=True,
            )
            write_json(target, row)
            raise


def run_batch(
    *,
    adapter,
    run_root,
    scope,
    harness,
    harness_version,
    harness_manifest,
    task_repeats,
    pairing_offsets,
    max_concurrency,
    limits=None,
):
    if harness != "opencode":
        raise ValueError("FDABench native execution uses OpenCode")
    allowed = (
        adapter.split().train
        if scope == "TRAIN"
        else adapter.split().test
        if scope == "TEST"
        else ()
    )
    if (
        not task_repeats
        or set(task_repeats) - set(allowed)
        or any(type(k) is not int or k < 1 for k in task_repeats.values())
    ):
        raise ValueError("Tasks/repeats outside FDABench scope")
    if set(pairing_offsets) - set(task_repeats) or any(
        type(k) is not int or k < 0 for k in pairing_offsets.values()
    ):
        raise ValueError("Invalid pairing offsets")
    signature = adapter.fingerprint()
    limits = limits or adapter.limits()
    output = Path(run_root).resolve()
    from harnesslens.infrastructure.batch_progress import BatchProgress
    progress = BatchProgress(output, scope, harness_version, task_repeats)
    with adapter.execution_context() as resources:

        def execute(tid):
            rows = []
            paths = []
            for trial in range(task_repeats[tid]):
                root = (
                    output
                    / "trials"
                    / stable_hash({"task": tid})
                    / f"trial_{trial:04d}"
                )
                with progress.trial(tid, trial):
                    from harnesslens.harnesses.channel_preflight import CandidateRuntimeError
                    for attempt in range(native_attempts()):
                        try:
                            row = run_trial(adapter, resources, root, tid, trial,
                                            pairing_offsets.get(tid, 0) + trial, scope,
                                            harness_version, harness_manifest, limits, signature)
                            break
                        except CandidateRuntimeError:
                            raise
                        except Exception:
                            if attempt + 1 == native_attempts(): raise
                            time.sleep(min(attempt + 1, 3))
                    rows.append(row)
                    paths.append(str(root / "trial.jsonl"))
            return {
                "task_id": tid,
                "harness_version": harness_version,
                "rewards": [r["reward"] for r in rows],
                "trajectory_paths": paths,
                "worker_errors": [],
                "trial_summaries": [
                    {
                        k: r.get(k)
                        for k in (
                            "trial",
                            "pairing_slot",
                            "reward",
                            "n_messages",
                            "n_tool_calls",
                            "termination",
                            "usage",
                        )
                    }
                    for r in rows
                ],
            }

        with ThreadPoolExecutor(
            max_workers=max(
                1, min(max_concurrency, adapter.max_concurrency, len(task_repeats))
            )
        ) as pool:
            records = list(pool.map(execute, task_repeats))
    if signature != adapter.fingerprint():
        raise RuntimeError("FDABench environment changed")
    return {
        "records": records,
        "per_task": {
            r["task_id"]: {
                "repeats": len(r["rewards"]),
                **{
                    k: r[k]
                    for k in (
                        "rewards",
                        "trajectory_paths",
                        "worker_errors",
                        "trial_summaries",
                    )
                },
            }
            for r in records
        },
        "metrics": {
            **summarize_records(records),
            "primary_metric": adapter.benchmark_config().primary_metric,
        },
    }
