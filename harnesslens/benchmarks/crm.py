"""DataAgentBench CRMarenapro: public tasks and host-only official grading.

The checkout is external and read-only. No Harness2 or RRSI package is imported.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

TASK_IDS = tuple(f"crmarenapro/query{i}" for i in range(1, 14))
DATABASE_FILES = ("core_crm.db", "sales_pipeline.duckdb", "support.sql",
                  "products_orders.db", "activities.duckdb", "territory.db")
PG_DATABASE = "h2_crm_support_v1"
PG_READER = "h2_crm_reader"


def checkout(repo_root: str | Path) -> Path:
    return Path(os.environ.get("HAI_DAB_ROOT") or Path(repo_root) / "third_party/dataagentbench").resolve()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dataset_root(repo_root: str | Path) -> Path:
    return checkout(repo_root) / "query_crmarenapro"


def load_tasks(repo_root: str | Path) -> dict[str, dict]:
    root = dataset_root(repo_root)
    tasks = {}
    for tid in TASK_IDS:
        value = json.loads((root / tid.split("/")[1] / "query.json").read_text())
        tasks[tid] = {"task_id": tid, "query": value}
    return tasks


def data_fingerprint(repo_root: str | Path) -> dict:
    root = dataset_root(repo_root)
    files = {str(p.relative_to(root)): sha(p) for p in (
        root / "db_description.txt",
        *(root / "query_dataset" / name for name in DATABASE_FILES),
        *(root / f"query{i}" / name for i in range(1, 14) for name in ("query.json", "validate.py")),
    )}
    manifest = checkout(repo_root) / "dataset_manifest.tsv"
    expected = {}
    for line in manifest.read_text().splitlines():
        name, digest, size = line.split("\t")
        if name.startswith("query_crmarenapro/query_dataset/"):
            relative = name.removeprefix("query_crmarenapro/")
            if files.get(relative) != digest or (root / relative).stat().st_size != int(size):
                raise ValueError(f"CRM data differs from pinned manifest: {relative}")
            expected[Path(name).name] = digest
    if set(expected) != set(DATABASE_FILES):
        raise ValueError("CRM manifest must identify all six data sources")
    files["dataset_manifest.tsv"] = sha(manifest)
    return files


def grade(repo_root: str | Path, task_id: str, answer: str) -> dict:
    if task_id not in TASK_IDS:
        raise ValueError("unknown CRM task")
    path = dataset_root(repo_root) / task_id.split("/")[1] / "validate.py"
    spec = importlib.util.spec_from_file_location("crm_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    passed, reason = module.validate(answer)
    return {"reward": float(bool(passed)), "validator_sha256": sha(path), "reason": str(reason)}


def public_explorer_input(repo_root: str | Path, task_ids) -> dict:
    tasks = load_tasks(repo_root)
    payload = {
        "scope": "TRAIN", "domain": "crmarenapro", "benchmark_kind": "crm",
        "tasks": [tasks[tid] for tid in task_ids],
        "environment": {
            "database_descriptions": (dataset_root(repo_root) / "db_description.txt").read_text(),
            "tools": [],
            "tool_transport": {"kind": "cli", "commands": [
                "python source/query.py schema DATABASE",
                "python source/query.py sql DATABASE SQL [--limit N]",
            ]},
            "runtime_contract": {},
        },
        "forbidden_inputs": ["grader", "reference_answer", "ground_truth", "TEST tasks"],
    }
    from harnesslens.harnesses.business_agent import load_config
    business = load_config()
    from harnesslens.harnesses.opencode_components import runtime_contract
    native_loader = {
        "config_loading": "Candidate JSON and captured workspace files are loaded before native OpenCode starts.",
        "implemented_lane": "Instructions, native prompt, Skill, and prompt-only Subagent files.",
        "fixed_config": ["model", "small_model", "provider", "mcp", "plugin", "tools", "permission", "agent.*.steps", "agent.*.tools", "agent.*.permission"],
        "disabled_features": ["automatic compaction", "pruning", "executable plugins", "custom tools"],
        "tool_transport": "Fixed read-only SQL CLI, without a schema-patch bridge.",
    }
    payload["environment"]["runtime_contract"] = runtime_contract(business=business, loader_facts=None if business else native_loader)
    if business:
        payload["environment"]["runtime_contract"].update(
            business_agent={"type": business["agent"]["type"], "name": business["agent"]["name"],
                            "model_request_evidence_configured": bool(business["agent"]["api_calls_path"] or business.get("trace"))},
            note="Candidates are delivered to an existing business agent. Only its declared channels may be edited; actual model-request evidence is required to pass channel preflight.")
    return payload
