"""Versioned business taxonomy, independent of per-experiment channel admission.

Names/counts describe our protocol, not a claim about OpenCode's module count.
Legacy channel IDs remain readable through aliases; archived trials are not rewritten.
"""
from __future__ import annotations

from typing import Any, Mapping

PROTOCOL = "harnesslens.opencode-components.v1"
OPENCODE_VERSION = "1.18.32"
COMPONENTS = (
    ("instructions_rules", "常驻规则"),
    ("system_prompt", "系统提示词"),
    ("skills", "Skill"),
    ("agent_definitions", "Agent 定义"),
    ("execution_policy", "执行与调度"),
    ("tool_description", "工具描述"),
    ("tool_parameter_description", "工具参数指导"),
    ("tool_availability", "工具可用性"),
    ("permissions", "权限规则"),
    ("commands", "Command"),
    ("reference_sources", "参考资料接入"),
    ("context_management", "上下文管理"),
    ("custom_tools", "自定义工具"),
    ("plugin_tool_system", "插件执行逻辑"),
    ("mcp_servers", "MCP 接入"),
    ("experimental_policies", "实验性策略"),
)
EDITABLE_IDS = frozenset(key for key, _ in COMPONENTS)
EDIT_SURFACES = {
    "instructions_rules": ["AGENTS.md", "instructions"],
    "system_prompt": ["agent.<name>.prompt", "experimental.chat.system.transform"],
    "skills": [".opencode/skills/*/SKILL.md", "skills.paths", "skills.urls", "skill companion files"],
    "agent_definitions": ["agent role", "agent description", "agent mode"],
    "execution_policy": ["default_agent", "agent.<name>.steps", "subagent_depth"],
    "tool_description": ["tool definition description"],
    "tool_parameter_description": ["parameter descriptions", "compatible parameter schema"],
    "tool_availability": ["tools", "agent.<name>.tools", "normalized tool visibility"],
    "permissions": ["permission", "agent.<name>.permission"],
    "commands": ["command", ".opencode/commands/*.md"],
    "reference_sources": ["references", "reference documentation and loading paths"],
    "context_management": ["compaction", "tool_output", "attachment processing"],
    "custom_tools": [".opencode/tools", "tool implementations and helper scripts"],
    "plugin_tool_system": ["plugin", ".opencode/plugins", "hooks without another semantic owner"],
    "mcp_servers": ["mcp"],
    "experimental_policies": ["explicitly admitted experimental behavior fields"],
}
PROPOSAL_ONLY = frozenset({"model_provider", "runtime_env", "file_attachments", "tool_return", "diagnostic"})
ALIASES = {
    "agent_tool_config": "tool_availability", "builtin_tools": "tool_availability",
    "compaction_config": "context_management", "project_instructions": "instructions_rules",
    "instructions": "instructions_rules", "agents": "agent_definitions",
    "tool_parameters": "tool_parameter_description", "references": "reference_sources",
    "context": "context_management", "plugins": "plugin_tool_system",
    "mcp": "mcp_servers", "experimental": "experimental_policies",
}
PROMPT_LANE_COMPONENTS = frozenset({"instructions_rules", "system_prompt", "skills", "agent_definitions"})

# Compatibility name for previously imported adapter APIs; this is a loader lane, not benchmark policy.
CRM_EDITABLE = PROMPT_LANE_COMPONENTS


def component_id(value: str) -> str:
    return ALIASES.get(value, value)


def protocol_manifest() -> dict[str, Any]:
    return {"schema": PROTOCOL, "opencode_version": OPENCODE_VERSION,
            "components": [{"number": n, "id": key, "name": name, "edit_surfaces": list(EDIT_SURFACES[key])}
                           for n, (key, name) in enumerate(COMPONENTS, 1)],
            "proposal_only": sorted(PROPOSAL_ONLY), "legacy_aliases": dict(ALIASES)}


def config_component(path: str) -> str:
    """Assign an effective config leaf exactly one semantic owner."""
    parts = path.split(".")
    head = parts[0]
    if head in {"model", "small_model", "provider", "enabled_providers", "disabled_providers"}:
        return "model_provider"
    if head == "agent" and len(parts) < 3:
        return "agent_definitions"
    if head == "agent" and len(parts) >= 3:
        if parts[2] in {"model", "provider", "temperature", "top_p", "options"}:
            return "model_provider"
        return {"prompt": "system_prompt", "tools": "tool_availability",
                "permission": "permissions", "steps": "execution_policy",
                "maxSteps": "execution_policy"}.get(parts[2], "agent_definitions")
    return {"instructions": "instructions_rules", "skills": "skills",
            "default_agent": "execution_policy", "subagent_depth": "execution_policy",
            "tools": "tool_availability", "permission": "permissions", "command": "commands",
            "references": "reference_sources", "compaction": "context_management",
            "tool_output": "context_management", "attachment": "context_management",
            "plugin": "plugin_tool_system", "mcp": "mcp_servers",
            "experimental": "experimental_policies", "logLevel": "diagnostic"}.get(head, "runtime_env")


def config_leaves(config: Mapping[str, Any], prefix: str = ""):
    for key, value in config.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping) and value:
            yield from config_leaves(value, path)
        else:
            yield path, value


def validate_config(config: Mapping[str, Any], allowed: set[str] | frozenset[str]) -> None:
    """Validate candidate config before fixed overrides can silently erase edits."""
    if not isinstance(config, Mapping):
        raise ValueError("OpenCode candidate config must be an object")
    allowed = {component_id(value) for value in allowed} - PROPOSAL_ONLY
    for path, _ in config_leaves(config):
        if path == "$schema":
            continue
        owner = config_component(path)
        if owner not in allowed:
            raise ValueError(f"OpenCode candidate field {path!r} belongs to non-editable component {owner!r}")


def validate_bundle(files: Mapping[str, Mapping[str, str]], config: Mapping[str, Any], allowed) -> None:
    allowed = {component_id(value) for value in allowed}
    validate_config(config, allowed)
    references = set(config.get("instructions", []))
    for scope, entries in files.items():
        for path, content in entries.items():
            if not content.strip():
                continue
            if path in {"opencode.json", "config.json", ".opencode/opencode.json"}:
                continue  # Already parsed and checked as config, not an opaque reference file.
            parts = path.split("/")
            owner = "reference_sources"
            if path == "AGENTS.md" or (scope == "project" and path in references):
                owner = "instructions_rules"
            elif parts[0] == ".opencode" and len(parts) > 1:
                owner = {"skill": "skills", "skills": "skills", "agent": "agent_definitions", "agents": "agent_definitions",
                         "command": "commands", "commands": "commands", "plugin": "plugin_tool_system",
                         "plugins": "plugin_tool_system", "tool": "custom_tools", "tools": "custom_tools"}.get(parts[1], owner)
            elif scope == "home" and len(parts) > 1:
                owner = {"skills": "skills", "agents": "agent_definitions", "plugins": "plugin_tool_system",
                         "tools": "custom_tools", "commands": "commands"}.get(parts[0], owner)
            if owner not in allowed:
                raise ValueError(f"Candidate file {scope}/{path} belongs to non-editable component {owner!r}")
            if owner == "agent_definitions":
                from harnesslens.harnesses.candidate_config_runtime import parse_opencode_agent_definition
                parse_opencode_agent_definition(path, content)


def runtime_contract(*, business: Mapping[str, Any] | None = None, loader_facts=None) -> dict[str, Any]:
    # These describe the actual backend, not a benchmark-specific edit whitelist.
    declared = sorted({component_id(v) for v in business["capabilities"]["channels"]}) if business else None
    return {"component_protocol": protocol_manifest(), "declared_channels": declared,
            "fixed": ["model", "provider", "budget", "task inputs", "host grading"],
            "proposal_only": sorted(PROPOSAL_ONLY),
            "loader_facts": loader_facts or {
                "config_loading": "Candidate JSON configs and flat patches are merged into the prepared bundle; a business service must explicitly load delivered files.",
                "implemented_lane": "Prompt and versioned-file delivery. Remote native prompt/skill/agent loading requires a matching receipt, runtime report and request evidence.",
                "fixed_config": ["model", "small_model", "provider"],
                "disabled_features": [],
                "tool_transport": "Defined by the configured business service; inspect its actual runtime evidence.",
                "validation": "Unimplemented config/file mechanisms fail before execution; every candidate needs channel preflight.",
            },
            "note": "The explorer must infer effective edits from loader facts and evidence. No benchmark-owned component whitelist."}
