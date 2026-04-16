#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — Setup (launches Python TUI wizard)
# ─────────────────────────────────────────────────────────

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PY="python3"
command -v python3.12 &>/dev/null && PY="python3.12"

# Ensure venv exists and deps installed
if [ ! -d "venv" ]; then
  $PY -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt 2>&1 | tail -1

# Run the TUI wizard (PYTHONPATH ensures installer/ is importable)
PYTHONPATH="$DIR" python3 installer/setup.py "$@"
