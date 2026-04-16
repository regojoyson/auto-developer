#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Shared helper — resolves repo directories from config.yaml
#
#  Source this file, then use $REPO_DIRS (array) and $CLAUDE_DIR.
# ─────────────────────────────────────────────────────────

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="$SCRIPT_ROOT/.claude"

if [ ! -f "$SCRIPT_ROOT/config.yaml" ]; then
  echo "config.yaml not found" >&2
  return 1 2>/dev/null || exit 1
fi

MODE=$(node -e "const y=require('js-yaml'),f=require('fs');const c=y.load(f.readFileSync('$SCRIPT_ROOT/config.yaml','utf-8'));console.log(c.repo?.mode||'')")
REPO_DIRS=()

if [ "$MODE" = "dir" ]; then
  REPO_DIR=$(node -e "const y=require('js-yaml'),f=require('fs');const c=y.load(f.readFileSync('$SCRIPT_ROOT/config.yaml','utf-8'));console.log(c.repo?.path||'')")
  [ -n "$REPO_DIR" ] && REPO_DIRS=("$REPO_DIR")

elif [ "$MODE" = "parentDir" ]; then
  PARENT_DIR=$(node -e "const y=require('js-yaml'),f=require('fs');const c=y.load(f.readFileSync('$SCRIPT_ROOT/config.yaml','utf-8'));console.log(c.repo?.path||'')")
  if [ -n "$PARENT_DIR" ] && [ -d "$PARENT_DIR" ]; then
    for d in "$PARENT_DIR"/*/; do
      [ -d "$d" ] && REPO_DIRS+=("${d%/}")
    done
  fi

elif [ "$MODE" = "clone" ]; then
  CLONE_DIR=$(node -e "const y=require('js-yaml'),f=require('fs');const c=y.load(f.readFileSync('$SCRIPT_ROOT/config.yaml','utf-8'));console.log(c.repo?.cloneDir||'/tmp/auto-pilot-repos')")
  URLS=$(node -e "const y=require('js-yaml'),f=require('fs');const c=y.load(f.readFileSync('$SCRIPT_ROOT/config.yaml','utf-8'));(c.repo?.urls||[]).forEach(u=>console.log(u))")
  if [ -n "$URLS" ]; then
    while IFS= read -r url; do
      repo_name=$(basename "$url" .git)
      REPO_DIRS+=("$CLONE_DIR/$repo_name")
    done <<< "$URLS"
  fi
fi
