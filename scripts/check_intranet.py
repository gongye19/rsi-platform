#!/usr/bin/env python3
"""Offline, non-billing deployment checks. Does not call the business/provider API."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "configs/experiments/fdabench.toml")
    args = parser.parse_args()
    from harnesslens.core.config import load_repo_env
    from harnesslens.service.config import load_profile
    from harnesslens.infrastructure.process_isolation import check_editor_sandbox
    load_repo_env(ROOT)
    checks = []
    def check(name, action):
        try:
            value = action()
            checks.append({"check": name, "ok": True, "detail": value})
        except Exception as exc:
            checks.append({"check": name, "ok": False, "detail": type(exc).__name__ + ": " + str(exc)})
    check("python", lambda: sys.version.split()[0] if sys.version_info >= (3, 11) else (_ for _ in ()).throw(RuntimeError("Python >=3.11 required")))
    def dependencies():
        for name in ("httpx", "yaml"):
            if not importlib.util.find_spec(name):
                raise RuntimeError("Missing dependency: " + name)
        return "installed"
    check("dependencies", dependencies)
    def runtime():
        from harnesslens.core.config import opencode_version
        binary = ROOT / "runtime/opencode-1.18.32/bin/opencode"
        return opencode_version(binary)
    check("opencode_1_18_32", runtime)
    check("editor_sandbox", check_editor_sandbox)
    def profile():
        value = load_profile(args.profile)
        return {"mode": value["mode"], "readiness": value.get("readiness", "ready"), "fingerprint": value["fingerprint"]}
    check("profile_syntax", profile)
    print(json.dumps({"checks": checks, "business_and_model_calls": 0,
        "notice": "Passing these checks does not validate company HTTP, trace or test-data connectivity."}, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
