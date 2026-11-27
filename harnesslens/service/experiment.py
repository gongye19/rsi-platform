"""Generic TRAIN → frozen TEST orchestration, shared by UI and queue jobs."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from .config import ROOT, invocation, load_profile, run_id
from harnesslens.core.artifacts import write_json


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


def run(profile_path, identity):
    # The same bounded process/stop handling as the existing local launcher.
    run_id(identity + "-test")
    profile = load_profile(profile_path)
    # Preserve the same frozen TRAIN/TEST selection across all three subprocesses.
    if profile.get('dataset_selection'):
        from harnesslens.benchmarks.selection import resolve_dataset
        resolve_dataset(profile['benchmark'], {**profile['dataset'], 'frozen': profile['dataset_selection']},
                        mode='train', full_evaluation=True)
    training, env = invocation({**profile, 'full_evaluation': False}, identity)
    repeats = str(env.get('HAI_TEST_ROLLOUT_REPEATS', '2'))
    if repeats not in {'1', '2'}: raise ValueError('TEST repeats must be 1 or 2')
    directory = ROOT / 'runs/local_experiments' / identity
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / 'configuration.json', {'profile': profile['profile_path'], 'fingerprint': profile['fingerprint'],
               'run_id': identity, 'models': json.loads(env['HAI_MODEL_CONNECTIONS'])})
    execute(training, env, 'train', directory)
    train_root = ROOT / 'runs/train' / identity
    final_path = train_root / 'submission/final.json'
    final = json.loads(final_path.read_text())
    from harnesslens.harnesses.initial_harness import freeze_initial_harness
    from harnesslens.harnesses.opencode_package import export_package
    from harnesslens.benchmarks.cell_config import benchmark_config
    cell = benchmark_config(ROOT, profile['benchmark']).cell
    frozen = freeze_initial_harness(run_root=train_root, cell=cell)
    package = export_package(directory=directory, version='v0', workspace=frozen['workspace'], manifest=frozen['manifest'])
    test_id = identity + '-test'
    common = ['--run-id', test_id, '--benchmark', profile['benchmark'], '--harness', 'opencode', '--repeats', repeats]
    if profile['agent_config']: common += ['--agent-config', profile['agent_config']]
    execute([sys.executable, 'run_test_baseline.py', *common, '--initial-harness', package['path']], env, 'test_initial', directory)
    if final['selected_version'] != 'v0':
        execute([sys.executable, 'run_test_candidate.py', *common, '--patch-json', str(final_path)], env, 'test_selected', directory)
    write_json(directory / 'result.json', {'train_submission': str(final_path), 'selected_version': final['selected_version'],
               'test_run_id': test_id, 'selected_equals_initial': final['selected_version'] == 'v0', 'test_repeats': int(repeats)})


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    def stop(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    run(args.profile, args.run_id)


if __name__ == '__main__': main()
