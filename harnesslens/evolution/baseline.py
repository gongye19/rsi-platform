from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from harnesslens.core.artifacts import write_json
from harnesslens.benchmarks.cell_config import benchmark_config
from harnesslens.evaluation.rollout_bridge import RolloutRequest, TrainRolloutService
from harnesslens.benchmarks.task_data import BaselineDataset
from harnesslens.core.train_protocol import (
    MAX_ROLLOUT_CONCURRENCY,
    TRAIN_ROLLOUT_REPEATS,
)
from harnesslens.harnesses.harness_manifest import normalize_harness


BASELINE_FINGERPRINT_SCHEMA = "harnesslens.retail-baseline.v1"

# Exact source transitions whose empty-manifest request/config behavior is covered by
# regression tests. Candidate-only hook support must not invalidate retained v0 trials.
_BASELINE_EQUIVALENT_RUNTIME_HASHES = {
    "harnesslens/harnesses/native_candidate_runtime.py": {
        "0662381e90901111796667e2910f8b8f4ecb994f833870806d1e2cfb50157f0f": "codex-hook-candidate-only-v1",
        "74f449eb9eff2868a5057d14b8a0ab42af3b62945dfec3dfdf7234077c1e88cd": "codex-hook-candidate-only-v1",
    },
}


def build_baseline_fingerprint(
    repo_root: str | Path,
    *,
    cell: str = "fdabench",
    harness: str = "opencode",
    task_ids: Sequence[str] | None = None,
    initial_harness_digest: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    config = benchmark_config(root, cell)
    target_harness = normalize_harness(harness)
    normalized = tuple(str(item) for item in (task_ids or config.train_task_ids))
    files: dict[str, str] = {}
    runtime_files = [*config.runtime_files()]
    for relative in dict.fromkeys(runtime_files):
        path = root / relative
        if not path.is_file():
            raise ValueError(f"baseline runtime file is unavailable: {relative}")
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    rollout = {
        "repeats": TRAIN_ROLLOUT_REPEATS,
        "max_steps": 10,
        "max_turns": 40,
        "max_tool_calls": 60,
        "max_concurrency": MAX_ROLLOUT_CONCURRENCY,
    }
    from harnesslens.benchmarks.adapters import benchmark_adapter
    adapter = benchmark_adapter(root, config.cell)
    extension_fields = adapter.baseline_fields(target_harness) if adapter else {}
    if extension_fields:
        rollout = {"repeats": TRAIN_ROLLOUT_REPEATS, **extension_fields["rollout"]}
    from harnesslens.core.model_config import execution_model
    payload = {
        "schema": f"harnesslens.{config.cell}-baseline.v1",
        "benchmark": config.benchmark,
        "harness": target_harness,
        "target_model": execution_model(),
        "user_model": "openai/deepseek-v4-flash",
        "cell": config.cell,
        "task_ids": list(normalized),
        "task_ids_sha256": hashlib.sha256(
            json.dumps(list(normalized), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "rollout": rollout,
        "seed_protocol": {
            "user_simulator": "sha256(domain\\0task_id\\0pairing_slot)-31bit",
            "target_agent": (
                "sha256(agent\\0benchmark\\0domain\\0task_id\\0pairing_slot)-31bit"
            ),
            "provider_determinism": "best_effort",
        },
        "runtime_file_sha256": files,
    }
    if extension_fields:
        payload.update(extension_fields)
        payload["rollout"] = rollout
    if os.environ.get("HAI_EXECUTION_MODEL") and not extension_fields:
        from harnesslens.core.model_config import connection
        payload["execution_connection"] = {k: v for k, v in connection("execution").items() if k != "api_key"}
    if initial_harness_digest:
        payload["initial_harness_sha256"] = initial_harness_digest
    payload["fingerprint_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def validate_baseline_fingerprint(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    actual = payload.get("baseline_fingerprint")
    if not isinstance(actual, Mapping):
        raise ValueError("baseline event is missing the frozen runtime fingerprint")
    if _semantic_fingerprint(actual) != _semantic_fingerprint(expected):
        raise ValueError("baseline event runtime fingerprint differs from this run")


def _validate_harness_only_reuse(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> Mapping[str, Any]:
    actual = payload.get("baseline_fingerprint")
    if not isinstance(actual, Mapping):
        raise ValueError("baseline event is missing the frozen runtime fingerprint")
    if actual.get("initial_harness_sha256") != expected.get("initial_harness_sha256"):
        raise ValueError("Baseline reuse requires the same initial Harness")
    for field in ("harness", "benchmark", "cell", "target_model", "user_model"):
        if actual.get(field) != expected.get(field):
            raise ValueError(
                f"harness-only baseline reuse requires matching {field}"
            )
    if tuple(actual.get("task_ids") or ()) != tuple(expected.get("task_ids") or ()):
        raise ValueError("harness-only baseline reuse requires the same task split")
    actual_rollout = actual.get("rollout") or {}
    expected_rollout = expected.get("rollout") or {}
    if actual_rollout.get("repeats") != expected_rollout.get("repeats"):
        raise ValueError("harness-only baseline reuse requires matching repeats")
    return actual


def _validate_baseline_runtime(
    payload: Mapping[str, Any], *, expected_trial_count: int
) -> None:
    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping):
        entry = payload.get("agent_workspace_entry")
        metrics = entry.get("metrics") if isinstance(entry, Mapping) else None
    # Legacy and synthetic baseline events predate runtime accounting. They remain
    # eligible through their fingerprint and trajectory validation.
    if not isinstance(metrics, Mapping):
        return

    infrastructure_failures = int(metrics.get("infrastructure_failure_count") or 0)
    worker_errors = int(metrics.get("worker_error_count") or 0)
    charged = metrics.get("charged_trial_count")
    requested = metrics.get("requested_trial_count")
    incomplete = (
        charged is not None and int(charged) != int(expected_trial_count)
    ) or (requested is not None and int(requested) != int(expected_trial_count))
    if infrastructure_failures or worker_errors or incomplete:
        raise ValueError(
            "baseline rollout contains infrastructure failures or incomplete trials: "
            f"expected={expected_trial_count}, requested={requested}, charged={charged}, "
            f"infrastructure_failures={infrastructure_failures}, "
            f"worker_errors={worker_errors}"
        )


def _semantic_fingerprint(fingerprint: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(fingerprint)
    normalized.pop("fingerprint_sha256", None)
    rollout = normalized.get("rollout")
    if isinstance(rollout, Mapping):
        rollout = dict(rollout)
        # Scheduling width does not change task/repeat/seed semantics, and paired
        # candidate comparisons always use one shared current-run width.
        rollout.pop("max_concurrency", None)
        normalized["rollout"] = rollout
    runtime_files = normalized.get("runtime_file_sha256")
    if isinstance(runtime_files, Mapping):
        runtime_files = dict(runtime_files)
        # Baseline orchestration does not affect the generated trajectories. Older
        # Older events included it, so ignore that legacy entry when checking reuse.
        runtime_files.pop("harnesslens/evolution/baseline.py", None)
        runtime_files.pop("harnesslens/evaluation/rollout_bridge.py", None)
        if str(normalized.get("harness") or "") != "codex":
            runtime_files.pop(
                "harnesslens/infrastructure/codex_responses_proxy.py", None
            )
        for path, aliases in _BASELINE_EQUIVALENT_RUNTIME_HASHES.items():
            digest = str(runtime_files.get(path) or "")
            if digest in aliases:
                runtime_files[path] = aliases[digest]
        normalized["runtime_file_sha256"] = runtime_files
    return normalized


def _latest_compatible_baseline(
    *,
    runs_root: Path,
    current_run: Path,
    expected_fingerprint: Mapping[str, Any],
    expected_trial_count: int,
) -> Path | None:
    candidates = sorted(
        runs_root.glob("*/baseline/bootstrap_event.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        if candidate.parent.parent.resolve() == current_run.resolve():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            validate_baseline_fingerprint(payload, expected_fingerprint)
            _validate_baseline_runtime(
                payload, expected_trial_count=expected_trial_count
            )
            BaselineDataset.from_ingest_event(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        return candidate.resolve()
    return None


def ensure_baseline_event(
    *,
    repo_root: str | Path,
    run_root: str | Path,
    baseline_event: str | Path | None,
    cell: str = "fdabench",
    harness: str = "opencode",
    task_ids: Sequence[str] | None = None,
    initial_harness: str | Path | None = None,
) -> Path:
    root = Path(repo_root).resolve()
    run = Path(run_root).resolve()
    config = benchmark_config(repo_root, cell)
    from harnesslens.harnesses.initial_harness import freeze_initial_harness
    initial = freeze_initial_harness(run_root=run, cell=config.cell, harness=harness, source=initial_harness)
    normalized = tuple(str(item) for item in (task_ids or config.train_task_ids))
    expected_fingerprint = build_baseline_fingerprint(
        repo_root,
        cell=config.cell,
        harness=harness,
        task_ids=normalized,
        **({"initial_harness_digest": initial["sha256"]} if initial and not initial["empty"] else {}),
    )
    expected_trial_count = len(normalized) * TRAIN_ROLLOUT_REPEATS
    if baseline_event is not None:
        source = Path(baseline_event).resolve()
        BaselineDataset.from_ingest_event(source)
        payload = json.loads(source.read_text(encoding="utf-8"))
        try:
            validate_baseline_fingerprint(payload, expected_fingerprint)
        except ValueError as exc:
            policy = str(
                os.environ.get("HAI_BASELINE_REUSE_POLICY") or "strict"
            ).strip()
            if (
                str(exc) != "baseline event runtime fingerprint differs from this run"
                or policy != "harness_only"
            ):
                raise
            actual_fingerprint = _validate_harness_only_reuse(
                payload, expected_fingerprint
            )
            write_json(
                run / "baseline" / "reuse.json",
                {
                    "baseline_event": str(source),
                    "policy": "explicit_harness_only_runtime_mismatch",
                    "source_fingerprint_sha256": actual_fingerprint.get(
                        "fingerprint_sha256"
                    ),
                    "expected_fingerprint_sha256": expected_fingerprint.get(
                        "fingerprint_sha256"
                    ),
                },
            )
        _validate_baseline_runtime(payload, expected_trial_count=expected_trial_count)
        return source
    output_path = run / "baseline" / "bootstrap_event.json"
    if output_path.exists():
        BaselineDataset.from_ingest_event(output_path)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        validate_baseline_fingerprint(payload, expected_fingerprint)
        _validate_baseline_runtime(payload, expected_trial_count=expected_trial_count)
        return output_path
    reusable = _latest_compatible_baseline(
        runs_root=root / "runs" / "train",
        current_run=run,
        expected_fingerprint=expected_fingerprint,
        expected_trial_count=expected_trial_count,
    )
    if reusable is not None:
        write_json(
            run / "baseline" / "reuse.json",
            {
                "baseline_event": str(reusable),
                "baseline_fingerprint": expected_fingerprint,
                "policy": "latest_complete_compatible_fresh_baseline",
            },
        )
        return reusable
    expected_tasks = tuple(str(item) for item in config.train_task_ids)
    if len(normalized) != len(expected_tasks) or set(normalized) != set(expected_tasks):
        raise ValueError(
            f"{config.cell} baseline generation requires its complete canonical "
            f"TRAIN split ({len(expected_tasks)} distinct tasks)"
        )
    request_id = f"{run.name}-initial-baseline"
    service = TrainRolloutService(
        cell=config.cell,
        repo_root=root,
        run_id=run.name,
        artifact_root=run / "baseline_rollout_artifacts",
        train_task_ids=list(normalized),
        initial_budget=len(normalized) * TRAIN_ROLLOUT_REPEATS,
        evidence_root=run / "rollout_evidence",
        workspace_root=run / "baseline_rollout_workspaces",
        timeout_s=7200,
        local_rootless_rollout=config.local_rootless_rollout,
        harness=harness,
    )
    os.environ.setdefault("HAI_MIN_FREE_GB", "0")
    os.environ.setdefault("HAI_MIN_MEM_GB", "0")
    response = service.run(
        RolloutRequest(
            request_id=request_id,
            run_id=run.name,
            scope="TRAIN",
            harness_version="v0",
            task_repeats={task_id: TRAIN_ROLLOUT_REPEATS for task_id in normalized},
            max_concurrency=min(
                MAX_ROLLOUT_CONCURRENCY,
                len(normalized) * TRAIN_ROLLOUT_REPEATS,
            ),
            purpose="harnesslens_initial_train_baseline",
            pairing_offsets={task_id: 0 for task_id in normalized},
        )
    )
    if len(response.records) != len(expected_tasks) or any(
        len(record.rewards) != TRAIN_ROLLOUT_REPEATS for record in response.records
    ):
        raise RuntimeError(
            "baseline rollout did not return "
            f"{len(expected_tasks)} tasks x {TRAIN_ROLLOUT_REPEATS} trials"
        )
    trajectories = [
        path for record in response.records for path in record.trajectory_paths
    ]
    entry = _baseline_workspace_entry(
        workspace_root=run / "baseline_workspace",
        request_id=request_id,
        summary_json=response.summary_json,
        metadata_json=response.metadata_json,
        trajectory_paths=trajectories,
        metrics=response.metrics,
    )
    payload = response.to_dict()
    payload["agent_workspace_entry"] = entry
    payload["baseline_creation_accounting"] = {
        "creation_count": len(normalized) * TRAIN_ROLLOUT_REPEATS,
        "ledger_field": "baseline_used",
        "additional_job_charge": 0,
    }
    payload["baseline_fingerprint"] = expected_fingerprint
    _validate_baseline_runtime(payload, expected_trial_count=expected_trial_count)
    write_json(output_path, payload)
    BaselineDataset.from_ingest_event(output_path)
    return output_path


def _baseline_workspace_entry(
    *,
    workspace_root: Path,
    request_id: str,
    summary_json: str,
    metadata_json: str,
    trajectory_paths: Sequence[str],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    workspace_root.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for raw_path in trajectory_paths:
        path = Path(raw_path).resolve()
        content = hashlib.sha256(path.read_bytes())
        sidecars = []
        row = json.loads(path.read_text(encoding="utf-8").strip())
        reference = row.get("api_calls_jsonl") if isinstance(row, Mapping) else None
        if isinstance(reference, str) and reference.strip():
            sidecar = Path(reference)
            if not sidecar.is_absolute():
                sidecar = path.parent / sidecar
            if sidecar.is_file():
                sidecar_digest = hashlib.sha256(sidecar.read_bytes()).hexdigest()
                content.update(sidecar.read_bytes())
                sidecars.append(
                    {"path": str(sidecar.resolve()), "sha256": sidecar_digest}
                )
        digest = content.hexdigest()
        artifacts.append(
            {
                "evidence_id": f"ev_{digest}",
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "content_sha256": digest,
                "sidecars": sidecars,
            }
        )
    entry = {
        "scope": "TRAIN",
        "label": "initial_train_rollouts",
        "request_id": request_id,
        "harness_version": "v0",
        "workspace_dir": str(workspace_root.resolve()),
        "summary_json": str(Path(summary_json).resolve()),
        "metadata_json": str(Path(metadata_json).resolve()),
        "trajectory_paths": [item["path"] for item in artifacts],
        "trajectory_artifacts": artifacts,
        "evidence_ids": [item["evidence_id"] for item in artifacts],
        "metrics": dict(metrics),
        "budget_spent": len(artifacts),
        "budget_remaining": 0,
    }
    write_json(workspace_root / "evidence_manifest.json", {"entries": [entry]})
    return entry
