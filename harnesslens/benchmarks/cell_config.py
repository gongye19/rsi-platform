from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class BenchmarkConfig:
    benchmark: str
    cell: str
    kind: str
    train_task_ids: tuple[str, ...]
    local_rootless_rollout: bool
    outcome_authority: str
    domain_files: tuple[str, ...] = ()
    primary_metric: str = "pass_at_1"

    def runtime_files(self) -> tuple[str, ...]:
        common = (
            "harnesslens/core/model_config.py",
            "harnesslens/harnesses/component_policy.py",
            "harnesslens/harnesses/component_preflight.py",
            "harnesslens/harnesses/opencode_execution.py",
            "harnesslens/harnesses/opencode_bridge.mjs",
            "harnesslens/infrastructure/trace_watch.py",
            "harnesslens/harnesses/initial_harness.py",
            "harnesslens/evaluation/rollout_bridge.py",
            "harnesslens/harnesses/native_candidate_runtime.py",
            "harnesslens/harnesses/harness_workspace.py",
        )
        if self.kind == "fdabench":
            from .fdabench.adapter import FDABenchAdapter
            root = Path(__file__).resolve().parents[2]
            return tuple(str(p.relative_to(root)) for p in FDABenchAdapter(root).source_files()) + self.domain_files
        if self.kind == "business_extension":
            from .adapters import runtime_sources
            return (*common, *runtime_sources(), *self.domain_files)
        raise ValueError(f"unsupported benchmark kind: {self.kind}")

    def task_source_files(self) -> tuple[str, ...]:
        if self.kind in {"business_extension", "fdabench"}:
            return self.domain_files
        raise ValueError(f"unsupported benchmark kind: {self.kind}")


_ALIASES = {
    "fdabench": "fdabench", "fdabench-lite-report": "fdabench",
}


SUPPORTED_CELLS = ("fdabench",)


def supported_cell_help() -> str:
    """One line naming the cells, for --cell help text and error messages."""
    return " | ".join(SUPPORTED_CELLS) + " | /path/to/benchmark.toml"


def normalize_benchmark_cell(cell: str) -> str:
    from .jsonl_adapter import resolve_external
    external = resolve_external(Path(__file__).resolve().parents[2], cell)
    if external:
        return external.cell
    normalized = _ALIASES.get(str(cell).strip().lower())
    if normalized is None:
        raise ValueError(
            f"unknown benchmark cell {cell!r}; expected one of: "
            f"{supported_cell_help()}"
        )
    return normalized


def benchmark_cell(cell: str) -> str:
    """argparse ``type`` for --cell: accepts any alias, rejects typos at parse.

    A plain ``choices`` list would print all aliases in the usage
    line; this keeps them working while failing with a short, readable message.
    """
    import argparse

    try:
        normalized = normalize_benchmark_cell(cell)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return normalized if Path(str(cell)).suffix == ".toml" else cell


def _base_benchmark_config(repo_root: str | Path, cell: str) -> BenchmarkConfig:
    root = Path(repo_root).resolve()
    from .jsonl_adapter import resolve_external
    external = resolve_external(root, cell)
    if external:
        return external.benchmark_config()
    normalized = normalize_benchmark_cell(cell)
    if normalized == "fdabench":
        split = _load_split(root, "fdabench_split.json")
        return BenchmarkConfig("fdabench-lite-report", "fdabench", "fdabench", tuple(split["train"]), False, "behavioral", domain_files=("configs/fdabench_split.json", "configs/fdabench-assets.json"), primary_metric="mean_reward")
    raise AssertionError(normalized)


def _load_split(repo_root: Path, filename: str) -> dict[str, Sequence[str]]:
    candidates = (repo_root / "configs" / filename,)
    for path in candidates:
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            train = _validated_ids(payload.get("train"), label=f"{filename} TRAIN")
            test = _validated_ids(payload.get("test"), label=f"{filename} TEST")
            overlap = set(train) & set(test)
            if overlap:
                raise ValueError(f"{filename} split overlaps: {sorted(overlap)}")
            return {"train": train, "test": test}
    raise ValueError(f"split config is unavailable: {filename}")


def _validated_ids(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} split is empty or malformed")
    normalized = tuple(str(item) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} split contains duplicate task IDs")
    return normalized


def benchmark_config(repo_root: str | Path, cell: str) -> BenchmarkConfig:
    config=_base_benchmark_config(repo_root,cell)
    from .selection import ENV, selected_split
    if not os.environ.get(ENV):return config
    from .benchmark_splits import load_benchmark_split
    from dataclasses import replace
    base=load_benchmark_split(cell,apply_selection=False)
    return replace(config,train_task_ids=selected_split(base).train)
