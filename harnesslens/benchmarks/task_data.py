from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from harnesslens.benchmarks.cell_config import benchmark_config
from harnesslens.core.train_protocol import TRAIN_ROLLOUT_REPEATS


@dataclass(frozen=True)
class BaselineDataset:
    task_ids: tuple[str, ...]
    trajectory_paths: tuple[str, ...]
    trajectories_by_task: Mapping[str, tuple[str, ...]]
    evidence_by_path: Mapping[str, str]
    source_event: str

    @classmethod
    def from_ingest_event(cls, path: str | Path) -> "BaselineDataset":
        source = Path(path).resolve()
        payload = json.loads(source.read_text(encoding="utf-8"))
        entry = payload.get("agent_workspace_entry")
        if not isinstance(entry, Mapping):
            raise ValueError("baseline event is missing agent_workspace_entry")
        artifacts = entry.get("trajectory_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("baseline event has no retained trajectories")
        grouped: dict[str, list[str]] = {}
        evidence_by_path: dict[str, str] = {}
        ordered_paths: list[str] = []
        for artifact in artifacts:
            trajectory_path = Path(str((artifact or {}).get("path") or ""))
            if not trajectory_path.is_file():
                raise ValueError(f"baseline trajectory is unavailable: {trajectory_path}")
            rows = [
                json.loads(line)
                for line in trajectory_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if line.strip()
            ]
            if len(rows) != 1 or not isinstance(rows[0], Mapping):
                raise ValueError(f"baseline artifact must contain one trial: {trajectory_path}")
            task_id = str(rows[0].get("task_id") or "").strip()
            if not task_id:
                raise ValueError(f"baseline trajectory has no task_id: {trajectory_path}")
            resolved = str(trajectory_path.resolve())
            grouped.setdefault(task_id, []).append(resolved)
            evidence_id = str((artifact or {}).get("evidence_id") or "").strip()
            if not evidence_id:
                raise ValueError(f"baseline artifact has no evidence_id: {trajectory_path}")
            evidence_by_path[resolved] = evidence_id
            ordered_paths.append(resolved)
        fingerprint = payload.get("baseline_fingerprint") or {}
        expected_task_ids = tuple(
            str(item) for item in (fingerprint.get("task_ids") or ())
        )
        expected_task_count = len(expected_task_ids) if expected_task_ids else 30
        if len(grouped) != expected_task_count or any(
            len(paths) != TRAIN_ROLLOUT_REPEATS for paths in grouped.values()
        ):
            raise ValueError(
                "compatible baseline must contain "
                f"{expected_task_count} tasks x {TRAIN_ROLLOUT_REPEATS} trials"
            )
        if expected_task_ids and set(grouped) != set(expected_task_ids):
            raise ValueError("baseline task IDs do not match its fingerprint")
        return cls(
            task_ids=tuple(grouped),
            trajectory_paths=tuple(ordered_paths),
            trajectories_by_task={key: tuple(value) for key, value in grouped.items()},
            evidence_by_path=evidence_by_path,
            source_event=str(source),
        )


def benchmark_task_explorer_input(
    *,
    repo_root: str | Path,
    baseline: BaselineDataset,
    cell: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    config = benchmark_config(root, cell)
    from harnesslens.benchmarks.adapters import benchmark_adapter
    adapter = benchmark_adapter(root, config.cell)
    if adapter:
        payload = adapter.explorer_input(baseline.task_ids)
    else:
        raise ValueError(f"unsupported benchmark kind: {config.kind}")
    payload["evaluation_contract"] = evaluation_contract(config.outcome_authority)
    payload["evaluation_contract"]["primary_metric"] = config.primary_metric
    if config.primary_metric == "mean_reward":
        payload["evaluation_contract"]["score_interpretation"] = "Continuous reward [0,1]; compare paired mean rewards. Pass counts measure only perfect answers. Partial score gains require attributable behavioral evidence."
    # Native tool surfaces come from retained TRAIN requests, not assumptions
    # about a benchmark's name or the CLI used inside its tools.
    observed = {}
    for reference in baseline.trajectory_paths:
        trajectory = Path(reference)
        for line in trajectory.read_text().splitlines():
            if not line.strip(): continue
            row = json.loads(line)
            trace_name = row.get("api_calls_jsonl")
            if not trace_name: continue
            trace = Path(trace_name)
            if not trace.is_absolute(): trace = trajectory.parent / trace
            if not trace.is_file(): continue
            for raw in trace.read_text().splitlines():
                if not raw.strip(): continue
                event = json.loads(raw)
                for tool in (event.get("request") or {}).get("tools", []):
                    value = tool.get("function", tool)
                    if isinstance(value, Mapping) and value.get("name"):
                        observed[str(value["name"])] = {key: value[key] for key in ("name", "description", "parameters", "inputSchema") if key in value}
    if observed:
        payload.setdefault("environment", {})["native_tools"] = list(observed.values())
    return payload


def _normalized_query(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        return {"instruction": value}
    if value is None:
        return {}
    return {"instruction": str(value)}


def evaluation_contract(outcome_authority: str) -> dict[str, str]:
    authority = str(outcome_authority)
    if authority == "authoritative":
        interpretation = (
            "Recorded pass/fail is authoritative for task completion. Trajectories "
            "explain the mechanism but cannot relabel a failed trial as successful."
        )
    elif authority == "behavioral":
        interpretation = (
            "Recorded pass/fail is supporting whole-task metadata. Preserve explicit "
            "visible completion disagreements for downstream review."
        )
    else:
        raise ValueError(f"unsupported outcome authority: {authority}")
    return {
        "outcome_authority": authority,
        "interpretation": interpretation,
    }
