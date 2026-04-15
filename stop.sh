#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — Stop + Cleanup
#
#  Usage:  ./stop.sh
#
#  1. Kills the webhook server and ngrok tunnel
#  2. Removes .claude/ symlinks from target repos
# ─────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

ok()   { echo -e "  ${GREEN}+${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }

echo ""
echo -e "${CYAN}  Stopping Auto-Pilot...${NC}"
echo ""

# ── 1. Kill processes ─────────────────────────────────────

KILLED=0

SERVER_PIDS=$(pgrep -f "node.*src/webhook/server.js" 2>/dev/null || true)
if [ -n "$SERVER_PIDS" ]; then
  echo "$SERVER_PIDS" | xargs kill 2>/dev/null
  ok "Webhook server stopped"
  KILLED=1
fi

NGROK_PIDS=$(pgrep -f "ngrok.*http" 2>/dev/null || true)
if [ -n "$NGROK_PIDS" ]; then
  echo "$NGROK_PIDS" | xargs kill 2>/dev/null
  ok "ngrok tunnel stopped"
  KILLED=1
fi

[ "$KILLED" -eq 0 ] && warn "No running processes found"

# ── 2. Remove symlinks ───────────────────────────────────

source scripts/resolve-repos.sh 2>/dev/null

CLEANED=0
CLAUDE_DIR="$DIR/.claude"

if [ ${#REPO_DIRS[@]} -gt 0 ]; then
  echo ""
  echo -e "${CYAN}  Cleaning up symlinks...${NC}"
  echo ""

  for REPO in "${REPO_DIRS[@]}"; do
    REPO_NAME=$(basename "$REPO")
    TARGET="$REPO/.claude"

    if [ -L "$TARGET" ]; then
      CURRENT=$(readlink "$TARGET")
      if [ "$CURRENT" = "$CLAUDE_DIR" ]; then
        rm "$TARGET"
        ok "$REPO_NAME — symlink removed"
        CLEANED=1
      else
        warn "$REPO_NAME — symlink points elsewhere, left alone"
      fi
    fi
    # Skip non-symlink .claude/ dirs — those aren't ours
  done

  [ "$CLEANED" -eq 0 ] && warn "No symlinks to clean up"
fi

echo ""
ok "Auto-Pilot stopped"
echo ""
