#!/usr/bin/env python3
"""Export the pinned 13-task data privately, separately from GitHub source."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "offline/crm-data.tar.gz")
    args = parser.parse_args()
    from harnesslens.core.config import load_repo_env
    from harnesslens.benchmarks.crm import checkout, data_fingerprint
    load_repo_env(ROOT)
    files = data_fingerprint(ROOT)
    base = checkout(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, "w:gz") as archive:
        for name in files:
            relative = name if name == "dataset_manifest.tsv" else "query_crmarenapro/" + name
            archive.add(base / relative, arcname="dataagentbench/" + relative, recursive=False)
        for name in ("LICENSE", "LICENSE.md", "README.md"):
            if (base / name).is_file():
                archive.add(base / name, arcname="dataagentbench/" + name, recursive=False)
    args.output.chmod(0o600)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(digest + "  " + args.output.name + "\n")
    print(json.dumps({"archive": str(args.output), "sha256": digest, "tasks": 13, "data_files": 6}))


if __name__ == "__main__":
    main()
