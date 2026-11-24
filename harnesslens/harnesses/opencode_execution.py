"""Versioned native OpenCode component loading, shared by benchmark adapters.

Candidate permissions and executable extensions remain inside the host sandbox.
The host owns data, model access, grading, timeouts and experiment budgets.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Mapping

from .candidate_config_runtime import (compile_opencode_agent_definitions, compile_opencode_commands,
    deep_merge, load_json_configs)
from .native_candidate_runtime import apply_flat_config, candidate_workspace
from .opencode_components import (file_component,
    validate_bundle, validate_config)
from .component_policy import allowed_components, current_policy, policy_contract

CONFIG_PATHS = (("home", "config.json"), ("home", "opencode.json"),
                ("project", ".opencode/opencode.json"), ("project", "opencode.json"))
ENTRY_COMMAND = "harnesslens_run"
BRIDGE = Path(__file__).with_name("opencode_bridge.mjs")


def install_plugin_helpers(directory):
    """Seed checksum-pinned offline helpers, avoiding native startup npm fetches."""
    root = BRIDGE.parents[2]
    archive = root / "assets/opencode-plugin-runtime-1.18.32.tar.gz"
    pin = json.loads((root / "configs/opencode-plugin-runtime.json").read_text())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pin["sha256"]:
        raise ValueError("Offline OpenCode plugin helper archive changed")
    cache = root / "runtime" / ("opencode-plugin-helpers-" + pin["sha256"][:16])
    # Extraction only writes trusted packaged files. Concurrent trials lock the
    # cache and never let the sandbox alter it.
    import fcntl
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = cache / "ready.json"
        if not marker.is_file():
            cache.mkdir(exist_ok=True)
            with tarfile.open(archive) as tar:
                tar.extractall(cache, filter="data")
            marker.write_text(json.dumps(pin))
    directory.mkdir(parents=True, exist_ok=True)
    modules = directory / "node_modules"
    if not modules.exists(): modules.symlink_to(cache / "node_modules", target_is_directory=True)
    (directory / "package.json").write_text(json.dumps({"private": True, "type": "module", "dependencies": {"@opencode-ai/plugin": "1.18.32"}}))
    (directory / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {"": {"dependencies": {"@opencode-ai/plugin": "1.18.32"}}}}))
    (directory / ".gitignore").write_text("node_modules\npackage.json\npackage-lock.json\nbun.lock\nbun.lockb\n.gitignore\n")
    return cache


def declared_files(manifest):
    result = {"home": {}, "project": {}}
    for item in candidate_workspace(manifest)["files"]:
        result[item["scope"]][item["path"]] = item["content"]
    for item in manifest.get("files") or []:
        result["project"][item["path"]] = item["content"]
    return result


def validate_manifest(manifest, *, business=None, max_steps=40, policy=None):
    from .harness_manifest import MANIFEST_FIELDS, normalize_native_manifest
    # Legacy files must have exactly the same path/input validation as captured
    # workspace files, before the host writes anything to disk.
    normalize_native_manifest({key: manifest[key] for key in MANIFEST_FIELDS if key in manifest})
    files = declared_files(manifest)
    allowed = allowed_components(business, policy=policy)
    experimental_fields = (policy if policy is not None else current_policy())["experimental_fields"]
    merged = {}
    for scope, name in CONFIG_PATHS:
        if name in files[scope]:
            value = json.loads(files[scope][name])
            validate_config(value, allowed)
            validate_native_config(value, max_steps=max_steps, experimental_fields=experimental_fields)
            merged = deep_merge(merged, value)
    merged = apply_flat_config(merged, manifest.get("config_patch") or {})
    validate_config(merged, allowed)
    validate_native_config(merged, max_steps=max_steps, experimental_fields=experimental_fields)
    validate_bundle(files, merged, allowed)
    for scope, entries in files.items():
        for name, content in entries.items():
            if name.split("/")[0] in {"source", "output", ".runtime", ".git", "node_modules"}:
                raise ValueError(f"Candidate cannot replace protected task/runtime files: {scope}/{name}")
            if name.endswith(("package.json", "bun.lock", "bun.lockb")):
                raise ValueError("Candidate dependencies must use the fixed offline runtime; package installation is not an edit surface")
            if Path(name).name in {"opencode.jsonc", "config.jsonc"}:
                raise ValueError("Convert captured OpenCode JSONC config to JSON before the experiment")
            if file_component(scope, name, merged) == "agent_definitions":
                from .candidate_config_runtime import parse_opencode_agent_definition
                validate_native_config({"agent": {Path(name).stem: parse_opencode_agent_definition(name, content)}}, max_steps=max_steps)
            if file_component(scope, name, merged) == "skills" and name.endswith("/SKILL.md"):
                import re
                import yaml
                match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", content, re.S)
                try:
                    metadata = yaml.safe_load(match[1]) if match else None
                except yaml.YAMLError as exc:
                    raise ValueError("Invalid Skill YAML frontmatter") from exc
                if not isinstance(metadata, Mapping) or not isinstance(metadata.get("name"), str) or not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
                    raise ValueError("SKILL.md requires name and description frontmatter")
                if metadata["name"] != Path(name).parent.name:
                    raise ValueError("Skill name must match its captured directory")
    if (manifest.get("instructions") or manifest.get("prompt_appends")) and "instructions_rules" not in allowed:
        raise ValueError("Resident instruction edits are disabled by the experiment policy")
    patches = manifest.get("tool_desc_patches") or {}
    normalize_native_manifest({"tool_desc_patches": patches})
    for value in patches.values():
        if value.get("desc") and "tool_description" not in allowed:
            raise ValueError("Tool description edits are disabled by the experiment policy")
        if value.get("params") and "tool_parameter_description" not in allowed:
            raise ValueError("Tool parameter edits are disabled by the experiment policy")
    return merged


def validate_native_config(config, *, max_steps=40, experimental_fields=None):
    """Fail on unknown fields instead of letting OpenCode silently discard them."""
    def object_of(value, keys, name):
        if not isinstance(value, Mapping) or set(value) - set(keys):
            raise ValueError(f"Unsupported OpenCode 1.18.32 {name} fields")
    def integer(value, low, high, name):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name} must be an integer in {low}..{high}")
    def strings(value, name):
        if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
            raise ValueError(name + " must be an array of nonempty strings")
    for name, value in config.items():
        if name == "$schema":
            continue
        if name in {"tool_output", "compaction", "attachment", "experimental"}:
            fields = {"tool_output": {"max_bytes", "max_lines"},
                      "compaction": {"auto", "prune", "tail_turns", "preserve_recent_tokens", "reserved"},
                      "attachment": {"image"}, "experimental": set(current_policy()["experimental_fields"] if experimental_fields is None else experimental_fields)}[name]
            object_of(value, fields, name)
            for key, item in value.items():
                if key in {"auto", "prune", "batch_tool", "continue_loop_on_deny", "disable_paste_summary"}:
                    if type(item) is not bool: raise ValueError(f"{name}.{key} must be boolean")
                elif key == "primary_tools":
                    if not isinstance(item, list) or any(not isinstance(v, str) for v in item):
                        raise ValueError("experimental.primary_tools must be tool names")
                elif key == "image":
                    object_of(item, {"auto_resize", "max_width", "max_height", "max_base64_bytes"}, "attachment.image")
                    for field, setting in item.items():
                        if field == "auto_resize":
                            if type(setting) is not bool: raise ValueError("attachment.image.auto_resize must be boolean")
                        else: integer(setting, 1, 100_000_000, "attachment.image." + field)
                else:
                    integer(item, 0 if name == "compaction" else 1, 100_000_000, name + "." + key)
        elif name == "agent":
            if not isinstance(value, Mapping): raise ValueError("agent must be an object")
            for agent_name, agent in value.items():
                object_of(agent, {"prompt", "description", "mode", "hidden", "disable", "color", "tools", "permission", "steps", "maxSteps"}, "agent")
                for field, setting in agent.items():
                    if field in {"steps", "maxSteps"}: integer(setting, 1, max_steps, f"agent.{agent_name}.{field}")
                    elif field in {"tools", "permission"}: validate_native_config({"tools" if field == "tools" else "permission": setting}, max_steps=max_steps)
                    elif field in {"hidden", "disable"}:
                        if type(setting) is not bool: raise ValueError(f"agent.{field} must be boolean")
                    elif field == "mode":
                        if not isinstance(setting, str) or setting not in {"primary", "subagent", "all"}: raise ValueError("Invalid Agent mode")
                    elif not isinstance(setting, str): raise ValueError(f"agent.{field} must be text")
        elif name == "tools":
            if not isinstance(value, Mapping) or any(type(v) is not bool for v in value.values()):
                raise ValueError("tools must map names to booleans")
        elif name == "permission":
            def check(v):
                if isinstance(v, Mapping):
                    for item in v.values(): check(item)
                elif not isinstance(v, str) or v not in {"allow", "deny", "ask"}: raise ValueError("Invalid permission action")
            check(value)
        elif name == "subagent_depth": integer(value, 0, 8, name)
        elif name == "default_agent":
            if not isinstance(value, str) or not value: raise ValueError("default_agent must be a name")
        elif name == "command":
            if not isinstance(value, Mapping): raise ValueError("command must be an object")
            for command in value.values():
                object_of(command, {"template", "agent", "description", "subtask"}, "command")
                if not isinstance(command.get("template"), str): raise ValueError("Command requires a template")
                for key, item in command.items():
                    if key == "subtask" and type(item) is not bool: raise ValueError("Command.subtask must be boolean")
                    if key != "subtask" and not isinstance(item, str): raise ValueError("Command values must be text")
        elif name in {"instructions", "plugin"}:
            if not isinstance(value, list): raise ValueError(name + " must be an array")
            if name == "instructions": strings(value, name)
            elif any(not isinstance(v, str) and not (isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], Mapping)) for v in value):
                raise ValueError("Plugin entries must be local paths or [path, options]")
        elif name == "skills":
            object_of(value, {"paths", "urls"}, name)
            for key, item in value.items(): strings(item, "skills." + key)
        elif name == "references":
            if not isinstance(value, Mapping): raise ValueError("references must be an object")
            for ref in value.values():
                object_of(ref, {"path", "description", "hidden"}, "local reference")
                if not isinstance(ref.get("path"), str): raise ValueError("References require a captured local directory; external repositories must be staged first")
                if "hidden" in ref and type(ref["hidden"]) is not bool: raise ValueError("references.hidden must be boolean")
                if "description" in ref and not isinstance(ref["description"], str): raise ValueError("references.description must be text")
        elif name == "mcp":
            if not isinstance(value, Mapping): raise ValueError("mcp must be an object")
            for server in value.values():
                object_of(server, {"type", "command", "environment", "enabled", "timeout", "url", "headers", "oauth"}, "MCP")
                if "enabled" in server and type(server["enabled"]) is not bool: raise ValueError("MCP.enabled must be boolean")
                if "timeout" in server: integer(server["timeout"], 1, 7_200_000, "MCP.timeout")
                for key in ("environment", "headers"):
                    if key in server and (not isinstance(server[key], Mapping) or any(not isinstance(v, str) for v in server[key].values())):
                        raise ValueError("MCP." + key + " must map names to text")
                if set(server) == {"enabled"} and type(server["enabled"]) is bool: continue
                if server.get("type") == "local":
                    if not isinstance(server.get("command"), list) or not server["command"] or any(not isinstance(v, str) for v in server["command"]):
                        raise ValueError("Local MCP requires an argv array")
                    if any(k in server for k in ("url", "headers", "oauth")): raise ValueError("Local MCP has remote-only fields")
                elif server.get("type") == "remote":
                    if not isinstance(server.get("url"), str): raise ValueError("Remote MCP requires a URL")
                    if server.get("oauth", False) is not False: raise ValueError("Interactive MCP OAuth must be provisioned outside the experiment")
                else: raise ValueError("MCP type must be local or remote")
        else:
            raise ValueError(f"Unsupported or fixed OpenCode candidate config field: {name}")


def inside(root, value, *, directory=False):
    path = Path(str(value))
    if not str(value) or path.is_absolute() or ".." in path.parts or "://" in str(value):
        raise ValueError("Candidate loading paths must be relative to the delivered workspace")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()) or not target.exists() or (directory and not target.is_dir()):
        raise ValueError(f"Candidate loading path is not delivered: {value}")
    return target


def candidate_config(home, project, manifest):
    config = load_json_configs([({"home": home, "project": project}[scope] / name) for scope, name in CONFIG_PATHS])
    config = deep_merge(config, {"agent": deep_merge(compile_opencode_agent_definitions(home), compile_opencode_agent_definitions(project)),
                                "command": deep_merge(compile_opencode_commands(home), compile_opencode_commands(project))})
    return apply_flat_config(config, manifest.get("config_patch") or {})


def relocate(config, *, home, project):
    config = copy.deepcopy(config)
    for name in ("instructions",):
        if name in config:
            config[name] = [str(inside(project, value)) for value in config[name]]
    if config.get("skills", {}).get("urls"):
        raise ValueError("Stage remote Skills as versioned files before running; the solver has no package/download credentials")
    if "skills" in config:
        config["skills"]["paths"] = [str(inside(project, value, directory=True)) for value in config["skills"].get("paths", [])]
    for reference in config.get("references", {}).values():
        reference["path"] = str(inside(project, reference["path"], directory=True))
    return config


def lower_tool_visibility(config):
    """Lower deprecated tools flags to native permission rules deterministically.

    V1 normalization prepends derived tool rules ahead of a global '*' rule;
    that ordering can accidentally re-enable disabled tools. Use the canonical
    permission representation while checking visibility against real requests.
    """
    def lower(item):
        visibility = item.pop("tools", {})
        if not visibility: return
        permission = item.get("permission", {})
        if isinstance(permission, str): permission = {"*": permission}
        permission = dict(permission)
        for name, enabled in visibility.items():
            name = "edit" if name in {"write", "edit", "patch"} else name
            if not enabled: permission[name] = "deny"
            else: permission.setdefault(name, "allow")
        item["permission"] = permission
    lower(config)
    for agent in config.get("agent", {}).values(): lower(agent)
    return config


def prepare_extensions(*, workspace, home, config, manifest, max_steps, policy=None):
    """Explicit isolated config dir prevents duplicate auto-loading and host config."""
    platform = workspace / ".runtime/native"
    platform.mkdir(parents=True, exist_ok=True)
    helpers = install_plugin_helpers(platform)
    install_plugin_helpers(workspace)
    install_plugin_helpers(workspace / ".runtime/platform-config/opencode")
    for name in ("tools",): (platform / name).mkdir(exist_ok=True)
    candidates = []
    for root in (home, workspace / ".opencode"):
        for directory in ("plugin", "plugins"):
            candidates.extend(sorted(p for p in (root / directory).glob("*") if p.suffix in {".js", ".ts", ".mjs"}))
        for directory in ("tool", "tools"):
            for path in sorted((root / directory).glob("*")):
                if path.suffix not in {".js", ".ts"}: continue
                target = platform / "tools" / path.name
                target.write_text(f"export * from {json.dumps(path.as_uri())};\nimport * as module from {json.dumps(path.as_uri())};\nexport default module.default;\n")
    for raw in config.get("plugin", []):
        spec = raw[0] if isinstance(raw, list) and len(raw) == 2 else raw
        if not isinstance(spec, str): raise ValueError("Plugin requires a captured local path")
        path = inside(workspace, spec)
        candidates.append(path)
    bridge = workspace / ".runtime/harnesslens"
    bridge.mkdir(parents=True, exist_ok=True)
    (bridge / "bridge.mjs").write_bytes(BRIDGE.read_bytes())
    plugin_specs = []
    for index, path in enumerate(dict.fromkeys(candidates)):
        wrapper = bridge / f"plugin-{index}.mjs"
        options = next((v[1] for v in config.get("plugin", []) if isinstance(v, list) and len(v) == 2 and inside(workspace, v[0]) == path), {})
        wrapper.write_text(f"import * as module from {json.dumps(path.as_uri())};\nimport {{wrapPluginModule}} from './bridge.mjs';\nexport default wrapPluginModule(module, {json.dumps(str(path.relative_to(workspace)))}, {json.dumps(options)});\n")
        plugin_specs.append(wrapper.as_uri())
    config["plugin"] = [*plugin_specs, (bridge / "bridge.mjs").as_uri()]
    settings = {"schema": "harnesslens.native-components.v1", "policy": policy_contract(policy=policy),
                "tool_patches": manifest.get("tool_desc_patches") or {}, "max_steps": max_steps,
                "plugins": [str(p.relative_to(workspace)) for p in dict.fromkeys(candidates)],
                "entry_command": ENTRY_COMMAND, "helper_root": str(helpers),
                "protected_files": [str((home if scope == "home" else workspace) / name)
                                    for scope, entries in declared_files(manifest).items() for name in entries]}
    (bridge / "settings.json").write_text(json.dumps(settings))
    config.setdefault("command", {}).setdefault(ENTRY_COMMAND, {"template": "$ARGUMENTS", "description": "Experiment task entry"})
    if "$ARGUMENTS" not in config["command"][ENTRY_COMMAND]["template"]:
        # A command may add guidance but cannot remove the benchmark question.
        config["command"][ENTRY_COMMAND]["template"] += "\n\n$ARGUMENTS"
    return platform


def refresh_report(report, workspace, api_trace):
    """Only native callbacks are runtime evidence; prepared files stay separate."""
    path = workspace / ".runtime/harnesslens/events.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []
    config_events = [e for e in events if e.get("kind") == "config_loaded"]
    compact = []
    repeated = {}
    for event in events:
        item = {k: v for k, v in event.items() if k not in {"config", "raw_tool_return", "output", "schema", "description"}}
        if item.get("kind") == "tool_definition": continue  # Actual schemas live in API trace/tool_definitions.
        if item.get("kind") == "native_event":
            raw_event = item["event"]
            info = (raw_event.get("properties") or {}).get("info")
            if isinstance(info, dict):
                item["event"] = {"type": raw_event["type"], "properties": {"info": {k: info[k] for k in ("id", "parentID") if k in info}}}
        if item.get("kind") in {"plugin_hook", "native_event", "system_transform"}:
            key = (item.get("kind"), item.get("source"), item.get("hook"), item.get("tool"), item.get("session_id"), json.dumps(item.get("event", {}), sort_keys=True))
            if key in repeated:
                compact[repeated[key]]["n_calls"] = compact[repeated[key]].get("n_calls", 1) + 1
                continue
            repeated[key] = len(compact)
        compact.append(item)
    report.update(native_component_events=compact, component_policy=report.get("component_policy") or policy_contract(),
                  effective_config=config_events[-1]["config"] if config_events else {},
                  verification_level="runtime_callbacks" if config_events else "prepared_files_only")
    tools = {}
    if api_trace.is_file():
        for line in api_trace.read_text().splitlines():
            entry = json.loads(line)
            for raw in (entry.get("request") or {}).get("tools", []):
                value = raw.get("function", raw)
                if isinstance(value, dict) and value.get("name"): tools[value["name"]] = value
    report["tool_definitions"] = list(tools.values())
    for field in ("candidate_files", "candidate_project_files"):
        for item in report.get(field, []):
            if item.get("path") in {"opencode.json", "config.json", ".opencode/opencode.json"}:
                config = json.loads(item["content"])
                config.pop("provider", None)
                item["content"] = json.dumps(config)
    report["native_evidence"] = {"events_path": str(path), "events_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                                 "model_request_evidence": bool(tools)}
    failures = [e.get("error", "native component failed") for e in events if e.get("kind") in {"component_error", "policy_violation"}]
    if not config_events: failures.append("Native component observer did not load")
    return failures


def prepare_received_harness(*, workspace, harness_files, fixed_config, tool_patches=None, max_steps=40, component_policy=None):
    """Receiver helper for either a Python function or HTTP service.

    Call per isolated request workspace before starting OpenCode. The business
    service supplies its own fixed model/provider config and tools/data sandbox.
    Returns only launch overrides; it never changes the service's global files.
    """
    from .harness_workspace import materialize_workspace, normalize_workspace_snapshot
    from .channel_preflight import build_runtime_load_report
    from .component_policy import receiver_policy
    policy = receiver_policy(component_policy)
    workspace = Path(workspace).resolve()
    home = workspace / ".runtime/candidate-home"
    snapshot = normalize_workspace_snapshot({"files": [
        {"scope": scope, "path": name, "content": content}
        for scope, entries in harness_files.items() for name, content in entries.items()]})
    manifest = {"_workspace": snapshot, "tool_desc_patches": tool_patches or {}}
    validate_manifest(manifest, max_steps=max_steps, policy=policy)
    materialize_workspace(snapshot, home_root=home, project_root=workspace)
    config = relocate(candidate_config(home, workspace, manifest), home=home, project=workspace)
    if "model" not in fixed_config or "provider" not in fixed_config:
        raise ValueError("Receiver must provide its fixed model/provider configuration")
    config = deep_merge({"agent": {"build": {"steps": max_steps}}, "permission": {"*": "allow", "question": "deny"},
                         "compaction": {"auto": False, "prune": False}}, config)
    config = deep_merge(config, fixed_config)
    instructions = [str(workspace / "AGENTS.md")] if (workspace / "AGENTS.md").is_file() else []
    config["instructions"] = list(dict.fromkeys([*instructions, *config.get("instructions", [])]))
    for folder in (home / "skills", workspace / ".opencode/skills"):
        if folder.is_dir(): config.setdefault("skills", {}).setdefault("paths", []).append(str(folder))
    lower_tool_visibility(config)
    platform = prepare_extensions(workspace=workspace, home=home, config=config, manifest=manifest, max_steps=max_steps, policy=policy)
    (workspace / "opencode.json").write_text(json.dumps(config))
    environment = {"OPENCODE_CONFIG": str(workspace / "opencode.json"), "OPENCODE_CONFIG_CONTENT": json.dumps(config),
                   "OPENCODE_CONFIG_DIR": str(platform), "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
                   "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
                   "XDG_CONFIG_HOME": str(workspace / ".runtime/platform-config"), "HOME": str(workspace / ".runtime/home"),
                   "XDG_DATA_HOME": str(workspace / ".runtime/data"), "XDG_CACHE_HOME": str(workspace / ".runtime/cache"),
                   "XDG_STATE_HOME": str(workspace / ".runtime/state"), "TMPDIR": str(workspace / ".runtime/tmp")}
    for name in ("home", "data", "cache", "state", "tmp"): (workspace / ".runtime" / name).mkdir(exist_ok=True)
    report = build_runtime_load_report(harness="opencode", project_root=workspace, home_root=home, manifest=manifest, tool_definitions=[])
    report["component_policy"] = policy_contract(policy=policy)
    return {"environment": environment, "config": config, "report": report,
            "command_arguments": ["run", "--format", "json", "--dir", str(workspace), "--command", ENTRY_COMMAND]}
