import json
from pathlib import Path

import pytest

from harnesslens.harnesses.opencode_components import (
    COMPONENTS, PROPOSAL_ONLY, CRM_EDITABLE, component_id, config_component,
    validate_config, validate_bundle, runtime_contract,
)
from harnesslens.harnesses.opencode_harness import OpencodeHarnessAdapter
from harnesslens.evolution.discovery import _enforce_native_channel_admission
from harnesslens.harnesses.native_candidate_runtime import attach_candidate_workspace
from harnesslens.benchmarks.crm_eval import prepare_harness, CrmLimits
from harnesslens.benchmarks.crm_business import prepare_harness as prepare_business


def test_protocol_catalog_has_16_components_and_original_5_proposal_only():
    inventory = OpencodeHarnessAdapter().query_channel_inventory()
    assert [i["id"] for i in inventory[:16]] == [key for key, _ in COMPONENTS]
    assert [i["number"] for i in inventory[:16]] == list(range(1, 17))
    assert {i["id"] for i in inventory if i["materialization"] == "proposal_only"} == PROPOSAL_ONLY
    assert len(inventory) == 21
    assert component_id("agent_tool_config") == component_id("builtin_tools") == "tool_availability"
    assert component_id("compaction_config") == "context_management"


@pytest.mark.parametrize("channel", ["instructions_rules", "system_prompt", "skills", "agent_definitions"])
def test_experiment_restriction_wins_over_generic_admission(channel):
    output = {}
    _enforce_native_channel_admission(output, hypotheses={channel: {"policy_status": "forbidden"}},
                                    harness="opencode", controller_mcp_ids=set())
    assert output["modifiable_modules"] == []
    assert output["unavailable_modules"][0]["status"] == "forbidden"


@pytest.mark.parametrize("channel", sorted(PROPOSAL_ONLY))
def test_proposal_only_never_becomes_modifiable(channel):
    output = {"modifiable_modules": [{"id": channel, "status": "modifiable"}]}
    _enforce_native_channel_admission(output, hypotheses={channel: {}}, harness="opencode", controller_mcp_ids=set())
    assert not output["modifiable_modules"]
    assert output["unavailable_modules"][0]["status"] == "forbidden"


@pytest.mark.parametrize(("path", "owner"), [
    ("agent.build.steps", "execution_policy"), ("subagent_depth", "execution_policy"),
    ("agent.explore.permission.bash", "permissions"), ("agent.explore.tools.read", "tool_availability"),
    ("agent.explore.prompt", "system_prompt"), ("agent.explore.description", "agent_definitions"),
    ("agent.explore.model", "model_provider"), ("tool_output.max_bytes", "context_management"),
    ("attachment.max_size", "context_management"), ("references.docs.path", "reference_sources"),
])
def test_fields_have_one_semantic_owner(path, owner):
    assert config_component(path) == owner


@pytest.mark.parametrize("config", [
    {"model": "other/model"}, {"small_model": "other/model"}, {"provider": {"other": {}}},
    {"agent": {"build": {"steps": 999}}}, {"agent": {"build": {"model": "other/model"}}},
    {"permission": {"bash": "allow"}}, {"tools": {"webfetch": True}}, {"mcp": {}},
    {"tool_output": {"max_bytes": 1}}, {"attachment": {}}, {"experimental": {"anything": True}},
])
def test_crm_rejects_fixed_config_before_runtime_overwrites_it(tmp_path, config):
    manifest = attach_candidate_workspace({}, {"files": [{"scope": "project", "path": "opencode.json", "content": json.dumps(config)}]})
    with pytest.raises(ValueError, match="non-editable"):
        prepare_harness(tmp_path, manifest, 12345, CrmLimits())


def test_business_preserves_native_prompt_separate_from_resident_instructions(tmp_path, monkeypatch):
    # Offline bundle preparation; no business service or model requests.
    monkeypatch.delenv("HAI_AGENT_CONFIG", raising=False)
    manifest = {"instructions": ["resident-rule"], "config_patch": {"agent.build.prompt": "native-system-sentinel"}}
    files, resident, _, _ = prepare_business(tmp_path, manifest)
    assert "native-system-sentinel" not in resident
    assert "native-system-sentinel" not in files["project"]["AGENTS.md"]
    assert json.loads(files["project"]["opencode.json"])["agent"]["build"]["prompt"] == "native-system-sentinel"


def test_business_declared_channels_limit_all_candidate_file_paths(tmp_path, monkeypatch):
    config = tmp_path / "agent.toml"
    config.write_text('[agent]\ntype="python"\nfunction="business:solve"\n[capabilities]\nchannels=["instructions_rules"]\n')
    monkeypatch.setenv("HAI_AGENT_CONFIG", str(config))
    manifest = {"files": [{"path": ".opencode/skills/probe/SKILL.md", "content": "skill"}]}
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ValueError, match="non-editable component 'skills'"):
        prepare_business(work, manifest)
    assert runtime_contract(business={"capabilities": {"channels": ["instructions_rules"]}})["declared_channels"] == ["instructions_rules"]


def test_baseline_empty_config_still_starts_with_fixed_crm_runtime(tmp_path):
    (tmp_path / "workspace").mkdir()
    _, config, _ = prepare_harness(tmp_path, {}, 12345, CrmLimits())
    assert config["agent"]["build"]["steps"] == 40
    assert config["mcp"] == {}


def test_selected_package_is_self_contained_and_detects_mutation(tmp_path):
    from harnesslens.harnesses.opencode_package import export_package
    from harnesslens.harnesses.opencode_components import protocol_manifest
    bundle = {"files": [{"scope": "project", "path": "AGENTS.md", "content": "rule"}]}
    params = dict(directory=tmp_path, version="v-test", workspace=bundle, manifest={})
    receipt = export_package(**params)
    saved = json.loads(Path(receipt["path"]).read_text())
    assert saved["workspace"]["files"][0]["content"] == "rule"
    assert saved["component_protocol"] == protocol_manifest()
    assert export_package(**params) == receipt
    Path(receipt["path"]).write_text("changed")
    with pytest.raises(ValueError, match="package changed"):
        export_package(**params)


@pytest.mark.parametrize("extra", ["model: other/model", "steps: 999", "permission: allow", "tools: {bash: true}"])
def test_agent_markdown_cannot_bypass_frozen_config(extra):
    files = {"project": {".opencode/agents/probe.md": f"---\ndescription: Probe\n{extra}\n---\nPrompt"}}
    with pytest.raises(ValueError, match="Prompt-only"):
        validate_bundle(files, {}, CRM_EDITABLE)


@pytest.mark.parametrize("role", ["system", "user"])
def test_system_prompt_requires_system_role_not_just_matching_text(tmp_path, role):
    from harnesslens.harnesses.channel_preflight import build_runtime_load_report, validate_channel_preflight, ChannelPreflightError
    content = json.dumps({"agent": {"build": {"prompt": "system-only-sentinel"}}})
    (tmp_path / "opencode.json").write_text(content)
    report = build_runtime_load_report(harness="opencode", project_root=tmp_path, home_root=None,
                                      manifest={}, tool_definitions=[])
    api = tmp_path / "calls.jsonl"
    api.write_text(json.dumps({"request": {"messages": [{"role": role, "content": "system-only-sentinel"}]}, "response": {}}))
    row = tmp_path / "trial.jsonl"
    row.write_text(json.dumps({"model_context": report, "api_calls_jsonl": str(api)}))
    decision = {"candidate": {"channel_diffs": [{"channel_id": "system_prompt"}],
        "workspace_delta": {"files": [{"scope": "project", "path": "opencode.json", "change": "added", "content": content}]}}}
    kwargs = dict(decision=decision, rollout={"per_task": {"sample": {"trajectory_paths": [str(row)]}}}, output_path=tmp_path / "preflight.json")
    if role == "user":
        with pytest.raises(ChannelPreflightError):
            validate_channel_preflight(**kwargs)
    else:
        assert validate_channel_preflight(**kwargs)["passed"]


def test_model_discovery_is_not_replaced_by_historical_four_channel_whitelist():
    output = {"modifiable_modules": [{"id": "commands", "status": "modifiable", "evidence_level": "documented",
        "edit_contract": {"scope": "project", "path": ".opencode/commands/check.md", "mechanism": "file"},
        "evidence_refs": ["docs:opencode:commands"], "visibility": "explicit invocation",
        "use": "Reusable command", "risks": "Needs invocation", "runtime_constraints": ["Invoker must call the command"]}],
        "unavailable_modules": [{"id": "skills", "status": "unsupported", "reason": "This service does not load skill files",
            "evidence_refs": ["service:loader"]}]}
    _enforce_native_channel_admission(output, hypotheses={"commands": {}, "skills": {}, "system_prompt": {}},
                                    harness="opencode", controller_mcp_ids=set())
    assert [item["id"] for item in output["modifiable_modules"]] == ["commands"]
    unavailable = {item["id"]: item for item in output["unavailable_modules"]}
    assert unavailable["skills"]["reason"] == "This service does not load skill files"
    assert unavailable["system_prompt"]["status"] == "conditional"


def test_runtime_contract_reports_loader_facts_instead_of_benchmark_whitelist():
    contract = runtime_contract()
    assert "editable" not in contract
    assert "unavailable" not in contract
    assert contract["declared_channels"] is None
    assert contract["loader_facts"]["fixed_config"]
