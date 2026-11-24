from __future__ import annotations

import os
import shutil
import sys
import json
from pathlib import Path
from typing import Mapping, Sequence


_SAFE_ENV_NAMES = {
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "NO_COLOR",
    "PATH",
    "TERM",
    "TZ",
}
_SECRET_MARKERS = (
    "API_KEY",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "CREDENTIAL",
    "AUTH",
    "COOKIE",
)


def isolated_child_env(
    base: Mapping[str, str] | None = None,
    *,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = dict(base or os.environ)
    env = {
        key: str(value)
        for key, value in source.items()
        if key in _SAFE_ENV_NAMES or key.startswith("LC_")
    }
    env.update({str(key): str(value) for key, value in (overrides or {}).items()})
    leaked = sorted(
        key
        for key in env
        if any(marker in key.upper() for marker in _SECRET_MARKERS)
        and env[key] not in {"", "editor-local-proxy"}
    )
    if leaked:
        raise ValueError(f"isolated child environment contains credentials: {leaked}")
    return env


def bubblewrap_command(
    command: Sequence[str],
    *,
    writable_root: str | Path,
    working_directory: str | Path,
    read_only_roots: Sequence[str | Path] = (),
) -> list[str]:
    executable = shutil.which("bwrap")
    if not executable:
        if sys.platform == "darwin":
            return seatbelt_command(command, writable_root=writable_root,
                                    working_directory=working_directory, read_only_roots=read_only_roots)
        raise RuntimeError("bubblewrap is required for isolated Harness Editor calls")
    writable = Path(writable_root).resolve()
    cwd = Path(working_directory).resolve()
    try:
        cwd.relative_to(writable)
    except ValueError as exc:
        raise ValueError("isolated working directory must be under writable_root") from exc
    roots = [
        path
        for path in (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"), Path("/etc"))
        if path.exists()
    ]
    roots.extend(Path(path).resolve() for path in read_only_roots)
    args = [
        executable,
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    destinations = [*roots, writable]
    created: set[str] = set()
    for destination in destinations:
        for parent in reversed(destination.parents):
            text = str(parent)
            if text == "/" or text in created:
                continue
            args.extend(["--dir", text])
            created.add(text)
        text = str(destination)
        if destination.is_dir() and text not in created:
            args.extend(["--dir", text])
            created.add(text)
    seen: set[str] = set()
    for root in roots:
        text = str(root)
        if text in seen:
            continue
        args.extend(["--ro-bind", text, text])
        seen.add(text)
    args.extend(
        [
            "--bind",
            str(writable),
            str(writable),
            "--chdir",
            str(cwd),
            "--",
            *[str(item) for item in command],
        ]
    )
    return args


def seatbelt_command(command, *, writable_root, working_directory, read_only_roots=()):
    """macOS equivalent of the editor's declared filesystem boundary."""
    writable = Path(writable_root).resolve()
    cwd = Path(working_directory).resolve()
    if not cwd.is_relative_to(writable):
        raise ValueError("isolated working directory must be under writable_root")
    if not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("macOS sandbox-exec is required for the isolated editor")
    # /usr/share/zoneinfo and ICU timezone data resolve outside /usr on macOS.
    # Bun's JavaScriptCore traps during initialization if these cannot be read.
    roots = [Path(p).resolve() for p in ("/System", "/usr", "/bin", "/sbin", "/Library", "/private/etc", "/private/var/db/timezone", "/dev")]
    roots.extend(Path(p).resolve() for p in read_only_roots)
    quote = lambda p: json.dumps(str(p))
    rules = ["(version 1)", "(allow default)", '(deny file-read* file-write* (subpath "/"))', "(allow file-read-metadata)"]
    for parent in {p for root in [writable, *roots] for p in root.parents}:
        rules.append(f"(allow file-read* (literal {quote(parent)}))")
    for root in roots:
        rules.append(f"(allow file-read* (subpath {quote(root)}))")
    rules.append(f"(allow file-read* file-write* (subpath {quote(writable)}))")
    rules.append('(allow file-write* (subpath "/dev"))')
    return ["/usr/bin/sandbox-exec", "-p", "\n".join(rules), *map(str, command)]


def node_runtime_root() -> Path | None:
    executable = shutil.which("node")
    if not executable:
        return None
    resolved = Path(executable).resolve()
    for parent in resolved.parents:
        if parent.name == "node" and parent.parent.name == "installs":
            return parent
    return resolved.parent.parent


def check_editor_sandbox() -> str:
    """Exercise the filesystem boundary without invoking a model or business API."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(prefix="harnesslens-check-") as workspace, tempfile.TemporaryDirectory(prefix="harnesslens-private-") as private:
        marker = Path(private) / "marker"
        marker.write_text("probe")
        command = bubblewrap_command(
            ["/bin/sh", "-c", 'if cat "$1" >/dev/null 2>&1; then exit 1; fi; echo isolated', "probe", str(marker)],
            writable_root=workspace, working_directory=workspace,
            read_only_roots=[sys.prefix, sys.base_prefix])
        result = subprocess.run(command, text=True, capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError("Editor sandbox unavailable: " + result.stderr[-500:])
        return result.stdout.strip()
