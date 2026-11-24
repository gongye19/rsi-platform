"""Content-addressed, self-contained local delivery artifact for a selected harness."""
import hashlib
import json
from pathlib import Path

from harnesslens.harnesses.opencode_components import protocol_manifest
from harnesslens.harnesses.harness_workspace import normalize_workspace_snapshot


def export_package(*, directory, version, workspace, manifest, experiment=None):
    payload = {"schema": "harnesslens.opencode-package.v1", "version": str(version),
               "component_protocol": protocol_manifest(), "workspace": normalize_workspace_snapshot(workspace),
               "manifest": manifest, "experiment_contract": experiment or {}}
    data = (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    path = Path(directory) / f"harness-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as out:
            out.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("Existing content-addressed OpenCode package changed")
    return {"path": str(path.resolve()), "sha256": digest, "version": str(version)}
