#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — Stop + Cleanup
#
#  Usage:  ./stop.sh
#
#  1. Kills the webhook server
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

[ "$KILLED" -eq 0 ] && warn "No running processes found"

# ── 2. Remove symlinks ───────────────────────────────────

cd "$DIR"
source scripts/resolve-repos.sh 2>/dev/null

CLEANED=0
AGENTS_SRC="$DIR/agents"

# Get CLI-specific dirs
CLI_AGENT_DIR=$(node src/providers/cli-dirs.js agentDir 2>/dev/null || echo ".claude/agents")
CLI_CONFIG_DIR=$(node src/providers/cli-dirs.js configDir 2>/dev/null || echo ".claude")
CLI_RULES_FILE=$(node src/providers/cli-dirs.js rulesFileName 2>/dev/null || echo "CLAUDE.md")

if [ ${#REPO_DIRS[@]} -gt 0 ]; then
  echo ""
  echo -e "${CYAN}  Cleaning up symlinks...${NC}"
  echo ""

  for REPO in "${REPO_DIRS[@]}"; do
    [ ! -d "$REPO" ] && continue
    REPO_NAME=$(basename "$REPO")

    # Remove .auto-developer symlink
    AD_LINK="$REPO/.auto-developer"
    if [ -L "$AD_LINK" ]; then
      rm "$AD_LINK"
      ok "$REPO_NAME — .auto-developer/ removed"
      CLEANED=1
    fi

    # Remove individual agent file symlinks (only if they point to us)
    for AGENT_FILE in "$AGENTS_SRC"/*.md; do
      [ ! -f "$AGENT_FILE" ] && continue
      AGENT_NAME=$(basename "$AGENT_FILE")
      TARGET="$REPO/$CLI_AGENT_DIR/$AGENT_NAME"

      if [ -L "$TARGET" ]; then
        LINK_TARGET=$(readlink "$TARGET")
        if [ "$LINK_TARGET" = "$AGENT_FILE" ]; then
          rm "$TARGET"
          ok "$REPO_NAME — $AGENT_NAME removed"
          CLEANED=1
        fi
      fi
    done

    # Remove rules file symlink (only if it points to our RULES.md)
    RULES_TARGET="$REPO/$CLI_CONFIG_DIR/$CLI_RULES_FILE"
    if [ -L "$RULES_TARGET" ]; then
      LINK_TARGET=$(readlink "$RULES_TARGET")
      if [ "$LINK_TARGET" = "$DIR/agents/RULES.md" ]; then
        rm "$RULES_TARGET"
        ok "$REPO_NAME — $CLI_RULES_FILE removed"
        CLEANED=1
      fi
    fi
  done

  [ "$CLEANED" -eq 0 ] && warn "No symlinks to clean up"
fi

echo ""
ok "Auto-Pilot stopped"
echo ""
