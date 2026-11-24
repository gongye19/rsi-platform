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
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime_sources():
    return tuple(str(Path(__file__).resolve().parents[1] / name) for name in (
        "benchmarks/adapters.py", "benchmarks/jsonl_adapter.py", "benchmarks/grader_worker.py", "evaluation/business_runtime.py",
        "benchmarks/cell_config.py", "benchmarks/benchmark_splits.py", "evaluation/rollout_bridge.py",
        "harnesses/business_agent.py", "harnesses/business_worker.py", "harnesses/opencode_components.py",
        "harnesses/candidate_config_runtime.py", "harnesses/native_candidate_runtime.py",
        "harnesses/harness_workspace.py", "harnesses/harness_manifest.py", "harnesses/channel_preflight.py",
        "infrastructure/process_isolation.py", "evaluation/rollout_outcome.py"))


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


class CrmAdapter(BusinessBenchmark):
    cell = "crmarenapro"

    def __init__(self, repo_root):
        self.repo_root = Path(repo_root).resolve()

    def split(self):
        from .benchmark_splits import load_benchmark_split
        return load_benchmark_split("crm")

    def explorer_input(self, task_ids):
        from .crm import public_explorer_input
        return public_explorer_input(self.repo_root, task_ids)

    def fingerprint(self):
        from .crm_eval import runtime_fingerprint
        return runtime_fingerprint(self.repo_root)

    def limits(self):
        from .crm_eval import effective_limits
        return effective_limits()

    def target_model(self):
        from .crm_eval import model
        return model()

    def public_task(self, task_id):
        from .crm import load_tasks
        return load_tasks(self.repo_root)[task_id]

    def prepare_task(self, workspace, task_id, resources):
        from .crm_eval import prepare_task
        from .crm import dataset_root
        from .crm_postgres import pg_port
        return {"prompt": prepare_task(self.repo_root, workspace, task_id, resources["pg_port"]),
                "private_roots": [str(dataset_root(self.repo_root))], "private_ports": [pg_port()]}

    def grade(self, task_id, answer):
        from .crm import grade
        return grade(self.repo_root, task_id, answer)

    def execution_context(self):
        from contextlib import contextmanager
        from .crm_postgres import ReadOnlyPostgresProxy
        @contextmanager
        def start():
            with ReadOnlyPostgresProxy() as proxy:
                yield {"pg_port": proxy.port}
        return start()

    def baseline_fields(self, harness):
        from .crm_eval import model
        if harness != "opencode":
            raise ValueError("The configured native runtime supports OpenCode only")
        return {"target_model": model(), "user_model": None,
                "benchmark_environment": self.fingerprint(), "rollout": self.limits().to_dict()}

    def run_batch(self, **kwargs):
        from harnesslens.harnesses.business_agent import load_config
        if load_config():
            return super().run_batch(**kwargs)
        from .crm_eval import run_crm_batch
        return run_crm_batch(repo_root=self.repo_root, **kwargs)


def benchmark_adapter(repo_root, cell):
    if str(cell) in {"crm", "crmarenapro", "dab-crmarenapro"}:
        return CrmAdapter(repo_root)
    from .jsonl_adapter import resolve_external
    return resolve_external(repo_root, cell)
