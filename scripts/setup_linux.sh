#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" == Linux ]] || { echo 'Run this script on Linux.' >&2; exit 1; }
command -v uv >/dev/null
if [[ "${1:-}" == --offline ]]; then
  bundle="${2:?Usage: setup_linux.sh --offline /path/to/offline-bundle}"
  bundle="$(realpath "$bundle")"
  uv venv --python "${HAI_PYTHON:-python3.13}" --no-python-downloads .venv
  uv pip sync --python .venv/bin/python --require-hashes --no-index --find-links "$bundle/wheelhouse" "$bundle/requirements.lock.txt"
  .venv/bin/python scripts/install_opencode.py --offline --archive "$bundle/opencode/$(uname -m)/opencode.tar.gz"
else
  uv sync --locked --extra crm --extra tau2 --extra dev
  .venv/bin/python scripts/install_opencode.py
fi
if [[ ! -f .env ]]; then cp .env.example .env; fi
chmod 600 .env
echo 'Python/runtime ready. Fill private configuration, then run scripts/check_intranet.py.'
