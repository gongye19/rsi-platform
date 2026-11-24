#!/usr/bin/env python3
"""Generate current-user systemd units. Never starts paid experiments."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def unit_path(value):
    value = str(value)
    if any(char in value for char in ("\n", "\r", "\0")):
        raise ValueError("Invalid systemd path")
    return value.replace("%", "%%")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path.home() / ".config/systemd/user")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--enable", action="store_true", help="Enable/start API and idle Worker; requires Linux user systemd")
    parser.add_argument("--web", action="store_true", help="Also install built Next.js UI (Node required)")
    args = parser.parse_args()
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        parser.error("Run setup_linux.sh first")
    args.output.mkdir(parents=True, exist_ok=True)
    common = f'''[Unit]
Description=HarnessLens {{name}}
After=network.target

[Service]
Type=simple
WorkingDirectory={unit_path(ROOT)}
EnvironmentFile={unit_path(args.env_file.resolve())}
Environment=PYTHONUNBUFFERED=1
UMask=0077
ExecStart={{command}}
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
KillMode=control-group
NoNewPrivileges=true

[Install]
WantedBy=default.target
'''
    commands = {
        "api": f"{quote(python)} -m harnesslens.service api",
        "worker": f"{quote(python)} -m harnesslens.service worker",
    }
    if args.web:
        node = shutil.which("node")
        if not node or not (ROOT / "web/.next/BUILD_ID").is_file():
            parser.error("Build web/ with Bun and install Node first")
        commands["web"] = f"{quote(node)} {quote(ROOT / 'web/node_modules/next/dist/bin/next')} start --hostname 127.0.0.1 --port 3000"
    for name, command in commands.items():
        unit = common.replace("{name}", name).replace("{command}", command)
        if name == "web":
            unit = unit.replace("WorkingDirectory=" + unit_path(ROOT), "WorkingDirectory=" + unit_path(ROOT / "web"), 1)
        path = args.output / f"harnesslens-{name}.service"
        path.write_text(unit)
        print(path)
    if args.enable:
        if sys.platform != "linux" or os.geteuid() == 0:
            parser.error("Use a normal Linux user with systemd --user")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", *[f"harnesslens-{name}.service" for name in commands]], check=True)


if __name__ == "__main__":
    main()
