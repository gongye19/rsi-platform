#!/usr/bin/env python3
"""Server-only FDABench assets, sandbox preflight and optional one-task smoke run."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def profile_environment(path):
    if path:
        from harnesslens.service.config import load_profile, invocation

        profile=load_profile(path)
        from harnesslens.benchmarks.cell_config import benchmark_config
        if benchmark_config(ROOT,profile['benchmark']).cell!='fdabench':
            raise ValueError('Select a native FDABench experiment profile')
        _, env = invocation(profile, "fdabench-preflight")
        os.environ.clear()
        os.environ.update(env)
    else:
        from harnesslens.core.config import load_repo_env

        load_repo_env(ROOT)


def launch_profile(profile_path, identity, *, data_root=None, index=None):
    """Persist CLI overrides so TRAIN and subsequent TEST reload the same settings."""
    import tomllib
    from harnesslens.service.config import load_profile
    from harnesslens.service.settings import dump_toml
    profile=load_profile(profile_path)
    raw=tomllib.loads(Path(profile_path).read_text())
    for key in ('env_file','initial_harness','agent_config','submission'):
        if key in raw:raw[key]=profile[key]
    raw['benchmark']=profile['benchmark']
    environment=raw.setdefault('environment',{})
    if data_root is not None:environment['HAI_FDABENCH_ROOT']=str(data_root)
    if index is not None:environment['HAI_FDABENCH_INDEX']=str(index)
    destination=ROOT/'runs/launch_profiles'/identity
    destination.mkdir(parents=True,exist_ok=False,mode=0o700)
    path=destination/'profile.toml';path.write_text(dump_toml(raw));path.chmod(0o600)
    load_profile(path)
    return path


def doctor(adapter):
    from harnesslens.core.config import resolve_opencode_binary, opencode_version
    from harnesslens.core.model_config import connection
    from harnesslens.evaluation.native_benchmark import isolated_command

    if sys.platform != "linux":
        raise RuntimeError("Run the server preflight on Linux")
    for binary in ("bwrap", "pdftotext"):
        if not shutil.which(binary):
            raise RuntimeError("Missing system dependency: " + binary)
    binary = resolve_opencode_binary()
    if opencode_version(binary) != "1.18.32":
        raise ValueError("OpenCode 1.18.32 is required")
    adapter.task_map()
    adapter._resources()
    for role in ("execution", "analysis"):
        selected = connection(role)
        if not selected.get("api_key"):
            raise ValueError("Missing " + role + " credential")
        if "your-" in selected["model"]:
            raise ValueError("Configure a real " + role + " model in the profile")
    adapter._get_judge()
    if not os.environ.get("ZHIPU_API_KEY"):
        raise ValueError("ZHIPU_API_KEY is required for live web search")
    # Test real network namespaces and the Unix-socket bridge without external calls.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"rsi-gateway-ok")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (ROOT / "runs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="fda-doctor-", dir=ROOT / "runs"
        ) as folder:
            workspace = Path(folder)
            (workspace / ".runtime").mkdir()
            marker = workspace.parent / (workspace.name + "-private")
            marker.write_text("host-only")
            try:
                code = f"import pathlib,urllib.request;assert not pathlib.Path({str(marker)!r}).exists();assert urllib.request.urlopen('http://127.0.0.1:{server.server_port}').read()==b'rsi-gateway-ok'"
                with isolated_command(
                    [sys.executable, "-c", code], workspace, [server.server_port], []
                ) as command:
                    result = subprocess.run(
                        command,
                        cwd=workspace,
                        env={"PATH": os.environ.get("PATH", "")},
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                if result.returncode:
                    raise RuntimeError(
                        "Linux sandbox/loopback bridge failed: " + result.stderr[-600:]
                    )
            finally:
                marker.unlink(missing_ok=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return {
        "ready": True,
        "benchmark": "fdabench-lite-report",
        "train": 70,
        "test": 35,
        "databases": 16,
        "pdfs": 1418,
        "opencode": "1.18.32",
        "sandbox": "bubblewrap + private network namespace",
        "model_requests_made": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("download", "prepare", "doctor", "smoke", "run")
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Defaults to HAI_FDABENCH_ROOT or third_party/fdabench-lite-report",
    )
    parser.add_argument(
        "--index-cache",
        type=Path,
        help="Defaults to the directory containing HAI_FDABENCH_INDEX",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--section", choices=("all", "tasks", "databases", "documents"), default="all"
    )
    parser.add_argument(
        "--profile", type=Path, default=ROOT / "configs/experiments/fdabench.toml"
    )
    parser.add_argument(
        "--task",
        help="TRAIN task ID for one-task smoke; defaults to the first frozen TRAIN task",
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("workers must be 1..16")
    if args.action in ("doctor", "smoke", "run"):
        profile_environment(args.profile)
    else:
        from harnesslens.core.config import load_repo_env

        load_repo_env(ROOT)
    if args.data_root:
        os.environ["HAI_FDABENCH_ROOT"] = str(args.data_root.expanduser().resolve())
    if args.index_cache:
        os.environ["HAI_FDABENCH_INDEX"] = str(
            args.index_cache.expanduser().resolve() / "documents.sqlite"
        )
    from harnesslens.benchmarks.fdabench.adapter import FDABenchAdapter

    adapter = FDABenchAdapter(ROOT)
    if args.action == "download":
        from harnesslens.benchmarks.fdabench.download import download

        download(adapter.data_root, workers=args.workers, section=args.section)
        print(
            json.dumps(
                {
                    "download": "complete",
                    "section": args.section,
                    "data_root": str(adapter.data_root),
                }
            )
        )
    elif args.action == "prepare":
        from harnesslens.benchmarks.fdabench.download import verify
        from harnesslens.benchmarks.fdabench.data import build_index

        if (adapter.data_root / "prebuilt/documents.sqlite").is_file():
            from harnesslens.benchmarks.fdabench.runtime_bundle import prepare_runtime
            receipt = prepare_runtime(adapter.data_root, adapter.index)
        else:
            verify(adapter.data_root)
            _, receipt = build_index(
                adapter.data_root, adapter.index.parent, workers=args.workers
            )
        adapter._resources()
        print(json.dumps({"prepared": True, **receipt}))
    elif args.action == "doctor":
        print(json.dumps(doctor(adapter)))
    elif args.action == "smoke":
        doctor(adapter)
        task = args.task or adapter.split().train[0]
        from harnesslens.harnesses.harness_manifest import empty_harness_manifest

        output = ROOT / "runs/fdabench-smoke" / uuid.uuid4().hex[:12]
        result = adapter.run_batch(
            run_root=output,
            scope="TRAIN",
            harness="opencode",
            harness_version="v0",
            harness_manifest=empty_harness_manifest(),
            task_repeats={task: 1},
            pairing_offsets={},
            max_concurrency=1,
        )
        print(json.dumps({"output": str(output), "metrics": result["metrics"]}))
    else:
        doctor(adapter)
        from harnesslens.service.config import load_profile, invocation

        identity = "fdabench-" + uuid.uuid4().hex[:12]
        snapshot=launch_profile(args.profile,identity,
                                data_root=adapter.data_root if args.data_root else None,
                                index=adapter.index if args.index_cache else None)
        command,env=invocation(load_profile(snapshot),identity)
        print(json.dumps({'run_id':identity,'profile':str(snapshot)}),flush=True)
        return subprocess.call(command, cwd=ROOT, env=env)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
