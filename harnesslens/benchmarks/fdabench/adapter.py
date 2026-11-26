"""Native FDABench-Lite report adapter, selected as --cell fdabench."""

from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import threading
from harnesslens.benchmarks.adapters import (
    BusinessBenchmark,
    BusinessLimits,
    sha,
    runtime_sources,
)
from .data import tasks

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = """Use the fixed task-scoped CLI tools:
python source/client.py schema
python source/client.py sql "SELECT ..." --limit 200
python source/client.py document_search "keywords" --limit 5
python source/client.py document_read "category/file.pdf" --page 1
python source/client.py web_search "query"
SQL is read-only, limited to the specified database, 1000 rows and 20 seconds.
Documents cover the complete 1418-PDF corpus using page-aware FTS5 BM25 lexical retrieval (not PageIndex or FAISS).
Web search uses the configured live backend, at most 15 calls per execution. Cite URLs and PDF paths/pages.
Inspect schema. Preserve units, time windows and denominators. State unsupported claims and missing evidence.
Produce the requested complete analytical report; save it to output/answer.txt and return the same final response.
"""
_HASHES = {}
_LOCK = threading.Lock()


def cached_sha(path):
    path = Path(path).resolve()
    stat = path.stat()
    key = (
        str(path),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )
    with _LOCK:
        if key not in _HASHES:
            _HASHES[key] = sha(path)
        return _HASHES[key]


def asset_manifest(repo_root=ROOT):
    return json.loads((Path(repo_root) / "configs/fdabench-assets.json").read_text())


class FDABenchAdapter(BusinessBenchmark):
    cell = "fdabench"

    def __init__(self, repo_root):
        self.repo_root = Path(repo_root).resolve()
        self.data_root = (
            Path(
                os.environ.get(
                    "HAI_FDABENCH_ROOT",
                    str(self.repo_root / "third_party/fdabench-lite-report"),
                )
            )
            .expanduser()
            .resolve()
        )
        self.index = (
            Path(
                os.environ.get(
                    "HAI_FDABENCH_INDEX",
                    str(self.repo_root / "runs/fdabench-assets/documents.sqlite"),
                )
            )
            .expanduser()
            .resolve()
        )
        self.outputs = (
            Path(
                os.environ.get(
                    "HAI_FDABENCH_ARTIFACTS", str(self.repo_root / "runs/fdabench")
                )
            )
            .expanduser()
            .resolve()
        )
        self._tasks = None
        self._judge = None
        self._judge_lock = threading.Lock()

    @property
    def max_concurrency(self):
        cap = int(os.environ.get("HAI_FDABENCH_MAX_CONCURRENCY", "8"))
        if not 1 <= cap <= 64:
            raise ValueError("HAI_FDABENCH_MAX_CONCURRENCY must be 1..64")
        return cap

    def task_map(self):
        if self._tasks is None:
            self._tasks = tasks(self.data_root)
        return self._tasks

    def split(self):
        from harnesslens.benchmarks.benchmark_splits import load_benchmark_split

        return load_benchmark_split(self.cell)

    def benchmark_config(self):
        from harnesslens.benchmarks.cell_config import benchmark_config

        return benchmark_config(self.repo_root, self.cell)

    def limits(self):
        timeout = int(os.environ.get("HAI_FDABENCH_TIMEOUT_S", "900"))
        if not 30 <= timeout <= 7200:
            raise ValueError("HAI_FDABENCH_TIMEOUT_S must be 30..7200")
        return BusinessLimits(timeout_s=timeout)

    def target_model(self):
        from harnesslens.core.model_config import connection

        return connection("execution")["model"]

    def public_task(self, task_id):
        raw = self.task_map()[task_id]
        return {
            k: raw[k]
            for k in (
                "task_id",
                "db",
                "query",
                "level",
                "question_type",
                "tools_available",
            )
            if k in raw
        }

    def explorer_input(self, task_ids):
        if set(task_ids) - set(self.split().train):
            raise ValueError("Explorer may only receive TRAIN tasks")
        from harnesslens.harnesses.opencode_components import runtime_contract

        return {
            "benchmark_kind": "fdabench",
            "cell": self.cell,
            "tasks": [self.public_task(t) for t in task_ids],
            "environment": {
                "tool_transport": {"kind": "cli", "contract": CONTRACT},
                "runtime_contract": runtime_contract(),
                "retriever": "full-corpus 1418-PDF FTS5 BM25; live configured web search; tool identities and sources are fixed",
            },
            "forbidden_inputs": [
                "grader",
                "reference_answer",
                "rubric",
                "reference_sql",
                "construction_retrieval",
                "TEST tasks",
            ],
        }

    def _resources(self):
        manifest = asset_manifest(self.repo_root)
        database_receipt = []
        for item in manifest["databases"]:
            path = self.data_root / item["local_path"]
            if (
                path.stat().st_size != item["bytes"]
                or cached_sha(path) != item["sha256"]
            ):
                raise ValueError("FDABench database missing or changed: " + item["db"])
            database_receipt.append({"db": item["db"], "sha256": item["sha256"]})
        verified_path = self.data_root / "metadata/verified-assets.json"
        verified = json.loads(verified_path.read_text())
        if (
            verified.get("assets_sha256")
            != sha(self.repo_root / "configs/fdabench-assets.json")
            or verified.get("tasks_sha256")
            != cached_sha(self.data_root / "tasks/tasks.jsonl")
            or verified.get("references_sha256")
            != cached_sha(self.data_root / "evaluation/references.jsonl")
        ):
            raise ValueError("Run FDABench prepare to verify pinned assets")
        receipt_path = self.index.with_name("index.json")
        receipt = json.loads(receipt_path.read_text())
        if (
            receipt.get("pdf_count") != 1418
            or receipt.get("indexed_pdf_count") != 1418
            or receipt.get("index_sha256") != cached_sha(self.index)
        ):
            raise ValueError(
                "Build and verify the full FDABench document index before starting"
            )
        listing = json.loads(
            (self.data_root / "metadata/corpus_file_listing.json").read_text()
        )
        if len([e for e in listing if e["path"].lower().endswith(".pdf")]) != 1418:
            raise ValueError("Full corpus listing required")
        if receipt.get("corpus_listing_sha256") != cached_sha(
            self.data_root / "metadata/corpus_file_listing.json"
        ) or receipt.get("verified_assets_sha256") != cached_sha(verified_path):
            raise ValueError("Index is not bound to the verified asset manifest")
        # Index input identity includes the listing; its source PDFs are checked when prepare runs.
        return {
            "databases": database_receipt,
            "index": receipt,
            "corpus_listing": cached_sha(
                self.data_root / "metadata/corpus_file_listing.json"
            ),
        }

    def _get_judge(self):
        from .judge import Judge

        with self._judge_lock:
            if self._judge is None:
                self._judge = Judge(
                    self.data_root, self.outputs / "grades", self.task_map()
                )
        return self._judge

    def fingerprint(self):
        from harnesslens.core.model_config import connection
        from harnesslens.core.config import resolve_opencode_binary, opencode_version
        from harnesslens.harnesses.component_policy import policy_contract
        from harnesslens.harnesses.business_agent import load_config

        if load_config():
            raise ValueError(
                "Built-in FDABench uses the local native OpenCode runner. Remote business services need a benchmark/tool-environment descriptor."
            )
        self.task_map()
        binary = resolve_opencode_binary()
        return {
            "benchmark": self.cell,
            "primary_metric": "mean_reward",
            "tasks": cached_sha(self.data_root / "tasks/tasks.jsonl"),
            "references": cached_sha(self.data_root / "evaluation/references.jsonl"),
            "assets_manifest": sha(self.repo_root / "configs/fdabench-assets.json"),
            "split": self.split().fingerprint(),
            "resources": self._resources(),
            "judge": self._get_judge().identity,
            "model": {
                k: connection("execution")[k] for k in ("model", "base_url", "api")
            },
            "binary": cached_sha(binary),
            "opencode_version": opencode_version(binary),
            "component_policy": policy_contract(),
            "source": {
                str(p.relative_to(self.repo_root)): sha(p) for p in self.source_files()
            },
        }

    def source_files(self):
        return [
            *Path(__file__).parent.glob("*.py"),
            self.repo_root / "configs/fdabench-runtime-index.json",
            self.repo_root / "configs/fdabench-task-groups.json",
            self.repo_root / "harnesslens/benchmarks/crm_eval.py",
            self.repo_root / "harnesslens/harnesses/opencode_runtime.py",
            self.repo_root / "harnesslens/harnesses/native_harness_driver.py",
            self.repo_root / "harnesslens/infrastructure/chat_completions_proxy.py",
            self.repo_root / "harnesslens/infrastructure/provider_capacity.py",
            self.repo_root / "harnesslens/evaluation/native_benchmark.py",
            self.repo_root / "harnesslens/infrastructure/loopback_gateway.py",
            *[Path(p) for p in runtime_sources()],
        ]

    def baseline_fields(self, harness):
        if harness != "opencode":
            raise ValueError("FDABench uses native OpenCode")
        return {
            "target_model": self.target_model(),
            "user_model": None,
            "benchmark_environment": self.fingerprint(),
            "rollout": self.limits().to_dict(),
        }

    @contextmanager
    def execution_context(self):
        from .tools import ToolService

        service = ToolService(
            self.data_root, self.task_map(), self.index, self.outputs / "tools"
        )
        try:
            yield {"tools": service}
        finally:
            service.close()

    def prepare_task(self, workspace, task_id, resources):
        from harnesslens.core.artifacts import write_json

        workspace = Path(workspace)
        source = workspace / "source"
        source.mkdir()
        (workspace / "output").mkdir()
        shutil.copyfile(Path(__file__).with_name("client.py"), source / "client.py")
        service = resources["tools"]
        token = service.register(task_id, str(workspace))
        write_json(
            source / "endpoint.json",
            {"url": service.url, "token": token, "trial_id": str(workspace)},
        )
        public = self.public_task(task_id)
        write_json(source / "task.json", public)
        return {
            "prompt": public["query"] + "\n\n" + CONTRACT,
            "ports": [service.port],
            "private_roots": [str(self.data_root)],
            "private_ports": [],
        }

    def grade(self, task_id, answer):
        return self._get_judge().grade(task_id, answer)

    def run_batch(self, **kwargs):
        from harnesslens.evaluation.native_benchmark import run_batch

        return run_batch(adapter=self, **kwargs)
