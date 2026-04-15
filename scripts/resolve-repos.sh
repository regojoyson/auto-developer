#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Shared helper — resolves repo directories from repos.json
#
#  Source this file, then use $REPO_DIRS (array) and $CLAUDE_DIR.
#
#  Usage:  source scripts/resolve-repos.sh
# ─────────────────────────────────────────────────────────

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="$SCRIPT_ROOT/.claude"

if [ ! -f "$SCRIPT_ROOT/repos.json" ]; then
  echo "repos.json not found" >&2
  return 1 2>/dev/null || exit 1
fi

MODE=$(node -e "console.log(require('$SCRIPT_ROOT/repos.json').mode || '')")

REPO_DIRS=()

if [ "$MODE" = "single" ]; then
  REPO_DIR=$(node -e "console.log(require('$SCRIPT_ROOT/repos.json').single?.repoDir || '')")
  [ -n "$REPO_DIR" ] && REPO_DIRS=("$REPO_DIR")

elif [ "$MODE" = "multi" ]; then
  PARENT_DIR=$(node -e "console.log(require('$SCRIPT_ROOT/repos.json').multi?.parentDir || '')")
  if [ -n "$PARENT_DIR" ] && [ -d "$PARENT_DIR" ]; then
    for d in "$PARENT_DIR"/*/; do
      [ -d "$d" ] && REPO_DIRS+=("${d%/}")
    done
  fi
fi
