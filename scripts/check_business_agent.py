#!/usr/bin/env python3
"""Validate an adapter config, or explicitly execute one supplied prompt."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harnesslens.core.config import load_repo_env
from harnesslens.harnesses.business_agent import load_config, invoke
from harnesslens.harnesses.native_harness_driver import stable_hash
from harnesslens.harnesses.opencode_components import protocol_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--prompt", help="When supplied, make one real business-agent call")
    parser.add_argument("--harness-dir", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/business-agent-check")
    args = parser.parse_args()
    load_repo_env(ROOT)
    config = load_config(args.config)
    if args.prompt is None:
        print(json.dumps({"type": config["agent"]["type"], "name": config["agent"]["name"],
            "channels": config["capabilities"]["channels"], "model_request_evidence_configured": bool(config["agent"]["api_calls_path"] or config.get("trace")),
            "executed": False}, ensure_ascii=False, indent=2))
        return 0
    if not args.harness_dir or not args.harness_dir.is_dir():
        parser.error("--prompt execution requires an existing --harness-dir")
    source = args.harness_dir.resolve()
    if any(p.is_symlink() for p in source.rglob("*")):
        parser.error("Harness files cannot contain symlinks")
    files = {"project": {str(p.relative_to(source)): p.read_text() for p in source.rglob("*") if p.is_file()}, "home": {}}
    instructions = files["project"].get("AGENTS.md", "")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be empty; previous calls are retained")
    delivered = output / "harness/project"
    delivered.mkdir(parents=True)
    for name, content in files["project"].items():
        path = delivered / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    context = {"prompt": instructions + "\n\n" + args.prompt, "instructions": instructions,
        "harness_files": files, "harness_dir": str(delivered), "harness_digest": stable_hash(files), "workspace": str(output),
        "harness_version": "adapter-check", "component_protocol": protocol_manifest(),
        "task": {"query": args.prompt}, "task_id": "adapter-check", "scope": "CHECK", "model": config["agent"]["name"],
        "seed": 0, "steps": 40, "timeout": config["agent"]["timeout"],
        "request_id": stable_hash({"task": args.prompt, "harness": files, "agent": config["agent"]}), "trial_id": "adapter-check"}
    result = invoke(config, context, output)
    print(json.dumps({"answer": result["answer"], "usage": result["usage"], "executed": True,
                      "model_request_evidence": bool(result["api_calls"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
