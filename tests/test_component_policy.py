import json
from pathlib import Path

import pytest

from harnesslens.harnesses.component_policy import allowed_components, normalize_policy
from harnesslens.harnesses.opencode_components import EDITABLE_IDS, PROPOSAL_ONLY
from harnesslens.harnesses.opencode_execution import validate_manifest
from harnesslens.service.config import load_profile, invocation


def test_default_is_all_sixteen_not_a_benchmark_whitelist(monkeypatch):
    monkeypatch.delenv("HAI_COMPONENT_POLICY", raising=False)
    assert allowed_components() == EDITABLE_IDS
    assert not allowed_components() & PROPOSAL_ONLY


def test_startup_policy_is_applied_before_subprocess_and_model_discovery(tmp_path, monkeypatch, model_tables):
    monkeypatch.setenv("HAI_COMPONENT_POLICY", '{"allowed":["skills"]}')
    path = tmp_path / "experiment.toml"
    path.write_text('schema="harnesslens.experiment.v1"\n[components]\nallowed=["*"]\ndenied=["permissions","mcp_servers"]\nexperimental_fields=["batch_tool"]\n')
    path.write_text(path.read_text() + model_tables)
    profile = load_profile(path)
    _, env = invocation(profile, "policy-test")
    policy = json.loads(env["HAI_COMPONENT_POLICY"])
    assert set(policy["allowed"]) == EDITABLE_IDS - {"permissions", "mcp_servers"}
    assert policy["experimental_fields"] == ["batch_tool"]
    monkeypatch.setenv("HAI_COMPONENT_POLICY", env["HAI_COMPONENT_POLICY"])
    with pytest.raises(ValueError, match="non-editable"):
        validate_manifest({"config_patch": {"permission.bash": "deny"}})
    with pytest.raises(ValueError, match="experimental"):
        validate_manifest({"config_patch": {"experimental.continue_loop_on_deny": True}})


@pytest.mark.parametrize("raw", [
    {"allowed": ["model_provider"]}, {"denied": ["unknown"]},
    {"experimental_fields": ["openTelemetry"]}, {"allowed": "*"}, {"enabled": True},
])
def test_invalid_or_proposal_only_policy_fails_before_a_run(raw):
    with pytest.raises(ValueError): normalize_policy(raw)


@pytest.mark.parametrize("patch", [
    {"agent.build.model": "other/model"}, {"agent.build.temperature": .1},
    {"command.test.model": "other/model"}, {"agent.build.unknown_option": True},
    {"experimental.policies": []}, {"experimental.openTelemetry": True},
    {"experimental.anything": True}, {"tool_output.unknown": 1},
    {"compaction.auto": "true"}, {"agent.build.steps": 41}, {"subagent_depth": 9},
])
def test_fixed_unknown_or_over_budget_fields_cannot_be_enabled(patch, monkeypatch):
    monkeypatch.delenv("HAI_COMPONENT_POLICY", raising=False)
    with pytest.raises(ValueError): validate_manifest({"config_patch": patch})


def test_business_capability_is_a_real_upper_bound_not_four_hardcoded_channels(tmp_path):
    from harnesslens.harnesses.business_agent import load_config
    path = tmp_path / "business.toml"
    path.write_text('[agent]\ntype="python"\nfunction="business:solve"\nrequire_harness_receipt=true\nruntime_report_path="runtime_report"\n[agent.arguments]\nharness_files="{harness_files}"\n[capabilities]\nchannels=["custom_tools","mcp_servers","permissions"]\n')
    config = load_config(path)
    assert allowed_components(config) == {"custom_tools", "mcp_servers", "permissions"}


def test_agent_frontmatter_obeys_semantic_policy(monkeypatch):
    manifest = {"files": [{"path": ".opencode/agents/worker.md", "content":
        '---\ndescription: Worker\nmode: primary\nsteps: 20\npermission:\n  bash: deny\n---\nWorker instructions'}]}
    monkeypatch.delenv("HAI_COMPONENT_POLICY", raising=False)
    validate_manifest(manifest)
    monkeypatch.setenv("HAI_COMPONENT_POLICY", '{"denied":["permissions"]}')
    with pytest.raises(ValueError, match="permissions"): validate_manifest(manifest)


def test_new_benchmark_name_does_not_change_component_boundary(monkeypatch):
    monkeypatch.delenv("HAI_COMPONENT_POLICY", raising=False)
    from harnesslens.harnesses.opencode_components import runtime_contract
    a = runtime_contract()["component_policy"]
    monkeypatch.setenv("HAI_BENCHMARK", "another-question-set")
    assert runtime_contract()["component_policy"] == a


def test_discovery_receives_all_sixteen_without_stale_disabled_overrides(tmp_path, monkeypatch):
    from harnesslens.evolution.discovery import DiscoveryModule
    from harnesslens.harnesses.opencode_components import runtime_contract
    from harnesslens.harnesses.opencode_harness import OpencodeHarnessAdapter
    monkeypatch.delenv("HAI_COMPONENT_POLICY", raising=False)
    adapter = OpencodeHarnessAdapter()
    monkeypatch.setattr(adapter, "architecture_probe", lambda: {"harness_id": "opencode", "harness_version": "1.18.32"})
    monkeypatch.setattr(adapter, "query_evidence_catalog", lambda _: [])
    monkeypatch.setattr("harnesslens.evolution.discovery.harness_query_adapter", lambda *a, **k: adapter)
    module = DiscoveryModule(repo_root=Path(__file__).resolve().parents[1], run_root=tmp_path, budget=None, cell="crm")
    tools = [{"name": "bash", "description": "Actual native Bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}]
    payload = module._harness_query_input({"environment": {"native_tools": tools,
        "runtime_contract": runtime_contract(loader_facts={"implemented_lane": "native16", "fixed_config": ["model"], "disabled_features": []})}})
    hypotheses = {v["id"]: v for v in payload["surface_hypotheses"]}
    assert all(hypotheses[key].get("policy_status") != "forbidden" for key in EDITABLE_IDS)
    loading = payload["candidate_workspace_contract"]["runtime_loading"]
    assert not loading.get("conditional_surface_ids")
    assert not any("compaction" in str(v) or "tools and permissions" in str(v) for v in loading.get("disabled_behavior", []))
    assert payload["public_runtime"]["native_tools"] == tools
    assert any(e["id"] == "runtime:baseline-tool-catalog" for e in payload["evidence_catalog"])
    monkeypatch.setenv("HAI_COMPONENT_POLICY", '{"denied":["custom_tools"]}')
    payload = module._harness_query_input({"environment": {"runtime_contract": runtime_contract()}})
    assert next(v for v in payload["surface_hypotheses"] if v["id"] == "custom_tools")["policy_status"] == "forbidden"


def test_baseline_tool_catalog_contains_no_answers_or_other_request_content(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from harnesslens.benchmarks.task_data import BaselineDataset, benchmark_task_explorer_input
    tools = [{"type": "function", "function": {"name": "business_lookup", "description": "Native tool", "parameters": {"type": "object"}}}]
    api = tmp_path / "api.jsonl"
    api.write_text(json.dumps({"request": {"tools": tools, "messages": [{"role": "system", "content": "PRIVATE_PROMPT_SENTINEL"}]},
                               "response": {"content": "ANSWER_SENTINEL"}}))
    trajectory = tmp_path / "trial.jsonl"; trajectory.write_text(json.dumps({"task_id": "train", "api_calls_jsonl": str(api)}))
    baseline = BaselineDataset(("train",), (str(trajectory),), {"train": (str(trajectory),)}, {}, "fixture")
    monkeypatch.setattr("harnesslens.benchmarks.adapters.benchmark_adapter", lambda *a: SimpleNamespace(explorer_input=lambda ids: {"environment": {}}))
    result = benchmark_task_explorer_input(repo_root=Path(__file__).resolve().parents[1], baseline=baseline, cell="crm")
    assert result["environment"]["native_tools"][0]["name"] == "business_lookup"
    assert "PRIVATE_PROMPT_SENTINEL" not in json.dumps(result)
    assert "ANSWER_SENTINEL" not in json.dumps(result)


def test_prepared_config_without_native_callbacks_cannot_verify_new_components(tmp_path):
    from harnesslens.harnesses.channel_preflight import validate_channel_preflight, ChannelPreflightError
    trace = tmp_path / "api.jsonl"; trace.write_text(json.dumps({"request": {"messages": [{"role": "user", "content": "probe"}]}, "response": {}}))
    row = tmp_path / "trial.jsonl"; row.write_text(json.dumps({"model_context": {"harness": "opencode",
        "effective_config": {"compaction": {"auto": True}}, "verification_level": "prepared_files_only"}, "api_calls_jsonl": str(trace)}))
    with pytest.raises(ChannelPreflightError, match="callback"):
        validate_channel_preflight(decision={"candidate": {"channel_diffs": [{"channel_id": "context_management"}],
            "manifest_delta": {"config_patch": {"compaction.auto": True}}}},
            rollout={"per_task": {"train": {"trajectory_paths": [str(row)]}}}, output_path=tmp_path / "preflight.json")


def test_history_includes_native_tool_patches_and_config_fields():
    from harnesslens.service.history import grouped_files
    result = grouped_files({"files": [{"scope": "project", "path": ".opencode/mcp/server.py", "content": "server code"}]},
        {"config_patch": {"agent.build.steps": 20}, "tool_desc_patches": {"bash": {"desc": "Bash guidance", "params": {"command": "Command guidance"}}}})
    assert result["mcp_servers"] and result["execution_policy"]
    assert result["tool_description"] and result["tool_parameter_description"]


@pytest.mark.parametrize("path", ["../outside.txt", "/tmp/outside.txt", ".runtime/harnesslens/bridge.mjs", "source/task.json"])
def test_legacy_manifest_files_cannot_escape_or_replace_runtime(path):
    with pytest.raises(ValueError): validate_manifest({"files": [{"path": path, "content": "overwrite"}]})


def test_agent_step_only_edit_has_one_owner_in_editor_and_history():
    from harnesslens.evolution.main_agent import actual_editor_channel_diffs
    from harnesslens.service.history import grouped_files
    before = "---\ndescription: A worker\nmode: subagent\nsteps: 20\n---\nWorker body"
    after = before.replace("steps: 20", "steps: 10")
    path = ".opencode/agents/worker.md"
    def workspace(text): return {"files": [{"scope": "project", "path": path, "content": text}]}
    query = {"harness": "opencode", "modifiable_modules": [{"id": key, "edit_contract": {"scope": "project", "path": path, "mechanism": "file"}}
             for key in ("agent_definitions", "execution_policy")]}
    diffs = actual_editor_channel_diffs(harness_query=query, selected_candidate={"channel_plan": []},
        workspace_changes=[{"scope": "project", "path": path, "change": "modified"}], mcp_tool_patches={},
        base_workspace=workspace(before), candidate_workspace=workspace(after))
    assert {item["channel_id"] for item in diffs} == {"execution_policy"}
    a, b = grouped_files(workspace(before), {}), grouped_files(workspace(after), {})
    assert a["agent_definitions"] == b["agent_definitions"]
    assert a["execution_policy"] != b["execution_policy"]


def test_native_editor_materializes_non_prompt_components_through_normal_pipeline(monkeypatch):
    from types import SimpleNamespace
    from harnesslens.evolution.main_agent import materialize_selected_problem
    from harnesslens.harnesses.harness_workspace import MCP_PATCH_WORKSPACE_PATH
    monkeypatch.delenv("HAI_AGENT_CONFIG", raising=False)
    monkeypatch.delenv("HAI_COMPONENT_POLICY", raising=False)
    config = {"agent": {"worker": {"description": "A primary worker", "mode": "primary", "prompt": "Worker system prompt", "steps": 20}},
        "default_agent": "worker", "tools": {"todowrite": False}, "permission": {"bash": "allow"},
        "command": {"harnesslens_run": {"template": "Check evidence. $ARGUMENTS"}},
        "references": {"docs": {"path": "references/docs", "description": "Project docs"}},
        "compaction": {"tail_turns": 2}, "experimental": {"continue_loop_on_deny": True},
        "mcp": {"probe": {"type": "local", "command": ["python", ".opencode/mcp/probe.py"]}}}
    files = {"opencode.json": json.dumps(config), "references/docs/guide.md": "Reference text",
        ".opencode/plugins/probe.js": "export default async () => ({})",
        ".opencode/tools/probe.js": "export default {description:'Probe',args:{},execute:async()=> 'ok'}",
        ".opencode/mcp/probe.py": "# Versioned local server",
        ".opencode/skills/probe/SKILL.md": "---\nname: probe\ndescription: Probe skill\n---\nSkill body",
        MCP_PATCH_WORKSPACE_PATH: json.dumps({"bash": {"desc": "Bash guidance", "params": {"command": "Command guidance"}}})}
    snapshot = {"files": [{"scope": "project", "path": name, "content": content} for name, content in files.items()]}
    chosen = EDITABLE_IDS - {"instructions_rules"}
    query = {"harness": "opencode", "modifiable_modules": [{"id": key, "edit_contract": {"scope": "project", "path": "opencode.json", "mechanism": "file"}} for key in chosen]}
    captured = {}
    class Repository:
        harness = "opencode"
        def read_workspace_snapshot(self, _): return {"files": []}
        def read_candidate_snapshot(self, _): return {}
        def materialize_workspace_candidate(self, **kwargs): captured.update(kwargs); return "candidate"
    class Editor:
        def edit(self, **kwargs):
            return SimpleNamespace(snapshot=snapshot, summary={}, root="editor", stdout_path="stdout", stderr_path="stderr", api_trace_path="trace")
    version, result = materialize_selected_problem(repository=Repository(), editor=Editor(), parent_version="v0", candidate_label="candidate",
        editor_job_id="editor", harness_query=query, selected_candidate={"channel_plan": [{"channel_id": key, "experience_ids": ["train-evidence"]} for key in chosen]}, evidence=[])
    assert version == "candidate"
    assert {v["channel_id"] for v in result["channel_diffs"]} == chosen
    assert captured["manifest_delta"]["tool_desc_patches"]["bash"]["params"]["command"] == "Command guidance"
    assert not any(f["path"] == MCP_PATCH_WORKSPACE_PATH for f in captured["workspace"]["files"])


def test_receiver_policy_intersects_server_without_cross_request_state(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from harnesslens.harnesses.component_policy import receiver_policy, current_policy
    monkeypatch.setenv("HAI_COMPONENT_POLICY", '{"denied":["mcp_servers"]}')
    original = current_policy()
    requests = [{"denied": ["permissions"]}, {"allowed": ["*"]}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(receiver_policy, requests))
    assert "permissions" not in a["allowed"] and "permissions" in b["allowed"]
    assert "mcp_servers" not in a["allowed"] and "mcp_servers" not in b["allowed"]
    assert current_policy() == original
