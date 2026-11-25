#!/usr/bin/env python3
"""CRM environment check or a single TRAIN-task smoke test; no evolution launch."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harnesslens.core.config import load_repo_env
from harnesslens.core.artifacts import write_json
from harnesslens.benchmarks.crm_eval import runtime_fingerprint, prepare_task, sandbox_command
from harnesslens.benchmarks.crm_postgres import ReadOnlyPostgresProxy
from harnesslens.evaluation.rollout_bridge import CellHarnessRepository, TrainRolloutService, RolloutRequest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="crm-smoke-01")
    parser.add_argument("--agent-config", type=Path, help="Python/HTTP adapter TOML")
    parser.add_argument("--smoke", action="store_true", help="One real query1 trial, optionally with a candidate")
    parser.add_argument("--probe-candidate", action="store_true", help="Also execute query1 with an instruction sentinel")
    args = parser.parse_args()
    load_repo_env(ROOT)
    from harnesslens.harnesses.business_agent import select_config
    select_config(args.agent_config)
    root = ROOT / "runs/crm_checks" / args.run_id
    root.mkdir(parents=True, exist_ok=True)
    signature = runtime_fingerprint(ROOT)
    write_json(root / "environment.json", signature)
    workspace = root / "preflight/workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    with ReadOnlyPostgresProxy() as proxy:
        if not (workspace / "source").exists():
            prepare_task(ROOT, workspace, "crmarenapro/query1", proxy.port)
        else:
            # A resumed preflight gets a fresh restricted proxy port.
            import shutil
            shutil.rmtree(workspace / "source")
            shutil.rmtree(workspace / "output")
            prepare_task(ROOT, workspace, "crmarenapro/query1", proxy.port)
        probes = {}
        for name in json.loads((workspace / "source/connections.json").read_text()):
            command = sandbox_command([sys.executable, "source/query.py", "schema", name], workspace, [proxy.port])
            result = subprocess.run(command, cwd=workspace, text=True, capture_output=True, timeout=30)
            if result.returncode or not json.loads(result.stdout)["rows"]:
                raise RuntimeError(f"CRM schema preflight failed for {name}: {result.stderr[-400:]}")
            probes[name] = "readable"
        for name, code in {
            "validator_read": f"open({str(ROOT / 'third_party/dataagentbench/query_crmarenapro/query1/validate.py')!r}).read()",
            "source_write": "open('source/data/core_crm.db','ab').write(b'bad')",
            "admin_port": "import socket;socket.create_connection(('127.0.0.1',55432),1)",
            "postgres_write": f"import psycopg2;c=psycopg2.connect(host='127.0.0.1',port={proxy.port},user='h2_crm_reader',dbname='h2_crm_support_v1');c.autocommit=True;c.cursor().execute('CREATE TABLE forbidden_probe(x int)')",
        }.items():
            result = subprocess.run(sandbox_command([sys.executable, "-c", code], workspace, [proxy.port]),
                                    cwd=workspace, capture_output=True, timeout=10)
            if result.returncode == 0:
                raise RuntimeError(f"CRM isolation probe unexpectedly succeeded: {name}")
            probes[name] = "denied"
    write_json(root / "preflight.json", probes)
    print(json.dumps({"preflight": probes, "tasks": 13, "train": 10, "test": 3}, ensure_ascii=False), flush=True)
    if not args.smoke:
        return 0
    from harnesslens.core.model_config import task_models
    task_models(business=bool(args.agent_config))
    repository = CellHarnessRepository(cell="crmarenapro", repo_root=ROOT, run_id=args.run_id,
                                       evidence_root=root / "evidence", harness="opencode")
    versions = ["v0"]
    if args.probe_candidate:
        versions.append(repository.materialize_workspace_candidate(base_version="v0", candidate_label="instruction-probe",
                        workspace={"files": [{"scope": "project", "path": "AGENTS.md", "content":
                            "HarnessLens CRM integration marker: CRM_HARNESS_DELIVERY_PROBE. Use the provided sources to answer the task.\n"}]}))
    results = {}
    for version in versions:
        service = TrainRolloutService(cell="crmarenapro", repo_root=ROOT, run_id=args.run_id,
            artifact_root=root / "artifacts", train_task_ids=["crmarenapro/query1"], initial_budget=1,
            evidence_root=root / "evidence", workspace_root=root / "workspaces", local_rootless_rollout=False)
        response = service.run(RolloutRequest(request_id=f"smoke-{version}", run_id=args.run_id,
            scope="TRAIN", harness_version=version, task_repeats={"crmarenapro/query1": 1},
            max_concurrency=1, purpose="CRM integration smoke", pairing_offsets={"crmarenapro/query1": 0}))
        results[version] = response.to_dict()
        if version == "instruction-probe":
            path = Path(response.records[0].trajectory_paths[0])
            row = json.loads(path.read_text())
            trace = Path(row["api_calls_jsonl"])
            if not trace.is_absolute():
                trace = path.parent / trace
            events = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
            if not any("CRM_HARNESS_DELIVERY_PROBE" in json.dumps(e.get("request", {})) for e in events):
                raise RuntimeError("Candidate instruction was absent from actual provider requests")
            results[version]["candidate_delivery_verified"] = True
        print(json.dumps({"version": version, "metrics": response.metrics}, ensure_ascii=False), flush=True)
    write_json(root / "smoke_result.json", results)
    if signature != runtime_fingerprint(ROOT):
        raise RuntimeError("Shared CRM data or runtime changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
