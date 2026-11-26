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
    if set(raw) - {"schema", "benchmark", "initial_harness", "agent_config", "env_file", "mode", "submission", "environment", "readiness", "components", "models", "full_evaluation", "dataset"} or raw.get("schema") != "harnesslens.experiment.v1":
        raise ValueError("Unsupported experiment profile")
    if "full_evaluation" in raw and type(raw["full_evaluation"]) is not bool:
        raise ValueError("full_evaluation must be boolean")
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
    if "models" in raw:
        from harnesslens.core.model_config import normalize_models
        result["models"] = normalize_models(raw["models"])
    from harnesslens.harnesses.component_policy import normalize_policy
    policy = normalize_policy(raw.get("components"))
    result["components"] = policy
    initial = raw.get("initial_harness", "")
    if not isinstance(initial, str):
        raise ValueError("initial_harness must be a directory/package path")
    result["initial_harness"] = str((path.parent / initial).resolve()) if initial else ""
    if initial:
        if mode == "test_candidate":
            raise ValueError("test_candidate loads its full Harness from submission, not initial_harness")
        from harnesslens.harnesses.initial_harness import load_initial_harness
        files["initial_harness"] = load_initial_harness(result["initial_harness"])["sha256"]
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
    if 'dataset' in raw:
        from harnesslens.benchmarks.selection import normalize_dataset, resolve_dataset, digest
        result['dataset'] = normalize_dataset(raw['dataset'])
        result['dataset_selection'] = resolve_dataset(benchmark,raw['dataset'],repo_root=ROOT)
        files['dataset_selection'] = digest(result['dataset_selection'])
    # Endpoint/model changes invalidate resume; rotating credentials does not.
    if result.get("models"):
        model_env = profile_environment(result) if not result["env_file"] or Path(result["env_file"]).is_file() else dict(os.environ)
        for role, row in result["models"].items():
            if row.get("base_url_env"):
                files["model_endpoint:" + role] = hashlib.sha256(model_env.get(row["base_url_env"], "").encode()).hexdigest()
    result["fingerprint"] = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return result


def invocation(profile, identity):
    identity = run_id(identity)
    if profile.get("full_evaluation") and profile["mode"] == "train":
        run_id(identity + "-test")
    if profile.get("readiness", "ready") != "ready":
        raise ValueError("Profile is draft: finish business/data/trace integration before starting")
    env = profile_environment(profile)
    from harnesslens.benchmarks.selection import ENV as SELECTION_ENV, resolve_dataset
    env.pop(SELECTION_ENV,None)
    if profile.get('dataset_selection'):
        frozen=resolve_dataset(profile['benchmark'],{**profile['dataset'],'frozen':profile['dataset_selection']},
            mode=profile['mode'],full_evaluation=profile.get('full_evaluation',False))
        env[SELECTION_ENV]=json.dumps(frozen,sort_keys=True)
    from harnesslens.core.model_config import configure_models
    receipt = configure_models(profile.get("models"), env, business=bool(profile["agent_config"]))
    env["HAI_MODEL_CONNECTIONS"] = json.dumps(receipt, sort_keys=True)
    from harnesslens.harnesses.component_policy import ENV
    env[ENV] = json.dumps(profile["components"], sort_keys=True)
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
    if profile.get("initial_harness"):
        argv += ["--initial-harness", profile["initial_harness"]]
    if profile["mode"] == "test_candidate":
        if not profile["submission"]:
            raise ValueError("test_candidate needs submission")
        argv += ["--patch-json", profile["submission"]]
    if profile.get("full_evaluation") and profile["mode"] == "train":
        argv = [sys.executable, "-m", "harnesslens.service.experiment", "--profile", profile["profile_path"], "--run-id", identity]
    elif profile["mode"] != "train" and env.get("HAI_TEST_ROLLOUT_REPEATS"):
        argv += ["--repeats", env["HAI_TEST_ROLLOUT_REPEATS"]]
    return argv, env


def profile_environment(profile):
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
    return env
