#!/usr/bin/env python3
"""Download locked Linux wheels and checksum-pinned OpenCode; no credentials/data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("x86_64", "aarch64"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT / "offline" / ("linux-" + args.arch)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    requirements = output / "requirements.lock.txt"
    subprocess.run(["uv", "export", "--locked", "--extra", "dev",
        "--no-emit-project", "--no-header", "--output-file", str(requirements)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    # pip's cross-platform wheel selection does not execute target code/builds.
    command = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:",
        "--python-version", "3.13", "--implementation", "cp", "--abi", "cp313", "--dest", str(output / "wheelhouse"), "-r", str(requirements)]
    for minor in range(40, 16, -1):
        command += ["--platform", f"manylinux_2_{minor}_{args.arch}"]
    command += ["--platform", f"manylinux2014_{args.arch}"]
    subprocess.run(command, cwd=ROOT, check=True)
    target = "linux-" + {"x86_64": "x64", "aarch64": "arm64"}[args.arch]
    path = subprocess.check_output([sys.executable, str(ROOT / "scripts/install_opencode.py"), "--download-only", "--platform", target], text=True).strip()
    directory = output / "opencode" / args.arch
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, directory / "opencode.tar.gz")
    (output / "README.txt").write_text("Python 3.13 Linux " + args.arch + " wheels and OpenCode 1.18.32. Requires uv + Python 3.13 already available.\nRun: bash scripts/setup_linux.sh --offline PATH_TO_THIS_DIRECTORY\nFrontend: prepare/build on matching Linux separately; see docs/INTRANET.zh-CN.md.\n")
    manifest = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest() for path in output.rglob("*") if path.is_file() and path.name != "SHA256SUMS.json"}
    (output / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
