from pathlib import Path
import sys
import subprocess

import pytest

from harnesslens.infrastructure.process_isolation import (
    bubblewrap_command,
    isolated_child_env,
)


def test_isolated_child_env_drops_host_credentials_and_proxy_settings():
    env = isolated_child_env(
        {
            "PATH": "/usr/bin",
            "LANG": "C.UTF-8",
            "DEEPSEEK_API_KEY": "real-secret",
            "AWS_SESSION_TOKEN": "token",
            "HTTP_PROXY": "http://proxy",
        },
        overrides={"OPENAI_API_KEY": "editor-local-proxy", "HOME": "/job/home"},
    )

    assert env == {
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "OPENAI_API_KEY": "editor-local-proxy",
        "HOME": "/job/home",
    }


def test_isolated_child_env_rejects_explicit_real_secret():
    with pytest.raises(ValueError, match="contains credentials"):
        isolated_child_env({}, overrides={"OPENAI_API_KEY": "real-secret"})


def test_bubblewrap_exposes_only_declared_runtime_and_job_root(
    tmp_path: Path, monkeypatch
):
    job = tmp_path / "jobs" / "editor-01"
    cwd = job / "candidate"
    runtime = tmp_path / "runtime"
    cwd.mkdir(parents=True)
    runtime.mkdir()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)

    command = bubblewrap_command(
        [str(runtime / "agent"), "run"],
        writable_root=job,
        working_directory=cwd,
        read_only_roots=(runtime,),
    )

    joined = " ".join(command)
    assert f"--ro-bind {runtime} {runtime}" in joined
    assert f"--bind {job} {job}" in joined
    assert str(tmp_path / "private") not in joined
    assert command[-2:] == [str(runtime / "agent"), "run"]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt boundary")
def test_macos_editor_boundary_allows_job_but_denies_private_siblings(tmp_path):
    from harnesslens.infrastructure.process_isolation import seatbelt_command
    job = tmp_path / "job"
    job.mkdir()
    secret = tmp_path / "private.txt"
    secret.write_text("private")
    script = "from pathlib import Path; Path('allowed').write_text('ok'); " + f"Path({str(secret)!r}).read_text()"
    command = seatbelt_command([sys.executable, "-c", script], writable_root=job,
        working_directory=job, read_only_roots=(sys.base_prefix, sys.prefix))
    result = subprocess.run(command, cwd=job, capture_output=True)
    assert (job / "allowed").read_text() == "ok"
    assert result.returncode != 0
    assert b"Operation not permitted" in result.stderr
