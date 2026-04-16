#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — Setup (launches Python TUI wizard)
#
#  Prerequisite: Python 3.10+
#    macOS:   brew install python@3.12
#    Ubuntu:  sudo apt install python3.12 python3.12-venv
#    Windows: https://python.org/downloads/
# ─────────────────────────────────────────────────────────

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Find Python 3.10+ ────────────────────────────────

PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" &>/dev/null; then
    version=$("$candidate" -c "import sys; print(f'{sys.version_info.minor}')" 2>/dev/null)
    major=$("$candidate" -c "import sys; print(f'{sys.version_info.major}')" 2>/dev/null)
    if [ "$major" = "3" ] && [ "$version" -ge 10 ] 2>/dev/null; then
      PY="$candidate"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo ""
  echo -e "${RED}  Python 3.10+ is required but not found.${NC}"
  echo ""
  echo "  Install it first:"
  echo "    macOS:   brew install python@3.12"
  echo "    Ubuntu:  sudo apt install python3.12 python3.12-venv"
  echo "    Windows: https://python.org/downloads/"
  echo ""
  exit 1
fi

echo -e "  ${GREEN}Using $PY ($($PY --version 2>&1))${NC}"

# ── Create venv + install deps ────────────────────────

if [ ! -d "venv" ]; then
  echo -e "  ${CYAN}Creating virtual environment...${NC}"
  $PY -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt 2>&1 | tail -1

# ── Run the TUI wizard ────────────────────────────────

PYTHONPATH="$DIR" python3 installer/setup.py "$@"
