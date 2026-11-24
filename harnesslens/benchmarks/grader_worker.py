"""Isolated host grader process; never copied into the business workspace."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys


def main():
    path, function = Path(sys.argv[1]).resolve(), sys.argv[2]
    payload = json.loads(sys.stdin.read())
    sys.path.insert(0, str(path.parent))
    with contextlib.redirect_stdout(sys.stderr):
        spec = importlib.util.spec_from_file_location("harnesslens_host_grader", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        value = getattr(module, function)(payload["task"], payload["answer"])
    sys.stdout.write(json.dumps(value))


if __name__ == "__main__":
    main()
