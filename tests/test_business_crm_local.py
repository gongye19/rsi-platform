"""Opt-in CRM plumbing tests: real adapters/databases, synthetic local model."""
import json
import os
from pathlib import Path
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from harnesslens.harnesses.business_agent import load_config, select_config
from harnesslens.evaluation.rollout_bridge import TrainRolloutService, CellHarnessRepository, RolloutRequest
from harnesslens.harnesses.channel_preflight import validate_channel_preflight

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get("HAI_RUN_CRM_BUSINESS_PROBE") != "1", reason="opt in to real CRM local service tests")


CODE = '''import json, urllib.request, subprocess, sys
def solve(question, harness_files, model_url, request_id):
    schema = subprocess.check_output([sys.executable, "source/query.py", "schema", "core_crm"], text=True)
    request = {"model":"synthetic-local-model", "messages":[
        {"role":"system", "content":harness_files["project"]["AGENTS.md"]}, {"role":"user","content":question},
        {"role":"tool","content":schema}]}
    req = urllib.request.Request(model_url, json.dumps(request).encode(), {"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        result = json.load(response)
    return {"answer":result["choices"][0]["message"]["content"], "usage":result["usage"],
        "messages":[*request["messages"], result["choices"][0]["message"]],
        "api_calls":[{"request":request,"response":result,"usage":result["usage"],"upstream_status":200}],
        "request_id":request_id}
'''


class Model(BaseHTTPRequestHandler):
    calls = []
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append(body)
        response = {"choices": [{"message": {"role": "assistant", "content": "Authority"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())
    def log_message(self, *_):
        pass


@pytest.mark.parametrize("transport", ["python", "http"])
def test_crm_python_and_http_candidate_execution_cache_and_preflight(tmp_path, monkeypatch, transport):
    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    thread = threading.Thread(target=model.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{model.server_address[1]}/chat/completions"
    code = tmp_path / "business"
    code.mkdir()
    (code / "fixture_agent.py").write_text(CODE)
    namespace = {}
    exec(CODE, namespace)
    business = None
    if transport == "http":
        class Business(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                # The local server acts like a service with existing task tools.
                import urllib.request
                request = {"model": "synthetic-local-model", "messages": [
                    {"role": "system", "content": body["harness_files"]["project"]["AGENTS.md"]},
                    {"role": "user", "content": body["question"]}]}
                with urllib.request.urlopen(urllib.request.Request(url, json.dumps(request).encode(),
                    {"Content-Type": "application/json"}), timeout=5) as response:
                    result = json.load(response)
                answer = {"answer": result["choices"][0]["message"]["content"], "usage": result["usage"],
                          "messages": [*request["messages"], result["choices"][0]["message"]],
                          "api_calls": [{"request": request, "response": result, "upstream_status": 200}]}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(answer).encode())
            def log_message(self, *_):
                pass
        business = ThreadingHTTPServer(("127.0.0.1", 0), Business)
        threading.Thread(target=business.serve_forever, daemon=True).start()
    path = tmp_path / "agent.toml"
    options = (f'function="fixture_agent:solve"\npython="{sys.executable}"\npython_paths=["business"]' if transport == "python"
               else f'url="http://127.0.0.1:{business.server_address[1]}/solve"')
    mapping = "arguments" if transport == "python" else "body"
    path.write_text(f'''[agent]
type="{transport}"
name="synthetic-local-{transport}"
{options}
timeout=10
api_calls_path="api_calls"
[agent.{mapping}]
question="{{prompt}}"
harness_files="{{harness_files}}"
model_url="{url}"
request_id="{{request_id}}"
[capabilities]
channels=["instructions_rules"]
''')
    monkeypatch.setenv("HAI_AGENT_CONFIG", str(path))
    run_id = f"business-{transport}-{uuid.uuid4().hex[:8]}"
    root = ROOT / "runs/business_integration" / run_id
    repo = CellHarnessRepository(cell="crmarenapro", repo_root=ROOT, run_id=run_id, evidence_root=root / "evidence")
    version = repo.materialize_workspace_candidate(base_version="v0", candidate_label="candidate", workspace={"files": [
        {"scope": "project", "path": "AGENTS.md", "content": "BUSINESS_ADAPTER_SENTINEL"}]})
    def service():
        return TrainRolloutService(cell="crmarenapro", repo_root=ROOT, run_id=run_id,
            artifact_root=root / "artifacts", train_task_ids=["crmarenapro/query1"], initial_budget=1,
            evidence_root=root / "evidence", workspace_root=root / "workspaces", local_rootless_rollout=False)
    request = RolloutRequest("probe", run_id, "TRAIN", version, {"crmarenapro/query1": 1}, 1, "synthetic local transport test")
    try:
        response = service().run(request)
        assert response.metrics["trial_success_count"] == 1
        assert response.records[0].trial_summaries[0]["usage"]["total_tokens"] == 12
        report = validate_channel_preflight(decision={"harness_version": version, "candidate": {
            "channel_diffs": [{"channel_id": "instructions_rules"}],
            "workspace_delta": {"files": [{"scope": "project", "path": "AGENTS.md", "change": "added", "content": "BUSINESS_ADAPTER_SENTINEL"}]}}},
            rollout=response.to_dict(), output_path=root / "preflight.json")
        assert report["passed"]
        count = len(Model.calls)
        assert service().run(request).metrics == response.metrics
        assert len(Model.calls) == count
        assert service().recover_retained(request).records[0].task_id == "crmarenapro/query1"
        (root / "test_result.json").write_text(json.dumps({"synthetic_model": True, "performance_claim": False,
            "transport": transport, "preflight_passed": True, "cache_verified": True}))
    finally:
        model.shutdown()
        model.server_close()
        thread.join()
        if business:
            business.shutdown()
            business.server_close()
