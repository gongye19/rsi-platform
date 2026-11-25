#!/usr/bin/env python3
"""One local entry: offline check, paid smoke, TRAIN optimization, then frozen TEST."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def execute(command, env, stage, directory):
    from harnesslens.core.artifacts import write_json
    from harnesslens.service.worker import process_identity, stop_owned
    print(f"[{stage}] starting", flush=True)
    write_json(directory / "stage.json", {"stage": stage, "status": "running", "command": command})
    with (directory / "launcher.log").open("a") as log:
        try:
            process = subprocess.Popen(command, env=env, cwd=ROOT, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, start_new_session=True)
        except OSError:
            write_json(directory / "stage.json", {"stage": stage, "status": "failed", "error": "process could not start"})
            raise
        token = process_identity(process.pid)
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line); log.flush()
            code = process.wait()
        except BaseException:
            if process.poll() is None:
                stop_owned(process.pid, token)
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
            write_json(directory / "stage.json", {"stage": stage, "status": "interrupted"})
            raise
    write_json(directory / "stage.json", {"stage": stage, "status": "succeeded" if code == 0 else "failed", "returncode": code})
    if code:
        raise RuntimeError(f"{stage} failed. Inspect {directory / 'launcher.log'}; no later stages were started.")


def run(*, profile_path, identity, live=False, smoke_only=False):
    from harnesslens.service.config import load_profile, invocation, run_id
    from harnesslens.core.artifacts import write_json
    profile = load_profile(profile_path)
    if profile["benchmark"] not in {"crm", "crmarenapro", "dab-crmarenapro"} or profile["mode"] != "train" or profile["agent_config"]:
        raise ValueError("This simple launcher is for native local CRM TRAIN, not company HTTP/Python profiles")
    run_id(identity)
    training, env = invocation(profile, identity)
    directory = ROOT / "runs/local_experiments" / identity
    directory.mkdir(parents=True, exist_ok=True)
    config = {"profile": profile["profile_path"], "fingerprint": profile["fingerprint"], "run_id": identity, "models": json.loads(env["HAI_MODEL_CONNECTIONS"])}
    path = directory / "configuration.json"
    if path.is_file() and json.loads(path.read_text()) != config:
        raise ValueError("Launch configuration changed; use a new run ID")
    write_json(path, config)
    print(json.dumps({"run_id": identity, "training_output": str(ROOT / "runs/train" / identity),
        "models": json.loads(env["HAI_MODEL_CONNECTIONS"]),
        "mode": "live" if live or smoke_only else "offline-check", "components": profile["components"], "settings": profile.get("environment", {})}, ensure_ascii=False, indent=2), flush=True)
    python = sys.executable
    execute([python, "scripts/run_crm.py", "--run-id", identity + "-check"], env, "offline_preflight", directory)
    if profile.get("initial_harness"):
        from harnesslens.harnesses.initial_harness import load_initial_harness
        from harnesslens.benchmarks.crm_eval import _validate_manifest
        initial = load_initial_harness(profile["initial_harness"])
        _validate_manifest({**initial["manifest"], "_workspace": initial["workspace"]})
    if not live and not smoke_only:
        print("Local preflight passed; no provider requests made. Use --smoke-only or --run after API recovery.", flush=True)
        return
    execute([python, "scripts/run_crm.py", "--run-id", identity + "-smoke", "--smoke", "--probe-candidate"], env, "paid_smoke", directory)
    if smoke_only:
        return
    execute(training, env, "train", directory)
    train_root = ROOT / "runs/train" / identity
    final = train_root / "submission/final.json"
    chosen = json.loads(final.read_text())
    # Freeze TEST's parent from the actual TRAIN v0, including nonempty starts.
    from harnesslens.harnesses.initial_harness import freeze_initial_harness
    from harnesslens.harnesses.opencode_package import export_package
    frozen = freeze_initial_harness(run_root=train_root, cell="crmarenapro")
    package = export_package(directory=directory, version="v0", workspace=frozen["workspace"], manifest=frozen["manifest"])
    test_id = identity + "-test"
    execute([python, "run_test_baseline.py", "--run-id", test_id, "--benchmark", "crm", "--harness", "opencode",
             "--initial-harness", package["path"]], env, "test_initial", directory)
    if chosen["selected_version"] != "v0":
        execute([python, "run_test_candidate.py", "--run-id", test_id, "--benchmark", "crm", "--harness", "opencode",
                 "--patch-json", str(final)], env, "test_selected", directory)
    write_json(directory / "result.json", {"train_submission": str(final), "selected_version": chosen["selected_version"],
        "test_run_id": test_id, "selected_equals_initial": chosen["selected_version"] == "v0",
        "test_initial": str(ROOT / "runs/test_baselines" / test_id),
        "test_selected": str(ROOT / "runs/test_baselines" / test_id) if chosen["selected_version"] == "v0" else str(ROOT / "runs/test_candidates" / test_id)})
    print("TRAIN and frozen TEST completed. See " + str(directory / "result.json"), flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", type=Path, default=ROOT / "configs/experiments/crm-local.toml")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run", action="store_true", help="Paid smoke, TRAIN and frozen TEST; only after API recovery")
    modes.add_argument("--smoke-only", action="store_true", help="Paid query1 baseline/candidate smoke only")
    args = parser.parse_args()
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        run(profile_path=args.profile, identity=args.run_id, live=args.run, smoke_only=args.smoke_only)
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Stopped. Existing experiment records were retained.", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
