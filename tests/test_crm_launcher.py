import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/run_crm_experiment.py"
    spec = importlib.util.spec_from_file_location("crm_launcher", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr("harnesslens.service.config.ROOT", tmp_path)
    (tmp_path / "private.env").write_text("DEEPSEEK_API_KEY=local-test-only\n")
    source = tmp_path / "initial"; source.mkdir()
    (source / "AGENTS.md").write_text("Initial rules")
    profile = tmp_path / "local.toml"
    profile.write_text('schema="harnesslens.experiment.v1"\nbenchmark="crm"\nenv_file="private.env"\ninitial_harness="initial"\n')
    return module, profile


def test_default_launcher_checks_only_and_never_launches_models(launcher, monkeypatch):
    module, profile = launcher
    calls = []
    monkeypatch.setattr(module, "execute", lambda command, env, stage, directory: calls.append((stage, command)))
    module.run(profile_path=profile, identity="one")
    assert [stage for stage, _ in calls] == ["offline_preflight"]
    assert "--smoke" not in calls[0][1]


@pytest.mark.parametrize("selected", ["v0", "candidate-01"])
def test_launcher_train_then_frozen_test_and_avoids_duplicate_v0_test(launcher, monkeypatch, selected):
    module, profile = launcher
    calls = []
    def fake(command, env, stage, directory):
        assert env["DEEPSEEK_API_KEY"] == "local-test-only"
        calls.append((stage, command))
        if stage == "train":
            from harnesslens.harnesses.initial_harness import freeze_initial_harness
            root = module.ROOT / "runs/train/one"
            freeze_initial_harness(run_root=root, cell="crmarenapro", source=module.ROOT / "initial")
            final = root / "submission/final.json"; final.parent.mkdir()
            final.write_text(json.dumps({"selected_version": selected}))
    monkeypatch.setattr(module, "execute", fake)
    module.run(profile_path=profile, identity="one", live=True)
    assert [stage for stage, _ in calls][:4] == ["offline_preflight", "paid_smoke", "train", "test_initial"]
    assert [stage for stage, _ in calls][4:] == ([] if selected == "v0" else ["test_selected"])
    baseline_args = next(args for stage, args in calls if stage == "test_initial")
    initial_package = Path(baseline_args[baseline_args.index("--initial-harness") + 1])
    assert "Initial rules" in initial_package.read_text()
    result = json.loads((module.ROOT / "runs/local_experiments/one/result.json").read_text())
    assert result["selected_equals_initial"] == (selected == "v0")


def test_launcher_stops_after_failed_smoke_without_training(launcher, monkeypatch):
    module, profile = launcher
    stages = []
    def fake(command, env, stage, directory):
        stages.append(stage)
        if stage == "paid_smoke": raise RuntimeError("provider unavailable")
    monkeypatch.setattr(module, "execute", fake)
    with pytest.raises(RuntimeError, match="unavailable"):
        module.run(profile_path=profile, identity="one", live=True)
    assert stages == ["offline_preflight", "paid_smoke"]
