"""Native component checks: actual config callbacks, requests and hook events.

Configuration loaded, catalog visible and behavior triggered are distinct levels.
None of them is evidence that a candidate improves the benchmark score.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Mapping

from .opencode_components import config_component, config_leaves, file_component


def _get(value, selector):
    for key in selector.split("."):
        if not isinstance(value, Mapping) or key not in value: return None
        value = value[key]
    return value


def _equivalent(expected, actual):
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(k in actual and _equivalent(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(any(_equivalent(v, item) for item in actual) for v in expected)
    if isinstance(expected, str) and isinstance(actual, str):
        return expected == actual or (actual.startswith("/") and not expected.startswith("/") and actual.endswith("/" + expected.removeprefix("./")))
    return type(expected) is type(actual) and expected == actual


def expected_edits(candidate):
    config, files = {}, []
    manifest = candidate.get("manifest_delta") or {}
    from .native_candidate_runtime import apply_flat_config
    config = apply_flat_config(config, manifest.get("config_patch") or {})
    from .candidate_config_runtime import deep_merge, parse_opencode_agent_definition, parse_opencode_command
    for item in [*(candidate.get("workspace_delta") or {}).get("files", []), *manifest.get("files", [])]:
        if item.get("change") == "deleted":
            files.append(item)
            continue
        name = item.get("path", "")
        if name in {"opencode.json", "config.json", ".opencode/opencode.json"}:
            config = deep_merge(config, json.loads(item["content"]))
        else:
            files.append(item)
            owner = file_component(item.get("scope", "project"), name)
            if owner == "agent_definitions":
                value = parse_opencode_agent_definition(name, item["content"])
                # Body belongs to Agent definition; not a second system edit.
                config = deep_merge(config, {"agent": {Path(name).stem: value}})
            elif owner == "commands" and name.endswith(".md"):
                config = deep_merge(config, {"command": {Path(name).stem: parse_opencode_command(name, item["content"])}})
    # Canonical native representation and immutable task-entry composition.
    for item in [config, *config.get("agent", {}).values()]:
        if isinstance(item.get("permission"), str): item["permission"] = {"*": item["permission"]}
    from .opencode_execution import ENTRY_COMMAND
    command = config.get("command", {}).get(ENTRY_COMMAND)
    if command and "$ARGUMENTS" not in command["template"]:
        command["template"] += "\n\n$ARGUMENTS"
    return config, files


def check_components(channels, candidate, context, row):
    expected, files = expected_edits(candidate)
    loaded = context.get("effective_config") or {}
    events = context.get("native_component_events") or []
    observed = any(e.get("kind") == "config_loaded" for e in events)
    trace = Path(str(row.get("api_calls_jsonl") or ""))
    if not trace.is_absolute(): trace = Path(row.get("_trajectory_path", "")).parent / trace
    requests = []
    if trace.is_file():
        for line in trace.read_text().splitlines():
            entry = json.loads(line)
            if isinstance(entry.get("request"), dict): requests.append(entry["request"])
    text = json.dumps(requests, ensure_ascii=False)
    messages = [m for r in requests for m in r.get("messages", []) if isinstance(m, dict)]
    system = json.dumps([m for m in messages if m.get("role") in {"system", "developer"}], ensure_ascii=False)
    tools = {t.get("name"): t for t in context.get("tool_definitions", [])}
    tool_names = {t.get("function", t).get("name") for r in requests for t in r.get("tools", [])}
    actual_files = {(i.get("scope", "project"), i.get("path")): i.get("content") for i in context.get("candidate_files", [])}
    actual_files.update({("project", i.get("path")): i.get("content") for i in context.get("candidate_project_files", [])})
    checks = []
    manifest = candidate.get("manifest_delta") or {}
    for channel in sorted(channels):
        reasons = []
        evidence = "runtime_config_loaded"
        affected = [(key, value) for key, value in config_leaves(expected) if config_component(key) == channel]
        owned_files = [f for f in files if file_component(f.get("scope", "project"), f.get("path", ""), expected) == channel]
        if not observed: reasons.append("native config callback evidence missing")
        if not requests: reasons.append("actual model-request evidence missing")
        for key, value in affected:
            if channel == "tool_availability":
                continue  # V1 tools flags are lowered to canonical permissions.
            if key.startswith("plugin"):
                continue  # Executed wrapper records identify the versioned source.
            if not _equivalent(value, _get(loaded, key)):
                reasons.append("effective native config mismatch: " + key)
        for file in owned_files:
            key = (file.get("scope", "project"), file["path"])
            if file.get("change") == "deleted":
                if key in actual_files: reasons.append("deleted candidate file is still present: " + file["path"])
            elif actual_files.get(key) != file.get("content"):
                # AGENTS.md may include immutable platform instructions.
                if channel != "instructions_rules" or file.get("content", "").strip() not in (actual_files.get(key) or ""):
                    reasons.append("runtime candidate file missing/changed: " + file["path"])
        if channel == "instructions_rules":
            values = [*manifest.get("instructions", []), *manifest.get("prompt_appends", [])]
            values += [f.get("content", "").strip() for f in owned_files if f.get("change") != "deleted" and f.get("path") == "AGENTS.md"]
            if not affected and not values and not owned_files: reasons.append("no resident-rule edit")
            if any(v not in system for v in values if v): reasons.append("resident rule absent from system request")
            evidence = "model_request"
        elif channel == "system_prompt":
            if not affected: reasons.append("no system prompt edit")
            if any(isinstance(v, str) and v not in system for _, v in affected): reasons.append("system prompt absent from system/developer request")
            evidence = "model_request"
        elif channel == "skills":
            skills = [f for f in owned_files if f.get("path", "").endswith("/SKILL.md") and f.get("change") != "deleted"]
            from .channel_preflight import _skill_description
            if not skills and not affected and not owned_files: reasons.append("no skill edit")
            for file in skills:
                description = _skill_description(file["content"])
                if description and description not in text: reasons.append("skill discovery description absent from request")
            evidence = "request_catalog"
        elif channel in {"tool_description", "tool_parameter_description"}:
            patches = manifest.get("tool_desc_patches") or {}
            if not patches: reasons.append("no exact tool patch")
            for name, patch in patches.items():
                tool = tools.get(name, {})
                schema = tool.get("parameters", tool.get("inputSchema", {}))
                if channel == "tool_description" and patch.get("desc") and patch["desc"] not in tool.get("description", ""):
                    reasons.append("tool description absent from request: " + name)
                if channel == "tool_parameter_description":
                    for param, desc in (patch.get("params") or {}).items():
                        if (schema.get("properties", {}).get(param) or {}).get("description") != desc:
                            reasons.append("tool parameter description absent from request: " + name + "." + param)
            evidence = "request_catalog"
        elif channel == "tool_availability":
            if not affected: reasons.append("no tool availability edit")
            for key, value in affected:
                name = key.rsplit(".", 1)[-1]
                if key.startswith("tools.") and "*" not in name and (name in tool_names) != value:
                    reasons.append("tool visibility does not match request catalog: " + name)
            evidence = "request_catalog"
        elif channel == "agent_definitions":
            if not affected and not owned_files: reasons.append("no Agent definition edit")
            for file in owned_files:
                if file.get("change") == "deleted": continue
                from .candidate_config_runtime import parse_opencode_agent_definition
                value = parse_opencode_agent_definition(file["path"], file["content"])
                if not _equivalent(value, loaded.get("agent", {}).get(Path(file["path"]).stem, {})):
                    reasons.append("Agent definition not loaded by native config")
        elif channel == "commands":
            commands = expected.get("command", {})
            invoked = {e.get("command") for e in events if e.get("kind") == "command_invoked"}
            if not commands and not owned_files: reasons.append("no Command edit")
            for name in commands:
                if name not in invoked: reasons.append("Command not invoked: " + name)
            evidence = "runtime_triggered"
        elif channel == "reference_sources":
            references = expected.get("references", {})
            if not references: reasons.append("reference files require a named references entry and loading path")
            for name, ref in references.items():
                if not ref.get("hidden") and (name not in system or ref.get("description", "") not in system):
                    reasons.append("reference loading catalog absent from system request: " + name)
            evidence = "request_catalog"
        elif channel == "custom_tools":
            for file in owned_files:
                if file.get("change") == "deleted" or not file["path"].endswith((".js", ".ts")): continue
                stem = Path(file["path"]).stem
                if not any(n == stem or str(n).startswith(stem + "_") for n in tool_names):
                    reasons.append("custom tool not exposed in model request: " + stem)
            if not owned_files: reasons.append("no custom tool file")
            evidence = "request_catalog"
        elif channel == "plugin_tool_system":
            sources = [e.get("source") for e in events if e.get("kind") == "plugin_loaded"]
            hooks = [e.get("source") for e in events if e.get("kind") == "plugin_hook"]
            relevant = [f["path"] for f in owned_files if f.get("change") != "deleted" and f["path"].endswith((".js", ".ts", ".mjs"))]
            for path in relevant:
                if not any(str(source).endswith(path) for source in sources): reasons.append("plugin did not initialize: " + path)
                if not any(str(source).endswith(path) for source in hooks): reasons.append("plugin hook was not triggered: " + path)
            if not relevant and not affected: reasons.append("no plugin edit")
            evidence = "runtime_triggered"
        elif channel == "mcp_servers":
            servers = expected.get("mcp", {})
            if not servers: reasons.append("no MCP server config")
            for name, server in servers.items():
                if server.get("enabled", True) and not any(str(tool).startswith(name + "_") for tool in tool_names):
                    reasons.append("enabled MCP server exposed no tools to the model: " + name)
            evidence = "request_catalog"
        elif not affected:
            reasons.append("no owned native config edit")
        failures = [e for e in events if e.get("kind") in {"component_error", "policy_violation"}]
        if failures: reasons.append("native component errors recorded")
        checks.append({"channel_id": channel, "passed": not reasons, "evidence_level": evidence,
                       "behavior_triggered": evidence == "runtime_triggered" and not reasons,
                       "detail": "; ".join(reasons) if reasons else "Verified " + evidence})
    return checks
