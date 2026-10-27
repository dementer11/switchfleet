#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_command="${PYTHON:-python3}"
"$python_command" -c 'import sys; assert sys.version_info >= (3, 11), "SwitchFleet Ansible requires Python 3.11 or newer"'
if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
  "$python_command" -m venv "$project_dir/.venv"
fi
"$project_dir/.venv/bin/python" -m pip install "$project_dir[fleet]"
printf '\nSwitchFleet installed. Start with:\n  "%s/.venv/bin/switchfleet-ui"\n\nOpen http://127.0.0.1:8787\n' "$project_dir"
