"""Optional initial OpenCode overlay, frozen locally before baseline evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile

from harnesslens.core.artifacts import write_json
from .harness_workspace import empty_workspace_snapshot, normalize_workspace_snapshot
from .opencode_harness import normalize_opencode_manifest

SCHEMA = "harnesslens.initial-harness.v1"


def identity(workspace, manifest):
    data = {"workspace": normalize_workspace_snapshot(workspace),
            "manifest": normalize_opencode_manifest(manifest)}
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    empty = data == {"workspace": empty_workspace_snapshot(), "manifest": normalize_opencode_manifest({})}
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "empty": empty, **data}


def load_initial_harness(source=None):
    if source is None or str(source) == "":
        return identity(None, {})
    path = Path(source).expanduser()
    if path.is_symlink():
        raise ValueError("Initial Harness cannot be a symlink")
    path = path.resolve()
    if path.is_file():
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Initial Harness package exceeds 32 MiB")
        package = json.loads(path.read_text())
        if not isinstance(package, dict) or package.get("schema") != "harnesslens.opencode-package.v1":
            raise ValueError("Initial Harness file must be an exported OpenCode Harness package")
        return identity(package["workspace"], package["manifest"])
    if not path.is_dir():
        raise ValueError("Initial Harness directory/package is missing")
    # A plain directory is the project overlay. Explicit home/project scopes
    # are also accepted for users who need both OpenCode discovery locations.
    scoped = (path / "project").exists() or (path / "home").exists()
    if scoped and any(item.name not in {"home", "project"} for item in path.iterdir()):
        raise ValueError("Scoped initial Harness may contain only home/ and project/")
    roots = {scope: path / scope for scope in ("home", "project")} if scoped else {"project": path}
    files = []
    total = 0
    for scope, root in roots.items():
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Initial Harness scopes must be directories without symlinks")
        for item in sorted(root.rglob("*")):
            if item.is_symlink():
                raise ValueError("Initial Harness cannot contain symlinks")
            if item.name == ".git" or item.name.startswith(".env") or item.name in {".venv", "node_modules"}:
                raise ValueError("Provide a dedicated Harness directory without credentials, Git or installed dependencies")
            if item.is_dir():
                continue
            metadata = item.stat()
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Initial Harness cannot contain special files")
            total += metadata.st_size
            if metadata.st_size > 2 * 1024 * 1024 or total > 16 * 1024 * 1024:
                raise ValueError("Initial Harness exceeds workspace size limits")
            files.append({"scope": scope, "path": item.relative_to(root).as_posix(),
                          "content": item.read_text(encoding="utf-8"), "executable": bool(metadata.st_mode & stat.S_IXUSR)})
    return identity({"schema": 1, "files": files}, {})


def freeze_initial_harness(*, run_root, cell, harness="opencode", source=None, run_id=None):
    source = None if source is None or str(source) == "" else source
    if harness != "opencode":
        if source is not None:
            raise ValueError("--initial-harness currently supports OpenCode only")
        return None
    run = Path(run_root).resolve()
    marker = run / "initial_harness.json"
    version = run / "rollout_evidence" / (run_id or run.name) / "versions_percell" / cell / "v0"
    native = version / "harness/opencode"
    requested = load_initial_harness(source) if source is not None else None
    if marker.is_file():
        recorded = json.loads(marker.read_text())
        frozen = identity(json.loads((native / "workspace.json").read_text()), json.loads((native / "manifest.json").read_text()))
        if recorded.get("schema") != SCHEMA or recorded.get("sha256") != frozen["sha256"]:
            raise ValueError("Frozen initial Harness changed; use a new run ID")
        if requested is not None and requested["sha256"] != frozen["sha256"]:
            raise ValueError("Initial Harness changed; use a new run ID")
        return frozen
    frozen = requested or load_initial_harness()
    if version.exists():
        if not (native / "workspace.json").is_file() or not (native / "manifest.json").is_file():
            raise ValueError("Incomplete initial Harness snapshot")
        existing = identity(json.loads((native / "workspace.json").read_text()), json.loads((native / "manifest.json").read_text()))
        if existing["sha256"] != frozen["sha256"]:
            raise ValueError("Existing v0 differs from initial Harness; use a new run ID")
    else:
        version.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".initial-", dir=version.parent))
        try:
            target = staging / "harness/opencode"
            write_json(target / "workspace.json", frozen["workspace"])
            write_json(target / "manifest.json", frozen["manifest"])
            write_json(staging / "lineage.json", {"version": "v0", "parent": None, "harness": harness})
            write_json(staging / "meta.json", {"version": "v0", "parent": None, "harness": harness, "status": "baseline", "temporary_candidate": False})
            from .opencode_components import protocol_manifest
            write_json(staging / "component_protocol.json", protocol_manifest())
            staging.rename(version)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    write_json(marker, {"schema": SCHEMA, "version": "v0", "sha256": frozen["sha256"], "empty": frozen["empty"],
                        "source": str(Path(source).expanduser().resolve()) if source is not None else None,
                        "snapshot_path": str(version)})
    return frozen
