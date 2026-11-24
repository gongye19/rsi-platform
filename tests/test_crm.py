import json
from pathlib import Path

import pytest

from harnesslens.benchmarks.benchmark_splits import load_benchmark_split
from harnesslens.benchmarks.cell_config import benchmark_config
from harnesslens.benchmarks.crm import TASK_IDS, public_explorer_input, load_tasks, grade
from harnesslens.benchmarks.crm_eval import CrmLimits, prepare_harness, _validate_manifest, run_crm_batch, _messages
from harnesslens.benchmarks.task_data import BaselineDataset, benchmark_task_explorer_input
from harnesslens.harnesses.native_candidate_runtime import attach_candidate_workspace
from harnesslens.evaluation.rollout_bridge import TrainRolloutService, RolloutRequest, CellHarnessRepository

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data(tmp_path, monkeypatch):
    checkout = tmp_path / "dab"
    root = checkout / "query_crmarenapro"
    root.mkdir(parents=True)
    (root / "db_description.txt").write_text("Six database descriptions")
    for i in range(1, 14):
        directory = root / f"query{i}"
        directory.mkdir()
        (directory / "query.json").write_text(json.dumps(f"Public question {i}"))
        (directory / "validate.py").write_text("def validate(answer):\n return answer == 'private-answer', 'diagnostic'\n")
        (directory / "ground_truth.csv").write_text("private-answer")
    monkeypatch.setenv("HAI_DAB_ROOT", str(checkout))
    return root


def test_crm_split_reuses_exact_10_train_3_test_protocol():
    split = load_benchmark_split("crm")
    assert split.train == TASK_IDS[:10]
    assert split.test == TASK_IDS[10:]
    assert benchmark_config(ROOT, "crm").train_task_ids == split.train
    assert benchmark_config(ROOT, "dab-crmarenapro").outcome_authority == "authoritative"


def test_public_task_exploration_hides_test_questions_and_grading(data):
    split = load_benchmark_split("crm")
    baseline = BaselineDataset(split.train, (), {}, {}, "fixture")
    payload = benchmark_task_explorer_input(repo_root=ROOT, baseline=baseline, cell="crm")
    text = json.dumps(payload)
    assert "Public question 1" in text
    assert "Public question 11" not in text
    assert "private-answer" not in text
    assert len(payload["tasks"]) == 10
    assert payload["evaluation_contract"]["outcome_authority"] == "authoritative"


def test_official_grader_runs_host_side(data):
    assert grade(ROOT, TASK_IDS[0], "private-answer")["reward"] == 1
    assert grade(ROOT, TASK_IDS[0], "wrong")["reward"] == 0


def test_candidate_instructions_and_skills_materialize_with_fixed_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("HAI_CRM_MODEL", "crm/glm-5.2")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = attach_candidate_workspace({"instructions": ["always-check"], "prompt_appends": ["append-check"]}, {
        "files": [
            {"scope": "project", "path": "AGENTS.md", "content": "instruction-sentinel"},
            {"scope": "project", "path": ".opencode/skills/probe/SKILL.md", "content": "---\nname: probe\ndescription: Probe skill\n---\nRun checks."},
            {"scope": "project", "path": "opencode.json", "content": json.dumps({"agent": {"build": {"prompt": "system-sentinel"}}})},
        ]})
    home, config, report = prepare_harness(tmp_path, manifest, 12345, CrmLimits())
    assert "always-check" in (workspace / "AGENTS.md").read_text()
    assert "append-check" in (workspace / "AGENTS.md").read_text()
    assert config["model"] == "crm/glm-5.2"
    assert config["agent"]["build"]["steps"] == 40
    assert config["agent"]["build"]["prompt"] == "system-sentinel"
    assert config["mcp"] == {}
    assert config["permission"]["webfetch"] == "deny"
    assert report["skills_available"][0]["name"] == "probe"


@pytest.mark.parametrize("path", ["source/task.json", "output/answer.txt", "../escape", "/tmp/escape", ".runtime/harnesslens/bridge.mjs"])
def test_protected_candidate_files_are_rejected(path):
    with pytest.raises(ValueError):
        _validate_manifest({"_workspace": {"files": [{"scope": "project", "path": path, "content": "bad"}]}})


def test_crm_scope_rejected_before_any_database_or_model_access():
    with pytest.raises(ValueError, match="outside"):
        run_crm_batch(repo_root=ROOT, run_root=ROOT / "runs/unused", scope="TRAIN", harness="opencode",
            harness_version="v0", harness_manifest={}, task_repeats={TASK_IDS[-1]: 1},
            pairing_offsets={}, max_concurrency=1)


def test_message_normalization_preserves_calls_and_observations():
    raw = [{"request": {"messages": [{"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "bash", "arguments": "{}"}}]}, {"role": "tool", "content": "result"}]},
            "response": {"choices": [{"message": {"role": "assistant", "content": "answer"}}]}}]
    messages = _messages(raw)
    assert messages[0]["tool_calls"][0]["name"] == "bash"
    assert messages[1]["content"] == "result"
    assert messages[-1]["content"] == "answer"


def test_main_trace_is_not_replaced_by_late_title_or_other_subagent():
    def event(session, agent, answer):
        return {"session_id": session, "agent_name": agent, "request": {"messages": [{"role": "user", "content": agent}]},
                "response": {"choices": [{"message": {"role": "assistant", "content": answer}}]}}
    events = [event("parent", "build", "main answer"), event("child", "worker", "child answer"), event("parent", "title", "session title")]
    assert _messages(events, "parent")[-1]["content"] == "main answer"


def test_train_rollout_routes_candidate_to_crm_adapter(tmp_path, monkeypatch):
    seen = {}
    def fake(**kwargs):
        seen.update(kwargs)
        return {"records": []}
    monkeypatch.setattr("harnesslens.benchmarks.crm_eval.run_crm_batch", fake)
    repository = CellHarnessRepository(cell="crmarenapro", repo_root=ROOT, run_id="run", evidence_root=tmp_path / "evidence")
    version = repository.materialize_workspace_candidate(base_version="v0", candidate_label="candidate", workspace={"files": [{"scope": "project", "path": "AGENTS.md", "content": "sentinel"}]})
    service = TrainRolloutService(cell="crmarenapro", repo_root=ROOT, run_id="run", artifact_root=tmp_path / "artifacts",
        train_task_ids=list(TASK_IDS[:10]), initial_budget=20, evidence_root=tmp_path / "evidence", workspace_root=tmp_path / "workspaces")
    req = RolloutRequest("request", "run", "TRAIN", version, {TASK_IDS[0]: 2}, 1, "test", {TASK_IDS[0]: 4})
    service._run_group(req, [TASK_IDS[0]], 2)
    assert seen["pairing_offsets"] == {TASK_IDS[0]: 4}
    assert seen["harness_manifest"]["_workspace"]["files"][0]["content"] == "sentinel"


def test_crm_rejects_unsupported_runtime(tmp_path):
    with pytest.raises(ValueError, match="OpenCode only"):
        TrainRolloutService(cell="crmarenapro", repo_root=ROOT, run_id="r", artifact_root=tmp_path,
            train_task_ids=list(TASK_IDS[:10]), initial_budget=20, evidence_root=tmp_path, workspace_root=tmp_path, harness="pi")


def test_glm_provider_endpoint_does_not_duplicate_v1(monkeypatch):
    from harnesslens.infrastructure.chat_completions_proxy import _upstream_url
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    assert _upstream_url("/v1/chat/completions") == "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"


def test_crm_cache_and_recovery_validate_environment_and_slash_ids(tmp_path, monkeypatch):
    from harnesslens.benchmarks.crm import sha
    signature = {"fixture": "frozen"}
    monkeypatch.setattr("harnesslens.benchmarks.crm_eval.runtime_fingerprint", lambda root: signature)
    source = tmp_path / "original"
    source.mkdir()
    trace = source / "api_calls.jsonl"
    trace.write_text(json.dumps({"request": {}, "response": {}, "upstream_status": 200}) + "\n")
    row = {"task_id": TASK_IDS[0], "trial": 0, "reward": 1, "api_calls_jsonl": str(trace),
           "environment_fingerprint": dict(signature), "api_trace_sha256": sha(trace)}
    path = source / "trial.jsonl"
    path.write_text(json.dumps(row) + "\n")
    calls = []
    def fake(self, *args):
        calls.append(1)
        return {"records": [{"task_id": TASK_IDS[0], "harness_version": "v0", "rewards": [1], "trajectory_paths": [str(path)]}],
                "per_task": {TASK_IDS[0]: {"repeats": 1}}}
    monkeypatch.setattr(TrainRolloutService, "_run_group", fake)
    def service():
        return TrainRolloutService(cell="crmarenapro", repo_root=ROOT, run_id="run", artifact_root=tmp_path / "artifacts",
            train_task_ids=[TASK_IDS[0]], initial_budget=1, evidence_root=tmp_path / "evidence", workspace_root=tmp_path / "workspaces")
    req = RolloutRequest("request", "run", "TRAIN", "v0", {TASK_IDS[0]: 1}, 1, "cache test")
    assert service().run(req).metrics["trial_success_count"] == 1
    assert service().run(req).metrics["trial_success_count"] == 1
    assert len(calls) == 1
    assert service().recover_retained(req).records[0].task_id == TASK_IDS[0]
    signature["fixture"] = "changed"
    with pytest.raises(ValueError, match="environment changed"):
        service().run(req)
