#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — Setup
#
#  Usage:  ./setup.sh
#
#  Reads repos.json and symlinks .claude/ into each target
#  repo so Claude Code CLI can find the agent configs.
# ─────────────────────────────────────────────────────────

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

ok()   { echo -e "  ${GREEN}+${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

source scripts/resolve-repos.sh || fail "Could not read repos.json"

[ ${#REPO_DIRS[@]} -eq 0 ] && fail "No repos found — check repos.json"

echo ""
echo -e "${CYAN}  Auto-Pilot Setup${NC}"
echo -e "  Mode: ${CYAN}$MODE${NC} | Repos: ${CYAN}${#REPO_DIRS[@]}${NC}"
echo ""

for REPO in "${REPO_DIRS[@]}"; do
  REPO_NAME=$(basename "$REPO")
  TARGET="$REPO/.claude"

  if [ -L "$TARGET" ]; then
    CURRENT=$(readlink "$TARGET")
    if [ "$CURRENT" = "$CLAUDE_DIR" ]; then
      ok "$REPO_NAME — already linked"
    else
      warn "$REPO_NAME — symlink exists but points elsewhere (skipped)"
    fi
  elif [ -d "$TARGET" ]; then
    warn "$REPO_NAME — .claude/ directory already exists (skipped)"
  else
    ln -s "$CLAUDE_DIR" "$TARGET"
    ok "$REPO_NAME — linked .claude/"
  fi
done

echo ""
echo -e "${GREEN}  Done.${NC} Run ${CYAN}./start.sh${NC} to start the pipeline."
echo ""
