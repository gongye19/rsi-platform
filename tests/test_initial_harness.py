import importlib
import json
from pathlib import Path

import pytest

from harnesslens.harnesses.initial_harness import load_initial_harness, freeze_initial_harness
from harnesslens.harnesses.opencode_package import export_package
from harnesslens.evaluation.rollout_bridge import CellHarnessRepository
from harnesslens.evaluation.blind_test_eval import _load_workspace_submission
from harnesslens.core.artifacts import content_digest
from harnesslens.harnesses.harness_workspace import workspace_digest
from harnesslens.service.config import load_profile, invocation
from harnesslens.service.store import Store


def test_default_empty_v0_and_export_roundtrip(tmp_path):
    run = tmp_path / "runs/train/empty"
    frozen = freeze_initial_harness(run_root=run, cell="crmarenapro")
    assert frozen["empty"] and frozen["workspace"]["files"] == []
    record = json.loads((run / "initial_harness.json").read_text())
    assert record["source"] is None
    assert Path(record["snapshot_path"]).joinpath("harness/opencode/workspace.json").is_file()
    package = export_package(directory=tmp_path / "packages", version="v0", workspace=frozen["workspace"], manifest=frozen["manifest"])
    assert load_initial_harness(package["path"]) == frozen


def test_nonempty_frozen_v0_inheritance_and_no_source_overwrite(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "AGENTS.md").write_text("Initial rules")
    skill = source / ".opencode/skills/a/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: a\ndescription: Initial skill\n---\nOriginal skill body")
    run = tmp_path / "runs/train/nonempty"
    frozen = freeze_initial_harness(run_root=run, cell="crmarenapro", source=source)
    assert not frozen["empty"]
    repo = CellHarnessRepository(cell="crmarenapro", repo_root=tmp_path, run_id="nonempty", evidence_root=run / "rollout_evidence")
    child = repo.materialize_candidate(base_version="v0", candidate_label="candidate-01", delta={"instructions": ["Candidate rule"]})
    assert repo.read_workspace_snapshot(child) == frozen["workspace"]
    assert repo.read_candidate_snapshot(child)["instructions"] == ["Candidate rule"]
    assert (source / "AGENTS.md").read_text() == "Initial rules"
    (source / "AGENTS.md").write_text("Edited outside experiment")
    # Omitted on resume: load the frozen v0. Explicit changed input: reject.
    assert freeze_initial_harness(run_root=run, cell="crmarenapro") == frozen
    with pytest.raises(ValueError, match="changed"):
        freeze_initial_harness(run_root=run, cell="crmarenapro", source=source)


def test_explicit_changed_initial_and_corrupted_frozen_snapshot_reject(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    (source / "AGENTS.md").write_text("Before")
    run = tmp_path / "runs/train/one"
    freeze_initial_harness(run_root=run, cell="crmarenapro", source=source)
    record = json.loads((run / "initial_harness.json").read_text())
    workspace = Path(record["snapshot_path"]) / "harness/opencode/workspace.json"
    workspace.write_text('{"files": []}')
    with pytest.raises(ValueError, match="changed"):
        freeze_initial_harness(run_root=run, cell="crmarenapro")


@pytest.mark.parametrize("kind", ["symlink", "secret", "binary"])
def test_initial_directory_is_a_dedicated_bounded_text_input(tmp_path, kind):
    source = tmp_path / "source"; source.mkdir()
    outside = tmp_path / "outside"; outside.write_text("private")
    if kind == "symlink": (source / "AGENTS.md").symlink_to(outside)
    if kind == "secret": (source / ".env").write_text("KEY=private")
    if kind == "binary": (source / "binary").write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError):
        load_initial_harness(source)


def test_scoped_directory_and_exported_package_retain_files(tmp_path):
    source = tmp_path / "input"
    (source / "home").mkdir(parents=True)
    (source / "project").mkdir()
    (source / "home/opencode.json").write_text('{"agent":{"build":{"prompt":"Native prompt"}}}')
    (source / "project/AGENTS.md").write_text("Initial")
    first = load_initial_harness(source)
    package = export_package(directory=tmp_path / "packages", version="candidate-02", workspace=first["workspace"], manifest=first["manifest"])
    assert load_initial_harness(package["path"]) == first


def test_profile_optional_initial_and_queue_detects_input_changes(tmp_path):
    path = tmp_path / "experiment.toml"
    base = 'schema="harnesslens.experiment.v1"\nbenchmark="crm"\n'
    path.write_text(base)
    profile = load_profile(path)
    assert profile["initial_harness"] == ""
    assert "--initial-harness" not in invocation(profile, "one")[0]
    source = tmp_path / "initial"; source.mkdir()
    (source / "AGENTS.md").write_text("One")
    path.write_text(base + 'initial_harness="initial"\n')
    profile = load_profile(path)
    command = invocation(profile, "one")[0]
    assert command[command.index("--initial-harness") + 1] == str(source)
    store = Store(tmp_path / "state")
    store.create("one", path)
    (source / "AGENTS.md").write_text("Changed before start")
    with pytest.raises(ValueError, match="changed"):
        store.transition("one", "start")


def test_initial_v0_history_and_final_submission_do_not_become_empty(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir()
    (source / "AGENTS.md").write_text("Initial baseline survives rollback")
    run = tmp_path / "runs/train/one"
    frozen = freeze_initial_harness(run_root=run, cell="crmarenapro", source=source)
    marker = json.loads((run / "initial_harness.json").read_text())
    submission = run / "submission/final.json"; submission.parent.mkdir()
    submission.write_text(json.dumps({"snapshot_path": marker["snapshot_path"], "selected_version": "v0",
        "workspace_digest": workspace_digest(frozen["workspace"]), "patch_digest": content_digest(frozen["manifest"])}))
    loaded = _load_workspace_submission(submission, repo_root=tmp_path, harness="opencode")
    assert loaded["workspace"] == frozen["workspace"]
    module = importlib.import_module("harnesslens.service.history")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    history = module.history("one")
    version = next(row for row in history["versions"] if row["component_id"] == "instructions_rules")
    assert version["present"] and "Initial" in version["files"][0]["diff"]
    assert history["steps"][-1]["active_bundle_id"] == "v0"
