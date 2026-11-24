import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def run_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", value):
        raise ValueError("Invalid run ID")
    return value


def load_profile(path):
    path = Path(path).resolve()
    raw = tomllib.loads(path.read_text())
    if set(raw) - {"schema", "benchmark", "agent_config", "env_file", "mode", "submission", "environment", "readiness"} or raw.get("schema") != "harnesslens.experiment.v1":
        raise ValueError("Unsupported experiment profile")
    mode = raw.get("mode", "train")
    if mode not in {"train", "test_baseline", "test_candidate"}:
        raise ValueError("Unsupported experiment mode")
    benchmark = raw.get("benchmark", "crm")
    if not isinstance(benchmark, str):
        raise ValueError("benchmark must be a name or TOML path")
    if benchmark.endswith(".toml"):
        benchmark = str((path.parent / benchmark).resolve())
    files = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()}
    result = {**raw, "mode": mode, "benchmark": benchmark, "profile_path": str(path)}
    for key in ("agent_config", "env_file", "submission"):
        value = raw.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a path")
        result[key] = str((path.parent / value).resolve()) if value else ""
        if value and key != "env_file":
            target = Path(result[key])
            if not target.is_file():
                raise ValueError(f"Configured {key} file is missing")
            files[str(target)] = hashlib.sha256(target.read_bytes()).hexdigest()
    environment = raw.get("environment", {})
    if not isinstance(environment, dict):
        raise ValueError("environment must be a table")
    for key, value in environment.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not key.startswith(("HAI_", "DEEPSEEK_")):
            raise ValueError("Only explicit HarnessLens/provider settings are allowed")
        if any(word in key for word in ("KEY", "TOKEN", "PASSWORD", "SECRET")):
            raise ValueError("Secrets must be in the private env_file, not the profile")
        if type(value) not in {str, int, float, bool}:
            raise ValueError("Environment settings must be scalar")
    result["fingerprint"] = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return result


def invocation(profile, identity):
    identity = run_id(identity)
    if profile.get("readiness", "ready") != "ready":
        raise ValueError("Profile is draft: finish business/data/trace integration before starting")
    env = dict(os.environ)
    if profile["env_file"]:
        target = Path(profile["env_file"])
        if not target.is_file():
            raise ValueError("Private env_file is missing")
        for raw in target.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                    raise ValueError("Invalid env_file variable")
                env[key] = value.strip().strip('"').strip("'")
    env.update({key: str(value) for key, value in profile.get("environment", {}).items()})
    env["HARNESSLENS_ROOT"] = str(ROOT)
    if profile["agent_config"]:
        env["HAI_AGENT_CONFIG"] = profile["agent_config"]
    else:
        env.pop("HAI_AGENT_CONFIG", None)
    binary = ROOT / "runtime/opencode-1.18.32/bin/opencode"
    if binary.is_file():
        env.setdefault("HAI_OPENCODE_BIN", str(binary))
        env.setdefault("HAI_CRM_RUNTIME_ROOT", str(binary.parent.parent))
    env.setdefault("HAI_OPENCODE_VERSION", "1.18.32")
    entry = {"train": "run_e2e.py", "test_baseline": "run_test_baseline.py", "test_candidate": "run_test_candidate.py"}[profile["mode"]]
    flag = "--cell" if profile["mode"] == "train" else "--benchmark"
    argv = [sys.executable, "-m", "harnesslens.service.job_entry", entry,
            "--run-id", identity, flag, profile["benchmark"], "--harness", "opencode"]
    if profile["agent_config"]:
        argv += ["--agent-config", profile["agent_config"]]
    if profile["mode"] == "test_candidate":
        if not profile["submission"]:
            raise ValueError("test_candidate needs submission")
        argv += ["--patch-json", profile["submission"]]
    return argv, env
