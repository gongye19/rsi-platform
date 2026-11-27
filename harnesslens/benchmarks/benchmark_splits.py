from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class BenchmarkSplit:
    benchmark: str
    cell: str
    train: tuple[str, ...]
    test: tuple[str, ...]
    local_rootless_rollout: bool

    def fingerprint(self) -> str:
        payload = {"train": list(self.train), "test": list(self.test)}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


_SPECS: Mapping[str, Mapping[str, Any]] = {
    "fdabench-lite-report": {"cell":"fdabench", "config":"fdabench_split.json", "local_rootless_rollout":False},
}

_ALIASES = {
    "fdabench":"fdabench-lite-report", "fdabench-lite-report":"fdabench-lite-report",
}


def supported_test_benchmarks() -> tuple[str, ...]:
    return tuple(_SPECS)


def load_benchmark_split(benchmark: str, *, apply_selection: bool = True) -> BenchmarkSplit:
    from .jsonl_adapter import resolve_external
    external = resolve_external(Path(__file__).resolve().parents[2], benchmark)
    if external:
        return external.split(apply_selection=apply_selection)
    normalized = _ALIASES.get(str(benchmark).strip().lower())
    if normalized is None:
        raise ValueError(f"unsupported HarnessLens test benchmark: {benchmark}")
    spec = _SPECS[normalized]
    path = Path(__file__).resolve().parents[2] / "configs" / str(spec["config"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    train = _validated_ids(payload.get("train"), label=f"{normalized} TRAIN")
    test = _validated_ids(payload.get("test"), label=f"{normalized} TEST")
    overlap = set(train) & set(test)
    if overlap:
        raise ValueError(f"{normalized} split overlaps: {sorted(overlap)}")
    result = BenchmarkSplit(
        benchmark=normalized,
        cell=str(spec["cell"]),
        train=train,
        test=test,
        local_rootless_rollout=bool(spec["local_rootless_rollout"]),
    )
    from .selection import selected_split
    return selected_split(result) if apply_selection else result


def _validated_ids(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} split is empty or malformed")
    normalized = tuple(str(item) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} split contains duplicate task IDs")
    return normalized
