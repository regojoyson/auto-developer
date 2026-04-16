#!/usr/bin/env bash
# Shared helper — resolves repo directories from config.yaml via Python.

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="$SCRIPT_ROOT/agents"

if [ ! -f "$SCRIPT_ROOT/config.yaml" ]; then
  echo "config.yaml not found" >&2
  return 1 2>/dev/null || exit 1
fi

PY="python3"
command -v python3.12 &>/dev/null && PY="python3.12"

MODE=$($PY -c "import yaml; c=yaml.safe_load(open('$SCRIPT_ROOT/config.yaml')); print(c.get('repo',{}).get('mode',''))" 2>/dev/null)
REPO_DIRS=()

if [ "$MODE" = "dir" ]; then
  REPO_DIR=$($PY -c "import yaml; c=yaml.safe_load(open('$SCRIPT_ROOT/config.yaml')); print(c.get('repo',{}).get('path',''))" 2>/dev/null)
  [ -n "$REPO_DIR" ] && REPO_DIRS=("$REPO_DIR")

elif [ "$MODE" = "parentDir" ]; then
  PARENT_DIR=$($PY -c "import yaml; c=yaml.safe_load(open('$SCRIPT_ROOT/config.yaml')); print(c.get('repo',{}).get('path',''))" 2>/dev/null)
  if [ -n "$PARENT_DIR" ] && [ -d "$PARENT_DIR" ]; then
    for d in "$PARENT_DIR"/*/; do
      [ -d "$d" ] && REPO_DIRS+=("${d%/}")
    done
  fi

elif [ "$MODE" = "clone" ]; then
  CLONE_DIR=$($PY -c "import yaml; c=yaml.safe_load(open('$SCRIPT_ROOT/config.yaml')); print(c.get('repo',{}).get('cloneDir','/tmp/auto-pilot-repos'))" 2>/dev/null)
  URLS=$($PY -c "import yaml; c=yaml.safe_load(open('$SCRIPT_ROOT/config.yaml')); [print(u) for u in c.get('repo',{}).get('urls',[])]" 2>/dev/null)
  if [ -n "$URLS" ]; then
    while IFS= read -r url; do
      repo_name=$(basename "$url" .git)
      REPO_DIRS+=("$CLONE_DIR/$repo_name")
    done <<< "$URLS"
  fi
fi
