"""Convert real run artifacts into the existing method-independent UI contract."""
import hashlib
import json
import re
from pathlib import Path

from .config import ROOT, run_id
from harnesslens.harnesses.opencode_components import COMPONENTS, config_component, config_leaves


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def history(identity):
    run_id(identity)
    root = ROOT / "runs/train" / identity
    known, versions, bundles, steps = {}, [], [], []
    components = []
    for key, name in COMPONENTS:
        bid = key + "_baseline"
        known[(key, "baseline")] = bid
        components.append({"id": key, "name": name, "description": name, "baseline_version_id": bid})
        versions.append({"id": bid, "component_id": key, "label": "H0", "parent_id": None,
            "step": 0, "round": 0, "digest": "baseline", "present": False, "files": [], "notes": "初始配置"})
    current = {key: key + "_baseline" for key, _ in COMPONENTS}
    bundles.append({"id": "v0", "label": "H0", "step": 0, "round": 0, "components": dict(current),
                    "execution": {"status": "baseline"}, "metrics": {}})
    steps.append({"index": 0, "round": 0, "label": "初始版本", "kind": "baseline", "bundle_id": "v0", "active_bundle_id": "v0"})
    snapshots = sorted(root.glob("rollout_evidence/**/versions_percell/*/*/harness/opencode/workspace.json"), key=lambda p: p.stat().st_mtime_ns)
    bundle_components = {"v0": dict(current)}
    final = read(root / "submission/final.json", {})
    recorded = {row["candidate_version"]: row for row in final.get("iteration_history", []) if row.get("candidate_version")}
    # Until final publication, read the controller's actual persisted reviews.
    for decision in sorted((root / "main_agent").glob("iteration-*.json")):
        match = re.fullmatch(r"iteration-(\d+)", decision.stem)
        row = read(decision, {})
        if not match or not row.get("harness_version"):
            continue
        label = decision.stem
        review = read(root / "main_agent" / (label + "-confirmation-review.json")) or read(root / "main_agent" / (label + "-review.json"), {})
        recorded.setdefault(row["harness_version"], {"iteration": int(match[1]), "selected_version": review.get("selected_version")})
    seen = {"v0"}
    metrics = {}
    for record in sorted((root / "rollout").glob("*.json")):
        payload = read(record, {})
        if payload.get("harness_version"):
            metrics[payload["harness_version"]] = {key: value for key, value in payload.get("metrics", {}).items() if type(value) in {int, float}}
    for index, path in enumerate(snapshots, 1):
        snapshot = path.parents[2]
        version = snapshot.name
        if version in seen:
            continue
        seen.add(version)
        record = recorded.get(version, {})
        # Unmapped snapshots share one unresolved group. Their mere creation
        # cannot be treated as proof of a completed/adopted optimizer round.
        round_number = record.get("iteration", 1)
        step_index = len(steps)
        lineage = read(snapshot / "lineage.json", {})
        parent = bundle_components.get(lineage.get("parent"), bundle_components["v0"])
        grouped = {key: [] for key, _ in COMPONENTS}
        workspace = read(path, {"files": []})
        for item in workspace.get("files", []):
            name, content = item["path"], item["content"]
            if name.endswith("opencode.json"):
                for field, value in config_leaves(read_text_json(content)):
                    owner = config_component(field)
                    if owner in grouped:
                        grouped[owner].append({"path": name + "#" + field, "content": json.dumps(value, ensure_ascii=False)})
            else:
                owner = ("skills" if "/skills/" in name else "agent_definitions" if "/agents/" in name else
                         "commands" if "/commands/" in name else "plugin_tool_system" if "/plugins/" in name else
                         "custom_tools" if "/tools/" in name else "instructions_rules" if name == "AGENTS.md" else "reference_sources")
                grouped[owner].append({"path": name, "content": content})
        manifest = read(path.with_name("manifest.json"), {})
        for text in [*manifest.get("instructions", []), *manifest.get("prompt_appends", [])]:
            grouped["instructions_rules"].append({"path": "manifest/instructions", "content": text})
        active = {}
        for key, _ in COMPONENTS:
            data = sorted(grouped[key], key=lambda item: (item["path"], item["content"]))
            digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() if data else "baseline"
            vid = known.get((key, digest))
            if vid is None:
                vid = key + "_" + digest[:16]
                known[key, digest] = vid
                versions.append({"id": vid, "component_id": key, "label": version, "parent_id": parent[key],
                    "step": step_index, "round": round_number, "digest": digest, "present": bool(data),
                    "files": [{"path": item["path"], "change": "snapshot", "diff": item["content"]} for item in data],
                    "notes": "真实配置快照；整包采用不等于单组件独立验证"})
            active[key] = vid
        current = active
        bundle_components[version] = dict(active)
        bundles.append({"id": version, "label": version, "step": step_index, "round": round_number,
            "components": active, "execution": {"status": (read(snapshot / "meta.json", {}) or {}).get("status", "candidate")}, "metrics": metrics.get(version, {})})
        steps.append({"index": step_index, "round": round_number, "label": version, "kind": "candidate", "bundle_id": version})
        selected = record.get("selected_version")
        if selected in bundle_components:
            steps.append({"index": len(steps), "round": round_number, "label": "记录中的整包选择", "kind": "select", "active_bundle_id": selected})
    selected = final.get("selected_version")
    if selected and any(bundle["id"] == selected for bundle in bundles):
        steps.append({"index": len(steps), "round": steps[-1]["round"], "label": "最终冻结版本", "kind": "select", "active_bundle_id": selected})
    return {"schema_version": "1.0", "id": identity, "title": identity, "algorithm": "HarnessLens",
        "source": "historical", "notice": "真实实验记录。组件快照不代表单组件独立收益。",
        "profile": {"id": "opencode-1.18.32", "runtime": "OpenCode", "version": "1.18.32"},
        "context": {}, "components": components, "versions": versions, "bundles": bundles, "steps": steps, "decisions": []}


def read_text_json(text):
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}
