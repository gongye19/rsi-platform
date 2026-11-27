import json
import os
import uuid
from pathlib import Path

import pytest

from harnesslens.benchmarks.cell_config import benchmark_config
from harnesslens.benchmarks.task_data import (
    BaselineDataset,
    benchmark_task_explorer_input,
)
from harnesslens.evolution.baseline import (
    _semantic_fingerprint,
    _validate_baseline_runtime,
    build_baseline_fingerprint,
    ensure_baseline_event,
)


TASK_COUNT = 30


def _paired_artifacts(root: Path):
    artifacts = []
    for task in range(TASK_COUNT):
        for trial in range(2):
            path = root / f"{task}-{trial}.jsonl"
            path.write_text(json.dumps({"task_id": str(task), "trial": trial}) + "\n")
            artifacts.append({"path": str(path), "evidence_id": f"ev_{task}_{trial}"})
    return artifacts


def test_baseline_dataset_requires_thirty_paired_tasks(tmp_path):
    event = tmp_path / "output.json"
    event.write_text(
        json.dumps(
            {"agent_workspace_entry": {"trajectory_artifacts": _paired_artifacts(tmp_path)}}
        )
    )

    baseline = BaselineDataset.from_ingest_event(event)

    assert len(baseline.task_ids) == 30
    assert all(len(paths) == 2 for paths in baseline.trajectories_by_task.values())


def test_baseline_runtime_rejects_infrastructure_only_completion():
    payload = {
        "metrics": {
            "requested_trial_count": 30,
            "charged_trial_count": 0,
            "infrastructure_failure_count": 30,
            "worker_error_count": 30,
        }
    }

    with pytest.raises(ValueError, match="infrastructure failures"):
        _validate_baseline_runtime(payload, expected_trial_count=30)


def test_baseline_runtime_accepts_complete_charged_trials():
    payload = {
        "metrics": {
            "requested_trial_count": 30,
            "charged_trial_count": 30,
            "infrastructure_failure_count": 0,
            "worker_error_count": 0,
        }
    }

    _validate_baseline_runtime(payload, expected_trial_count=30)


def test_baseline_dataset_rejects_unpaired_tasks(tmp_path):
    path = tmp_path / "one.jsonl"
    path.write_text(json.dumps({"task_id": "1"}) + "\n")
    event = tmp_path / "output.json"
    event.write_text(
        json.dumps(
            {
                "agent_workspace_entry": {
                    "trajectory_artifacts": [{"path": str(path), "evidence_id": "ev_1"}]
                }
            }
        )
    )

    with pytest.raises(ValueError, match="30 tasks x 2"):
        BaselineDataset.from_ingest_event(event)


def test_cached_baseline_is_validated_without_rollout(business_benchmark, tmp_path):
    root, cell = business_benchmark
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "agent_workspace_entry": {"trajectory_artifacts": _paired_artifacts(tmp_path)},
                "baseline_fingerprint": build_baseline_fingerprint(
                    root,
                    cell=cell,
                    task_ids=tuple(str(task) for task in range(TASK_COUNT)),
                ),
            }
        )
    )

    selected = ensure_baseline_event(
        repo_root=root,
        run_root=tmp_path / "run",
        baseline_event=event,
        cell=cell,
        task_ids=tuple(str(task) for task in range(TASK_COUNT)),
    )

    assert selected == event.resolve()


def test_cached_baseline_rejects_runtime_drift(business_benchmark, tmp_path):
    root, cell = business_benchmark
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "agent_workspace_entry": {"trajectory_artifacts": _paired_artifacts(tmp_path)},
                "baseline_fingerprint": build_baseline_fingerprint(
                    root,
                    cell=cell,
                    task_ids=tuple(str(task) for task in range(TASK_COUNT)),
                ),
            }
        )
    )
    changed = tmp_path / "harnesslens/harnesses/harness_workspace.py"
    changed.write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="fingerprint differs"):
        ensure_baseline_event(
            repo_root=root,
            run_root=tmp_path / "run",
            baseline_event=event,
            cell=cell,
            task_ids=tuple(str(task) for task in range(TASK_COUNT)),
        )


def test_cached_baseline_explicitly_reuses_same_harness_after_runtime_drift(
    business_benchmark, tmp_path, monkeypatch
):
    root, cell = business_benchmark
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "agent_workspace_entry": {"trajectory_artifacts": _paired_artifacts(tmp_path)},
                "baseline_fingerprint": build_baseline_fingerprint(
                    root,
                    cell=cell,
                    task_ids=tuple(str(task) for task in range(TASK_COUNT)),
                ),
            }
        )
    )
    changed = tmp_path / "harnesslens/harnesses/harness_workspace.py"
    changed.write_text("changed", encoding="utf-8")
    monkeypatch.setenv("HAI_BASELINE_REUSE_POLICY", "harness_only")
    run_root = tmp_path / "run"

    selected = ensure_baseline_event(
        repo_root=root,
        run_root=run_root,
        baseline_event=event,
        cell=cell,
        task_ids=tuple(str(task) for task in range(TASK_COUNT)),
    )

    assert selected == event.resolve()
    reuse = json.loads((run_root / "baseline" / "reuse.json").read_text())
    assert reuse["policy"] == "explicit_harness_only_runtime_mismatch"
    assert reuse["baseline_event"] == str(event.resolve())


def test_harness_only_baseline_reuse_rejects_another_harness(
    business_benchmark, tmp_path, monkeypatch
):
    root, cell = business_benchmark
    # business_extension 只支持 opencode；直接改写指纹的 harness 字段
    # 来覆盖 harness_only 复用的 harness 校验分支。
    fingerprint = build_baseline_fingerprint(
        root,
        cell=cell,
        task_ids=tuple(str(task) for task in range(TASK_COUNT)),
    )
    fingerprint["harness"] = "pi"
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "agent_workspace_entry": {"trajectory_artifacts": _paired_artifacts(tmp_path)},
                "baseline_fingerprint": fingerprint,
            }
        )
    )
    monkeypatch.setenv("HAI_BASELINE_REUSE_POLICY", "harness_only")

    with pytest.raises(ValueError, match="matching harness"):
        ensure_baseline_event(
            repo_root=root,
            run_root=tmp_path / "run",
            baseline_event=event,
            cell=cell,
            harness="opencode",
            task_ids=tuple(str(task) for task in range(TASK_COUNT)),
        )


def test_cached_baseline_allows_orchestration_only_drift(business_benchmark, tmp_path):
    root, cell = business_benchmark
    fingerprint = build_baseline_fingerprint(
        root,
        cell=cell,
        task_ids=tuple(str(task) for task in range(TASK_COUNT)),
    )
    fingerprint["runtime_file_sha256"][
        "harnesslens/evolution/baseline.py"
    ] = "legacy-orchestration-hash"
    fingerprint["runtime_file_sha256"][
        "harnesslens/evaluation/rollout_bridge.py"
    ] = "legacy-bridge-orchestration-hash"
    fingerprint["fingerprint_sha256"] = "legacy-full-hash"
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "agent_workspace_entry": {"trajectory_artifacts": _paired_artifacts(tmp_path)},
                "baseline_fingerprint": fingerprint,
            }
        )
    )

    selected = ensure_baseline_event(
        repo_root=root,
        run_root=tmp_path / "run",
        baseline_event=event,
        cell=cell,
        task_ids=tuple(str(task) for task in range(TASK_COUNT)),
    )

    assert selected == event.resolve()


@pytest.mark.parametrize(
    ("path", "old_digest", "new_digest"),
    [
        (
            "harnesslens/harnesses/native_candidate_runtime.py",
            "0662381e90901111796667e2910f8b8f4ecb994f833870806d1e2cfb50157f0f",
            "74f449eb9eff2868a5057d14b8a0ab42af3b62945dfec3dfdf7234077c1e88cd",
        ),
    ],
)
def test_baseline_allows_only_audited_candidate_runtime_transition(
    path, old_digest, new_digest
):
    old = _semantic_fingerprint({"runtime_file_sha256": {path: old_digest}})
    new = _semantic_fingerprint({"runtime_file_sha256": {path: new_digest}})
    unknown = _semantic_fingerprint({"runtime_file_sha256": {path: "unknown-drift"}})

    assert old == new
    assert unknown != new


def test_baseline_semantics_ignore_only_rollout_scheduling_width():
    old = _semantic_fingerprint(
        {"rollout": {"repeats": 2, "max_steps": 30, "max_concurrency": 20}}
    )
    new = _semantic_fingerprint(
        {"rollout": {"repeats": 2, "max_steps": 30, "max_concurrency": 2}}
    )
    changed_limit = _semantic_fingerprint(
        {"rollout": {"repeats": 2, "max_steps": 31, "max_concurrency": 2}}
    )

    assert old == new
    assert changed_limit != new


def test_uses_latest_complete_compatible_fresh_baseline(business_benchmark, tmp_path):
    root, cell = business_benchmark
    fingerprint = build_baseline_fingerprint(
        root,
        cell=cell,
        task_ids=tuple(str(task) for task in range(TASK_COUNT)),
    )
    runs_root = tmp_path / "runs" / "train"
    events = []
    for index in range(2):
        artifact_root = tmp_path / f"artifacts-{index}"
        artifact_root.mkdir()
        artifacts = []
        for task in range(TASK_COUNT):
            for trial in range(2):
                path = artifact_root / f"{task}-{trial}.jsonl"
                path.write_text(
                    json.dumps({"task_id": str(task), "trial": trial}) + "\n"
                )
                artifacts.append(
                    {"path": str(path), "evidence_id": f"ev_{index}_{task}_{trial}"}
                )
        event = runs_root / f"old-{index}" / "baseline" / "bootstrap_event.json"
        event.parent.mkdir(parents=True)
        event.write_text(
            json.dumps(
                {
                    "agent_workspace_entry": {"trajectory_artifacts": artifacts},
                    "baseline_fingerprint": fingerprint,
                }
            )
        )
        os.utime(event, (index + 1, index + 1))
        events.append(event)

    run_root = runs_root / "current"
    selected = ensure_baseline_event(
        repo_root=root,
        run_root=run_root,
        baseline_event=None,
        cell=cell,
        task_ids=tuple(str(task) for task in range(TASK_COUNT)),
    )

    assert selected == events[-1].resolve()
    reuse = json.loads((run_root / "baseline" / "reuse.json").read_text())
    assert reuse["baseline_event"] == str(events[-1].resolve())


def test_run_local_cached_baseline_rejects_runtime_drift(business_benchmark, tmp_path):
    root, cell = business_benchmark
    run_root = tmp_path / "run"
    event = run_root / "baseline" / "bootstrap_event.json"
    event.parent.mkdir(parents=True)
    event.write_text(
        json.dumps(
            {
                "agent_workspace_entry": {"trajectory_artifacts": _paired_artifacts(tmp_path)},
                "baseline_fingerprint": build_baseline_fingerprint(
                    root,
                    cell=cell,
                    task_ids=tuple(str(task) for task in range(TASK_COUNT)),
                ),
            }
        )
    )
    changed = tmp_path / "harnesslens/harnesses/harness_workspace.py"
    changed.write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="fingerprint differs"):
        ensure_baseline_event(
            repo_root=root,
            run_root=run_root,
            baseline_event=None,
            cell=cell,
            task_ids=tuple(str(task) for task in range(TASK_COUNT)),
        )


def test_business_explorer_input_stays_train_only_and_private_free(business_benchmark):
    root, cell = business_benchmark
    baseline = BaselineDataset(
        tuple(f"task-{index}" for index in range(TASK_COUNT)),
        (),
        {},
        {},
        "event.json",
    )

    payload = benchmark_task_explorer_input(
        repo_root=root,
        baseline=baseline,
        cell=cell,
    )

    assert payload["benchmark_kind"] == "business_extension"
    assert payload["cell"] == cell
    assert len(payload["tasks"]) == TASK_COUNT
    assert "answer" not in json.dumps(payload["tasks"][0])
