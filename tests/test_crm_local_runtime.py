"""Real OpenCode + real CRM databases, with a local synthetic model response.

This checks execution and candidate delivery, never optimization performance.
"""
import json
import os
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from harnesslens.core.config import load_repo_env
from harnesslens.evaluation.rollout_bridge import TrainRolloutService, RolloutRequest, CellHarnessRepository

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get("HAI_RUN_CRM_LOCAL_PROBE") != "1",
                              reason="opt in to the local CRM database/runtime probe")


class Handler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append(body)
        text = json.dumps(body.get("messages", []))
        tool_messages = [m for m in body.get("messages", []) if m.get("role") == "tool"]
        tool = None
        arguments = {}
        if "CRM_SKILL_DESCRIPTION_SENTINEL" in text and "CRM_SKILL_BODY_SENTINEL" not in text:
            tool, arguments = "skill", {"name": "crm-probe"}
        elif not any("sqlite_master" in json.dumps(m) or '"columns"' in str(m.get("content")) for m in tool_messages):
            tool, arguments = "bash", {"command": "python source/query.py schema core_crm", "description": "Inspect actual CRM schema"}
        delta = {"role": "assistant", "content": "Authority"}
        finish = "stop"
        if tool:
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call-{len(tool_messages)}", "type": "function", "function": {"name": tool, "arguments": json.dumps(arguments)}}]}
            finish = "tool_calls"
        def chunk(delta, reason=None, usage=None):
            value = {"id": "local-crm-probe", "object": "chat.completion.chunk", "created": 0,
                     "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}
            if usage:
                value["usage"] = usage
            return "data: " + json.dumps(value) + "\n\n"
        payload = (chunk(delta) + chunk({}, finish, {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass


@pytest.mark.parametrize("with_initial", [False, True])
def test_real_opencode_crm_tools_and_candidate_delivery(monkeypatch, with_initial):
    load_repo_env(ROOT)
    Handler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-probe-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}/v4")
    run_id = (os.environ.get("HAI_CRM_PROBE_RUN_ID") or "crm-local-runtime-" + uuid.uuid4().hex[:12]) + ("-initial" if with_initial else "-empty")
    root = ROOT / "runs/crm_checks" / run_id
    source = root / "initial-input"
    if with_initial:
        source.mkdir(parents=True)
        (source / "AGENTS.md").write_text("CRM_INITIAL_BASE_RULE")
    from harnesslens.harnesses.initial_harness import freeze_initial_harness
    frozen = freeze_initial_harness(run_root=root, cell="crmarenapro", source=source if with_initial else None)
    evidence = root / "rollout_evidence"
    repository = CellHarnessRepository(cell="crmarenapro", repo_root=ROOT, run_id=run_id, evidence_root=evidence)
    version = repository.materialize_workspace_candidate(base_version="v0", candidate_label="candidate", workspace={"files": [
        {"scope": "project", "path": "AGENTS.md", "content": "CRM_INSTRUCTION_SENTINEL"},
        {"scope": "project", "path": "opencode.json", "content": json.dumps({"agent": {"build": {"prompt": "CRM_SYSTEM_SENTINEL"}}})},
        {"scope": "project", "path": ".opencode/skills/crm-probe/SKILL.md", "content": "---\nname: crm-probe\ndescription: CRM_SKILL_DESCRIPTION_SENTINEL\n---\nCRM_SKILL_BODY_SENTINEL"},
    ]})
    results = {}
    try:
        for ver in ("v0", version):
            service = TrainRolloutService(cell="crmarenapro", repo_root=ROOT, run_id=run_id,
                artifact_root=root / "artifacts", train_task_ids=["crmarenapro/query1"], initial_budget=1,
                evidence_root=evidence, workspace_root=root / "workspaces", local_rootless_rollout=False)
            results[ver] = service.run(RolloutRequest("probe-" + ver, run_id, "TRAIN", ver,
                {"crmarenapro/query1": 1}, 1, "local synthetic-response integration probe", {"crmarenapro/query1": 4})).to_dict()
        text = json.dumps(Handler.requests)
        if with_initial:
            assert "CRM_INITIAL_BASE_RULE" in text
            assert (source / "AGENTS.md").read_text() == "CRM_INITIAL_BASE_RULE"
        assert frozen["empty"] == (not with_initial)
        assert "CRM_INSTRUCTION_SENTINEL" in text
        assert "CRM_SYSTEM_SENTINEL" in text
        assert "CRM_SKILL_DESCRIPTION_SENTINEL" in text
        assert "CRM_SKILL_BODY_SENTINEL" in text
        assert any(m.get("role") == "tool" and "CREATE TABLE" in str(m.get("content")) for r in Handler.requests for m in r.get("messages", []))
        assert len({r["seed"] for r in Handler.requests}) == 1
        assert all(result["metrics"]["trial_success_count"] == 1 for result in results.values())
        assert results[version]["records"][0]["trial_summaries"][0]["usage"]["total_tokens"] > 0
        from harnesslens.harnesses.channel_preflight import validate_channel_preflight
        snapshot = repository.read_workspace_snapshot(version)
        preflight = validate_channel_preflight(decision={"harness_version": version, "candidate": {
            "channel_diffs": [{"channel_id": value} for value in ("instructions_rules", "system_prompt", "skills")],
            "workspace_delta": {"files": [{**item, "change": "added"} for item in snapshot["files"]]}}},
            rollout=results[version], output_path=root / "component-preflight.json")
        assert preflight["passed"]
        root.mkdir(parents=True, exist_ok=True)
        (root / "local_probe_result.json").write_text(json.dumps({"synthetic_provider": True,
            "performance_claim": False, "verified": ["real OpenCode", "real database tool", "official grader",
            "instructions", "system prompt", "skill description and body", "paired seed", "token accounting"],
            "results": results}, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
