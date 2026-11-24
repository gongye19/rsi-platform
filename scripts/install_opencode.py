#!/usr/bin/env python3
"""Install a checksum-pinned runtime online or from an offline archive."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--platform")
    args = parser.parse_args()
    pin = json.loads((ROOT / "configs/opencode-assets.json").read_text())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(platform.machine())
    host = f"{platform.system().lower()}-{arch}"
    target = args.platform or host
    if target not in pin["assets"] or (target != host and not args.download_only):
        parser.error("Unsupported platform or cross-platform installation")
    asset = pin["assets"][target]
    directory = ROOT / "runtime" / (f"opencode-{pin['version']}" if target == host else target)
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / asset["name"]
    if args.archive:
        if digest(args.archive) != asset["sha256"]:
            raise SystemExit("Archive checksum mismatch")
        if args.archive.resolve() != archive.resolve():
            shutil.copyfile(args.archive, archive)
    if not archive.is_file():
        if args.offline:
            raise SystemExit("Offline archive missing; supply --archive")
        url = f"https://github.com/anomalyco/opencode/releases/download/v{pin['version']}/{asset['name']}"
        temporary = archive.with_suffix(".download")
        with urllib.request.urlopen(url, timeout=60) as source, temporary.open("wb") as out:
            shutil.copyfileobj(source, out)
        temporary.replace(archive)
    if digest(archive) != asset["sha256"]:
        raise SystemExit("Archive checksum mismatch")
    if args.download_only:
        print(archive)
        return
    binary = directory / "bin/opencode"
    manifest = directory / "runtime-manifest.json"
    if binary.is_file():
        expected = json.loads(manifest.read_text()).get("binary_sha256") if manifest.is_file() else None
        if not expected or digest(binary) != expected:
            raise SystemExit("Existing pinned runtime changed; refusing overwrite")
        print(binary)
        return
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as package:
            members = [m for m in package.infolist() if not m.is_dir() and Path(m.filename).name == "opencode"]
            if len(members) != 1:
                raise SystemExit("Unexpected archive")
            content = package.read(members[0])
    else:
        with tarfile.open(archive) as package:
            members = [m for m in package.getmembers() if m.isfile() and Path(m.name).name == "opencode"]
            if len(members) != 1:
                raise SystemExit("Unexpected archive")
            content = package.extractfile(members[0]).read()
    binary.parent.mkdir(exist_ok=True)
    binary.write_bytes(content)
    binary.chmod(0o755)
    version = subprocess.check_output([str(binary), "--version"], text=True, timeout=30).strip()
    if version != pin["version"]:
        raise SystemExit("Installed runtime version mismatch")
    manifest.write_text(json.dumps({"version": version, "platform": target,
        "archive_sha256": asset["sha256"], "binary_sha256": digest(binary)}, indent=2) + "\n")
    print(binary)


if __name__ == "__main__":
    main()
