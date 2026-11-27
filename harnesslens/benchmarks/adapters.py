"""Benchmark extension boundary. Optimizers consume this contract, not task names.

Existing native benchmark implementations remain available. New business-agent
benchmarks supply public inputs, preparation, host grading and fingerprints here.
"""
from __future__ import annotations
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
import hashlib
import json


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def runtime_sources():
    return tuple(str(Path(__file__).resolve().parents[1] / name) for name in (
        "core/model_config.py", "core/model_trace.py", "core/model_trace.py", "benchmarks/adapters.py", "benchmarks/jsonl_adapter.py", "benchmarks/grader_worker.py", "evaluation/business_runtime.py",
        "benchmarks/cell_config.py", "benchmarks/benchmark_splits.py", "benchmarks/selection.py", "evaluation/rollout_bridge.py",
        "harnesses/business_agent.py", "harnesses/business_worker.py", "harnesses/opencode_components.py",
        "harnesses/candidate_config_runtime.py", "harnesses/native_candidate_runtime.py",
        "harnesses/harness_workspace.py", "harnesses/initial_harness.py", "harnesses/harness_manifest.py", "harnesses/channel_preflight.py",
        "harnesses/component_policy.py", "harnesses/component_preflight.py", "harnesses/opencode_execution.py", "harnesses/opencode_bridge.mjs",
        "../configs/opencode-plugin-runtime.json", "../assets/opencode-plugin-runtime-1.18.32.tar.gz",
        "infrastructure/batch_progress.py", "infrastructure/process_isolation.py", "infrastructure/trace_watch.py", "evaluation/rollout_outcome.py"))


@dataclass(frozen=True)
class BusinessLimits:
    max_steps: int = 40
    timeout_s: float = 600
    output_tokens: int = 8192

    def to_dict(self):
        from dataclasses import asdict
        return asdict(self)


class BenchmarkAdapter(Protocol):
    cell: str
    def split(self): ...
    def explorer_input(self, task_ids): ...
    def fingerprint(self): ...
    def limits(self): ...
    def prepare_task(self, workspace, task_id, resources): ...
    def public_task(self, task_id): ...
    def grade(self, task_id, answer): ...
    def execution_context(self): ...
    def run_batch(self, **kwargs): ...
    def baseline_fields(self, harness): ...
    def validate_retained(self, records): ...


class BusinessBenchmark:
    """Reusable lifecycle for a benchmark driving an existing Python/HTTP agent."""
    max_concurrency = 2

    def target_model(self):
        from harnesslens.harnesses.business_agent import load_config
        business = load_config()
        if not business:
            raise ValueError("This benchmark requires --agent-config")
        return business["agent"]["name"]

    def limits(self):
        from harnesslens.harnesses.business_agent import load_config
        agent = load_config()
        return BusinessLimits(timeout_s=agent["agent"]["timeout"] if agent else 600)

    def execution_context(self):
        return nullcontext({})

    def loading_contract(self):
        from harnesslens.harnesses.business_agent import load_config
        from harnesslens.harnesses.opencode_components import runtime_contract
        business = load_config()
        result = runtime_contract(business=business)
        if business:
            result["business_agent"] = {"type": business["agent"]["type"], "name": business["agent"]["name"],
                "model_request_evidence_configured": bool(business["agent"]["api_calls_path"] or business.get("trace"))}
        return result

    def baseline_fields(self, harness):
        from harnesslens.harnesses.business_agent import load_config
        business = load_config()
        if harness != "opencode" or not business:
            raise ValueError("This benchmark adapter requires an OpenCode business agent via --agent-config")
        return {"target_model": business["agent"]["name"], "user_model": None,
                "benchmark_environment": self.fingerprint(), "rollout": self.limits().to_dict()}

    def run_batch(self, **kwargs):
        from harnesslens.evaluation.business_runtime import run_business_batch
        return run_business_batch(adapter=self, **kwargs)

    def validate_retained(self, records):
        from harnesslens.evaluation.business_runtime import validate_record
        expected = self.fingerprint()
        for record in records:
            for reference in record.trajectory_paths:
                path = Path(reference)
                row = json.loads(path.read_text())
                if row.get("environment_fingerprint") != expected:
                    raise ValueError("Cached benchmark or agent environment changed; choose a new run-id")
                if row.get("agent_transport") in {"python", "http"}:
                    validate_record(row, path)
                elif row.get("api_trace_sha256") != sha(path.parent / row["api_calls_jsonl"]):
                    raise ValueError("Cached provider trace changed")


def benchmark_adapter(repo_root, cell):
    if str(cell) in {"fdabench", "fdabench-lite-report"}:
        from .fdabench.adapter import FDABenchAdapter
        return FDABenchAdapter(repo_root)
    from .jsonl_adapter import resolve_external
    return resolve_external(repo_root, cell)
