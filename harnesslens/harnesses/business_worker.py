"""Standalone subprocess worker for an existing Python agent (stdlib only)."""
from __future__ import annotations
import asyncio
import dataclasses
import importlib
import inspect
import json
import sys
from pathlib import Path


def json_value(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def main():
    payload = json.loads(Path(sys.argv[1]).read_text())
    sys.path[:0] = payload["python_paths"]
    module, name = payload["function"].split(":", 1)
    function = importlib.import_module(module)
    for part in name.split("."):
        function = getattr(function, part)
    result = function(**payload["arguments"])
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    target = Path(payload["response_file"])
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, default=json_value))
    temporary.replace(target)


if __name__ == "__main__":
    main()
