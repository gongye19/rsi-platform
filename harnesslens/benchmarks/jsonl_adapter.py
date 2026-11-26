"""Data-driven benchmark adapter for existing business agents.

Select with --cell /absolute/path/benchmark.toml. No optimizer edits required.
Reference answers remain host-side; only explicitly listed public fields travel.
"""
from __future__ import annotations
import json
import os
import re
import tomllib
from pathlib import Path

from .adapters import BusinessBenchmark, sha, runtime_sources

_DESCRIPTORS: dict[str, Path] = {}


def resolve_external(repo_root, cell):
    value = str(cell)
    from .cell_config import _ALIASES
    if value.strip().lower() in _ALIASES:
        return None
    path = Path(value).expanduser()
    if path.suffix == ".toml" and path.is_file():
        adapter = JsonlAdapter(repo_root, path.resolve())
        existing = _DESCRIPTORS.get(adapter.cell)
        if existing is not None and existing != path.resolve() and existing.exists():
            raise ValueError("Two benchmark descriptors use the same ID")
        _DESCRIPTORS[adapter.cell] = path.resolve()
        os.environ["HAI_BENCHMARK_CONFIG"] = str(path.resolve())
        return adapter
    if value in _DESCRIPTORS and _DESCRIPTORS[value].is_file():
        adapter = JsonlAdapter(repo_root, _DESCRIPTORS[value])
        if adapter.cell != value:
            raise ValueError("Benchmark descriptor ID changed")
        return adapter
    selected = os.environ.get("HAI_BENCHMARK_CONFIG")
    if selected and Path(selected).is_file():
        adapter = JsonlAdapter(repo_root, Path(selected).resolve())
        if adapter.cell == value:
            return adapter
    return None


class JsonlAdapter(BusinessBenchmark):
    def __init__(self, repo_root, descriptor):
        self.repo_root, self.descriptor = Path(repo_root).resolve(), Path(descriptor).resolve()
        raw = tomllib.loads(self.descriptor.read_text())
        allowed = {"schema", "id", "tasks", "train", "test", "id_field", "prompt_field", "public_fields",
                   "reference_field", "grader", "grader_file", "grader_function", "grader_timeout", "max_concurrency", "primary_metric", "domain_field"}
        if set(raw) - allowed or raw.get("schema") != "harnesslens.business-benchmark.v1":
            raise ValueError("Unknown benchmark settings or schema")
        if raw.get("primary_metric", "pass_at_1") not in {"pass_at_1", "mean_reward"}:
            raise ValueError("primary_metric must be pass_at_1 or mean_reward")
        self.spec = raw
        if "domain_field" in raw and (not isinstance(raw["domain_field"],str) or not raw["domain_field"]):
            raise ValueError("domain_field must name a public task field")
        for key in ("tasks", "id_field", "prompt_field", "reference_field", "grader", "grader_file", "grader_function"):
            if key in raw and (not isinstance(raw[key], str) or not raw[key].strip()):
                raise ValueError(f"Benchmark {key} must be a nonempty string")
        self.cell = raw.get("id", "")
        from .cell_config import _ALIASES
        if not isinstance(self.cell, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.cell) or self.cell in {
            *_ALIASES, "crm", "crmarenapro", "retail", "banking", "banking_knowledge", "bird", "bird_mini_dev_challenging", "terminal", "terminal_bench"}:
            raise ValueError("External benchmark needs a unique safe ID")
        self.tasks_path = (self.descriptor.parent / raw["tasks"]).resolve()
        for scope in ("train", "test"):
            ids = raw.get(scope)
            if not isinstance(ids, list) or not ids or any(not isinstance(v, str) or not v for v in ids) or len(ids) != len(set(ids)):
                raise ValueError(f"Invalid benchmark {scope} task IDs")
        if set(raw["train"]) & set(raw["test"]):
            raise ValueError("Benchmark train and test split overlaps")
        self.prompt_field = raw.get("prompt_field", "question")
        self.id_field = raw.get("id_field", "id")
        self.reference_field = raw.get("reference_field", "answer")
        self.public_fields = raw.get("public_fields", [self.prompt_field])
        if not isinstance(self.public_fields, list) or self.prompt_field not in self.public_fields or any(not isinstance(v, str) for v in self.public_fields):
            raise ValueError("public_fields must explicitly include the prompt field")
        if self.reference_field in self.public_fields:
            raise ValueError("Reference answer cannot be a public field")
        if raw.get('domain_field') and (raw['domain_field'] not in self.public_fields or raw['domain_field']==self.reference_field):
            raise ValueError('domain_field must be explicitly public and cannot be the reference answer')
        self.grader = raw.get("grader", "exact")
        if self.grader not in {"exact", "python"}:
            raise ValueError("grader must be exact or python")
        self.grader_path = (self.descriptor.parent / raw["grader_file"]).resolve() if self.grader == "python" else None
        self.grader_timeout = raw.get("grader_timeout", 60)
        if type(self.grader_timeout) not in {int, float} or not 0 < self.grader_timeout <= 3600:
            raise ValueError("grader_timeout must be in (0, 3600]")
        self.max_concurrency = raw.get("max_concurrency", 2)
        if type(self.max_concurrency) is not int or not 1 <= self.max_concurrency <= 32:
            raise ValueError("Benchmark max_concurrency must be 1..32")

    def _tasks(self):
        tasks = {}
        for line in self.tasks_path.read_text().splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            tid = str(item[self.id_field])
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", tid):
                raise ValueError("JSONL task IDs must be safe unique identifiers without paths")
            if tid in tasks:
                raise ValueError("Duplicate benchmark task ID")
            if not isinstance(item.get(self.prompt_field), str) or not item[self.prompt_field].strip():
                raise ValueError("Task prompt is missing")
            if self.grader == "exact" and self.reference_field not in item:
                raise ValueError("Exact-match task is missing its host reference")
            tasks[tid] = item
        if (set(self.spec["train"]) | set(self.spec["test"])) - set(tasks):
            raise ValueError("Benchmark split references unavailable tasks")
        return tasks

    def split(self, *, apply_selection=True):
        from .benchmark_splits import BenchmarkSplit
        split = BenchmarkSplit(self.cell, self.cell, tuple(self.spec["train"]), tuple(self.spec["test"]), False)
        from .selection import selected_split
        return selected_split(split) if apply_selection else split

    def benchmark_config(self):
        from .cell_config import BenchmarkConfig
        files = (str(self.descriptor), str(self.tasks_path), *((str(self.grader_path),) if self.grader_path else ()))
        return BenchmarkConfig(self.cell, self.cell, "business_extension", tuple(self.spec["train"]), False,
                               "behavioral" if self.spec.get("primary_metric") == "mean_reward" else "authoritative", domain_files=files,
                               primary_metric=self.spec.get("primary_metric", "pass_at_1"))

    def public_task(self, task_id):
        raw = self._tasks()[task_id]
        return {key: raw[key] for key in self.public_fields if key in raw}

    def prepare_task(self, workspace, task_id, resources):
        task = self.public_task(task_id)
        source = Path(workspace) / "source"
        source.mkdir()
        (source / "task.json").write_text(json.dumps(task, ensure_ascii=False))
        return {"prompt": task[self.prompt_field], "private_roots": [str(self.tasks_path), str(self.descriptor),
                *([str(self.grader_path)] if self.grader_path else [])], "private_ports": []}

    def grade(self, task_id, answer):
        import math
        task = self._tasks()[task_id]
        if self.grader == "exact":
            reward = float(answer.strip() == str(task[self.reference_field]).strip())
            validator = str(Path(__file__))
        else:
            import subprocess
            import sys
            from harnesslens.harnesses.native_harness_driver import stop_process
            process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("grader_worker.py")),
                str(self.grader_path), self.spec.get("grader_function", "grade")], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                output, _ = process.communicate(json.dumps({"task": task, "answer": answer}), timeout=self.grader_timeout)
                if process.returncode != 0:
                    raise RuntimeError("Host grader failed")
                reward = json.loads(output)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Host grader timed out") from None
            finally:
                stop_process(process)
            if isinstance(reward, dict):
                reward = reward["reward"]
            validator = str(self.grader_path)
        if type(reward) not in {int, float, bool} or not math.isfinite(reward) or not 0 <= reward <= 1:
            raise ValueError("Host grader returned an invalid reward")
        return {"reward": float(reward), "validator_sha256": sha(validator)}

    def fingerprint(self):
        from harnesslens.harnesses.business_agent import load_config, fingerprint
        business = load_config()
        if not business:
            raise ValueError("External benchmark requires --agent-config")
        self._tasks()
        return {"benchmark": self.cell, "descriptor": sha(self.descriptor), "tasks": sha(self.tasks_path),
                "grader": sha(self.grader_path) if self.grader_path else sha(__file__),
                "business_agent": fingerprint(business), "runtime_sources": {p: sha(p) for p in runtime_sources()}}

    def explorer_input(self, task_ids):
        if set(task_ids) - set(self.spec["train"]):
            raise ValueError("Explorer may only receive TRAIN tasks")
        return {"benchmark_kind": "business_extension", "cell": self.cell,
                "tasks": [{"task_id": tid, "input": self.public_task(tid)} for tid in task_ids],
                "environment": {"runtime_contract": self.loading_contract(), "tools": []},
                "forbidden_inputs": ["reference answers", "grader", "TEST tasks"]}
