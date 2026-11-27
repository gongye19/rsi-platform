"""A second benchmark exercises shared orchestration without external benchmark services."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from harnesslens.benchmarks.adapters import benchmark_adapter
from harnesslens.benchmarks.cell_config import benchmark_cell, benchmark_config
from harnesslens.benchmarks.benchmark_splits import load_benchmark_split
from harnesslens.benchmarks.task_data import BaselineDataset, benchmark_task_explorer_input
from harnesslens.evaluation.rollout_bridge import CellHarnessRepository, TrainRolloutService, RolloutRequest
from harnesslens.evaluation.blind_test_eval import BlindTestRolloutService, runtime_limits
from harnesslens.evolution.baseline import build_baseline_fingerprint
from harnesslens.harnesses.channel_preflight import validate_channel_preflight

ROOT = Path(__file__).resolve().parents[1]
CODE = '''import json,urllib.request
def solve(question, harness_files, model_url):
    body={"model":"local-probe","messages":[{"role":"system","content":harness_files["project"]["AGENTS.md"]},{"role":"user","content":question}]}
    with urllib.request.urlopen(urllib.request.Request(model_url,json.dumps(body).encode(),{"Content-Type":"application/json"}),timeout=5) as r:
        result=json.load(r)
    return {"answer":result["choices"][0]["message"]["content"],"usage":result["usage"],
        "messages":[*body["messages"],result["choices"][0]["message"]],"api_calls":[{"request":body,"response":result,"upstream_status":200}]}
'''


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setenv("HAI_BENCHMARK_CONFIG", "")
    monkeypatch.delenv("HAI_AGENT_CONFIG", raising=False)
    name = "qa_" + uuid.uuid4().hex[:12]
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text("".join(json.dumps(row) + "\n" for row in [
        {"id": "train-a", "question": "Compute 2 + 3", "answer": "5", "private": "HIDDEN-ANSWER-FACT"},
        {"id": "train-b", "question": "Compute 4 + 7", "answer": "11"},
        {"id": "heldout", "question": "HELDOUT-QUESTION Compute 8 + 9", "answer": "17"}]))
    spec = tmp_path / "benchmark.toml"
    spec.write_text(f'schema="harnesslens.business-benchmark.v1"\nid="{name}"\ntasks="tasks.jsonl"\n'
                    'train=["train-a","train-b"]\ntest=["heldout"]\npublic_fields=["question"]\n')
    return spec


@pytest.fixture
def business(dataset, tmp_path, monkeypatch, request):
    class Model(BaseHTTPRequestHandler):
        calls = []
        def do_POST(self):
            import re
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            type(self).calls.append(body)
            numbers = re.findall(r"\d+", body["messages"][-1]["content"])
            answer = str(sum(map(int, numbers[-2:])))
            result = {"choices": [{"message": {"role": "assistant", "content": answer}}],
                      "usage": {"total_tokens": 12, "prompt_tokens": 10, "completion_tokens": 2}}
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
        def log_message(self, *_): pass
    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{model.server_address[1]}/v1/chat/completions"
    code = tmp_path / "business"
    code.mkdir()
    (code / "agent.py").write_text(CODE)
    namespace = {}
    exec(CODE, namespace)
    server = None
    transport = request.param
    if transport == "http":
        class Service(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                result = namespace["solve"](**body)
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Service)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        options = f'url="http://127.0.0.1:{server.server_address[1]}/solve"'
        mapping = "body"
    else:
        options = f'function="agent:solve"\npython="{sys.executable}"\npython_paths=["business"]'
        mapping = "arguments"
    config = tmp_path / "agent.toml"
    config.write_text(f'[agent]\ntype="{transport}"\nname="local-probe"\n{options}\ntimeout=10\napi_calls_path="api_calls"\n'
        f'[agent.{mapping}]\nquestion="{{prompt}}"\nharness_files="{{harness_files}}"\nmodel_url="{url}"\n'
        '[capabilities]\nchannels=["instructions_rules"]\n')
    monkeypatch.setenv("HAI_AGENT_CONFIG", str(config))
    try:
        yield Model, config
    finally:
        model.shutdown(); model.server_close()
        if server:
            server.shutdown(); server.server_close()


@pytest.mark.parametrize("business", ["python", "http"], indirect=True)
def test_second_benchmark_train_preflight_test_cache_and_fingerprints(dataset, business, tmp_path):
    model, agent_config = business
    cell = benchmark_cell(str(dataset))
    config = benchmark_config(ROOT, cell)
    assert config.kind == "business_extension"
    split = load_benchmark_split(cell)
    assert split.train == ("train-a", "train-b") and split.test == ("heldout",)
    # Descriptors resolve across process boundaries, without touching optimizer code.
    result = subprocess.check_output([sys.executable, "-c",
        "from harnesslens.benchmarks.cell_config import benchmark_config;import sys;print(benchmark_config(sys.argv[1],sys.argv[2]).cell)",
        str(ROOT), cell], cwd=ROOT, text=True)
    assert result.strip() == cell
    baseline = BaselineDataset(split.train, (), {}, {}, "fixture")
    public = benchmark_task_explorer_input(repo_root=ROOT, baseline=baseline, cell=cell)
    assert "HIDDEN-ANSWER-FACT" not in json.dumps(public)
    assert "HELDOUT-QUESTION" not in json.dumps(public)
    assert build_baseline_fingerprint(ROOT, cell=cell)["target_model"] == "local-probe"
    assert runtime_limits(split)["max_steps"] == 40
    repo = CellHarnessRepository(cell=cell, repo_root=ROOT, run_id="extension", evidence_root=tmp_path / "evidence")
    version = repo.materialize_workspace_candidate(base_version="v0", candidate_label="rule", workspace={"files": [
        {"scope": "project", "path": "AGENTS.md", "content": "GENERIC_RULE_SENTINEL"}]})
    params = dict(cell=cell, repo_root=ROOT, run_id="extension", artifact_root=tmp_path / "artifacts",
                  evidence_root=tmp_path / "evidence", workspace_root=tmp_path / "workspaces", harness="opencode", local_rootless_rollout=False)
    def train():
        return TrainRolloutService(**params, train_task_ids=list(split.train), initial_budget=3)
    req = RolloutRequest("train", "extension", "TRAIN", version, {"train-a": 1}, 1, "synthetic generic adapter test")
    response = train().run(req)
    assert response.records[0].rewards == (1.0,)
    assert "HIDDEN-ANSWER-FACT" not in json.dumps(model.calls)
    assert "HELDOUT-QUESTION" not in json.dumps(model.calls)
    count = len(model.calls)
    assert train().run(req).metrics == response.metrics
    assert train().recover_retained(req) is not None
    assert len(model.calls) == count
    check = validate_channel_preflight(decision={"candidate": {
        "channel_diffs": [{"channel_id": "instructions_rules"}], "workspace_delta": {"files": [
            {"scope": "project", "path": "AGENTS.md", "change": "added", "content": "GENERIC_RULE_SENTINEL"}]}}},
        rollout=response.to_dict(), output_path=tmp_path / "preflight.json")
    assert check["passed"]
    test_service = BlindTestRolloutService(**params, train_task_ids=list(split.test), initial_budget=1)
    test_req = RolloutRequest("test", "extension", "TEST", version, {"heldout": 1}, 1, "synthetic holdout")
    assert test_service.run(test_req).records[0].rewards == (1.0,)
    if agent_config.read_text().startswith('[agent]\ntype="http"'):
        patch = tmp_path / "candidate.json"
        patch.write_text(json.dumps({"instructions": ["GENERIC_CLI_RULE"]}))
        env = {**os.environ, "DEEPSEEK_BASE_URL": "http://127.0.0.1:1/unused",
               "HAI_ANALYSIS_MODEL": "test/unused-analysis", "HAI_ANALYSIS_BASE_URL": "http://127.0.0.1:1/unused",
               "HAI_ANALYSIS_API": "responses", "HAI_ANALYSIS_API_KEY": "local-test-unused"}
        env.pop("DEEPSEEK_API_KEY", None)
        for entry in ("run_test_baseline.py", "run_test_candidate.py"):
            extra = ["--patch-json", str(patch)] if entry == "run_test_candidate.py" else []
            raw = subprocess.check_output([sys.executable, str(ROOT / entry), "--run-id", "cli-probe",
                "--benchmark", str(dataset), "--agent-config", str(agent_config), "--repo-root", str(tmp_path / "cli-root"), *extra],
                cwd=ROOT, env=env, text=True, stderr=subprocess.STDOUT)
            assert json.loads(raw)["metrics"]["trial_success_count"] == 1
    with pytest.raises(ValueError, match="outside"):
        benchmark_adapter(ROOT, cell).run_batch(run_root=tmp_path / "bad", scope="TRAIN", harness="opencode",
            harness_version=version, harness_manifest={}, task_repeats={"heldout": 1}, pairing_offsets={}, max_concurrency=1)
    # Changing source or retained evidence refuses reuse rather than rerunning calls.
    final_count = len(model.calls)
    dataset.write_text(dataset.read_text() + '\nmax_concurrency=1\n')
    with pytest.raises(ValueError, match="environment changed"):
        train().run(req)
    assert len(model.calls) == final_count


def test_host_grader_is_not_delivered_to_business_inputs(dataset, tmp_path):
    grader = tmp_path / "grader.py"
    grader.write_text("def grade(task, answer):\n return float(answer.lower() == task['answer'].lower())\n")
    dataset.write_text(dataset.read_text() + 'grader="python"\ngrader_file="grader.py"\n')
    adapter = benchmark_adapter(ROOT, str(dataset))
    assert adapter.grade("train-a", "5")["reward"] == 1
    workspace = tmp_path / "workspace"; workspace.mkdir()
    prepared = adapter.prepare_task(workspace, "train-a", {})
    assert str(grader) in prepared["private_roots"]
    assert list((workspace / "source").iterdir()) == [workspace / "source/task.json"]
    assert "answer" not in json.loads((workspace / "source/task.json").read_text())


def test_host_grader_timeout_is_an_error_not_a_zero_reward(dataset, tmp_path):
    (tmp_path / "grader.py").write_text("import time\ndef grade(task, answer):\n time.sleep(30)\n return 0\n")
    dataset.write_text(dataset.read_text() + 'grader="python"\ngrader_file="grader.py"\ngrader_timeout=0.05\n')
    adapter = benchmark_adapter(ROOT, str(dataset))
    with pytest.raises(RuntimeError, match="timed out"):
        adapter.grade("train-a", "answer")


@pytest.mark.parametrize("business", ["python", "http"], indirect=True)
def test_initial_harness_baseline_candidate_reuse_and_retained_v0(dataset, business, tmp_path, monkeypatch):
    from harnesslens.evolution.baseline import ensure_baseline_event
    from harnesslens.harnesses.initial_harness import freeze_initial_harness
    from harnesslens.evolution.main_agent import MainAgentModule
    from harnesslens.core.budget import CreationBudget
    from harnesslens.evaluation.blind_test_eval import _load_workspace_submission, run_test_baseline
    model, agent_config = business
    cell = benchmark_cell(str(dataset))
    source = tmp_path / "initial"; source.mkdir()
    original = "INITIAL_RULE_FROM_BUSINESS"
    (source / "AGENTS.md").write_text(original)
    run = tmp_path / "runs/train/initial-probe"
    event = ensure_baseline_event(repo_root=ROOT, run_root=run, baseline_event=None,
        cell=cell, initial_harness=source)
    assert len(model.calls) == 4
    assert all(original in json.dumps(call["messages"]) for call in model.calls)
    baseline = json.loads(event.read_text())
    assert baseline["baseline_fingerprint"]["initial_harness_sha256"]
    count = len(model.calls)
    # Omitting input on restart reuses the frozen baseline and complete traces.
    assert ensure_baseline_event(repo_root=ROOT, run_root=run, baseline_event=None, cell=cell) == event
    assert len(model.calls) == count
    repository = CellHarnessRepository(cell=cell, repo_root=ROOT, run_id=run.name, evidence_root=run / "rollout_evidence")
    child = repository.materialize_candidate(base_version="v0", candidate_label="candidate-01", delta={"instructions": ["CHILD_RULE"]})
    service = TrainRolloutService(cell=cell, repo_root=ROOT, run_id=run.name, artifact_root=run / "rollout_artifacts",
        train_task_ids=["train-a"], initial_budget=1, evidence_root=run / "rollout_evidence", workspace_root=run / "workspaces", local_rootless_rollout=False)
    result = service.run(RolloutRequest("child", run.name, "TRAIN", child, {"train-a": 1}, 1, "candidate inherits initial"))
    assert result.metrics["trial_success_count"] == 1
    assert original in json.dumps(model.calls[-1]) and "CHILD_RULE" in json.dumps(model.calls[-1])
    # Publish the parent after a rejected/no-improvement candidate. TEST loading
    # and a subsequent experiment must retain its actual files, even named v0.
    module = MainAgentModule(repo_root=ROOT, run_root=run, cell=cell,
        budget=CreationBudget(run / "creation_budget.json", total=200, baseline_used=4))
    module.publish_selected(selected_version="v0", iteration_history=[], dispositions_path=run / "dispositions.json")
    final = run / "submission/final.json"
    loaded = _load_workspace_submission(final, repo_root=tmp_path, harness="opencode")
    assert loaded["workspace"] == repository.read_workspace_snapshot("v0")
    package = json.loads(final.read_text())["harness_package"]["path"]
    imported = freeze_initial_harness(run_root=tmp_path / "runs/train/next", cell=cell, source=package)
    assert imported["workspace"] == loaded["workspace"]
    holdout = run_test_baseline(repo_root=tmp_path, run_id="initial-holdout", benchmark=cell, repeats=1, initial_harness=source)
    assert holdout.response.metrics["trial_success_count"] == 1
    assert original in json.dumps(model.calls[-1])
    (source / "AGENTS.md").write_text("DIFFERENT_INITIAL_RULE")
    for policy in ("strict", "harness_only"):
        monkeypatch.setenv("HAI_BASELINE_REUSE_POLICY", policy)
        with pytest.raises(ValueError, match="fingerprint|initial Harness"):
            ensure_baseline_event(repo_root=ROOT, run_root=tmp_path / ("changed-" + policy), baseline_event=event,
                cell=cell, initial_harness=source)
    assert (source / "AGENTS.md").read_text() == "DIFFERENT_INITIAL_RULE"
