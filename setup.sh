#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — Interactive Setup Wizard
#
#  Usage:  ./setup.sh
#
#  If config.yaml doesn't exist: asks questions and generates it.
#  Then symlinks .claude/ into the target repo(s).
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
ask()  { echo -en "  ${CYAN}?${NC} $1"; }

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Auto-Pilot Setup${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo ""

# ── Check if config.yaml exists ───────────────────────

RUN_WIZARD=false

if [ ! -f "config.yaml" ]; then
  RUN_WIZARD=true
else
  echo -e "  config.yaml already exists.\n"
  ask "Do you want to reconfigure? (y/n) [n]: "
  read -r RECONFIG
  echo ""
  if [ "$RECONFIG" = "y" ] || [ "$RECONFIG" = "Y" ]; then
    RUN_WIZARD=true
    mv config.yaml config.yaml.bak
    ok "Old config backed up to config.yaml.bak"
    echo ""
  fi
fi

# ── Interactive wizard ────────────────────────────────

if [ "$RUN_WIZARD" = true ]; then
  echo -e "  Let's configure Auto Developer.\n"

  # --- Repo mode ---
  echo -e "  ${CYAN}Where is your code?${NC}"
  echo "    1) Local directory (one repo)"
  echo "    2) Parent directory (multiple repos)"
  echo "    3) Clone from git URL(s)"
  ask "Choice [1/2/3]: "
  read -r REPO_CHOICE
  echo ""

  REPO_SECTION=""
  case "$REPO_CHOICE" in
    1)
      ask "Repo path: "
      read -r REPO_PATH
      ask "Base branch [main]: "
      read -r BASE_BRANCH
      BASE_BRANCH=${BASE_BRANCH:-main}
      REPO_SECTION="repo:\n  mode: dir\n  path: $REPO_PATH\n  baseBranch: $BASE_BRANCH"
      ;;
    2)
      ask "Parent directory path: "
      read -r PARENT_PATH
      ask "Base branch [main]: "
      read -r BASE_BRANCH
      BASE_BRANCH=${BASE_BRANCH:-main}
      REPO_SECTION="repo:\n  mode: parentDir\n  path: $PARENT_PATH\n  baseBranch: $BASE_BRANCH"
      ;;
    3)
      ask "Git URL(s) (comma-separated): "
      read -r URLS_RAW
      ask "Clone directory [/tmp/auto-pilot-repos]: "
      read -r CLONE_DIR
      CLONE_DIR=${CLONE_DIR:-/tmp/auto-pilot-repos}
      ask "Base branch [main]: "
      read -r BASE_BRANCH
      BASE_BRANCH=${BASE_BRANCH:-main}
      # Build YAML urls list
      URL_LIST=""
      IFS=',' read -ra URL_ARRAY <<< "$URLS_RAW"
      for url in "${URL_ARRAY[@]}"; do
        url=$(echo "$url" | xargs)  # trim whitespace
        URL_LIST="${URL_LIST}\n    - ${url}"
      done
      REPO_SECTION="repo:\n  mode: clone\n  urls:${URL_LIST}\n  cloneDir: $CLONE_DIR\n  baseBranch: $BASE_BRANCH"
      ;;
    *)
      fail "Invalid choice"
      ;;
  esac
  echo ""

  # --- Issue tracker ---
  ask "Issue tracker (jira / github-issues) [jira]: "
  read -r TRACKER
  TRACKER=${TRACKER:-jira}

  ask "Trigger status [Ready for Development]: "
  read -r TRIGGER_STATUS
  TRIGGER_STATUS=${TRIGGER_STATUS:-Ready for Development}

  ask "Done status [Done]: "
  read -r DONE_STATUS
  DONE_STATUS=${DONE_STATUS:-Done}
  echo ""

  # --- Git provider ---
  ask "Git provider (gitlab / github) [gitlab]: "
  read -r GIT_PROV
  GIT_PROV=${GIT_PROV:-gitlab}
  echo ""

  # --- CLI adapter ---
  ask "AI coding CLI (claude-code / codex / gemini) [claude-code]: "
  read -r CLI_TYPE
  CLI_TYPE=${CLI_TYPE:-claude-code}
  echo ""

  # --- Notification ---
  ask "Enable notifications? (y/n) [n]: "
  read -r NOTIF_ENABLE
  NOTIF_SECTION=""
  if [ "$NOTIF_ENABLE" = "y" ] || [ "$NOTIF_ENABLE" = "Y" ]; then
    ask "Notification type (slack) [slack]: "
    read -r NOTIF_TYPE
    NOTIF_TYPE=${NOTIF_TYPE:-slack}
    ask "Channel name: "
    read -r NOTIF_CHANNEL
    NOTIF_SECTION="\nnotification:\n  type: $NOTIF_TYPE\n  channel: $NOTIF_CHANNEL"
  fi
  echo ""

  # --- Write config.yaml ---
  echo -e "$REPO_SECTION

issueTracker:
  type: $TRACKER
  triggerStatus: $TRIGGER_STATUS
  doneStatus: $DONE_STATUS

gitProvider:
  type: $GIT_PROV

cliAdapter:
  type: $CLI_TYPE

pipeline:
  maxReworkIterations: 3
  agentTimeout: 300000
  port: 3000${NOTIF_SECTION}" > config.yaml

  ok "config.yaml generated"
  echo ""

  # --- Create .env if missing ---
  if [ ! -f ".env" ]; then
    cp .env.example .env
    ok ".env created — fill in your tokens"
  fi
fi

# ── Link agent files into repos ───────────────────────

source scripts/resolve-repos.sh 2>/dev/null || fail "Could not read config.yaml"

if [ ${#REPO_DIRS[@]} -eq 0 ]; then
  warn "No repo directories found — check config.yaml"
  exit 0
fi

# Get CLI-specific directories (e.g. .claude/agents, .claude)
CLI_AGENT_DIR=$(node src/providers/cli-dirs.js agentDir 2>/dev/null || echo ".claude/agents")
CLI_CONFIG_DIR=$(node src/providers/cli-dirs.js configDir 2>/dev/null || echo ".claude")

echo -e "  CLI agent dir: ${CYAN}${CLI_AGENT_DIR}${NC}"
echo -e "  Linking agent files into repos..."
echo ""

AGENTS_SRC="$DIR/.claude/agents"

for REPO in "${REPO_DIRS[@]}"; do
  REPO_NAME=$(basename "$REPO")

  if [ ! -d "$REPO" ]; then
    warn "$REPO_NAME — directory does not exist yet (will link after clone)"
    continue
  fi

  # 1. Symlink .auto-developer/ as a reference to our project's .claude/
  AD_LINK="$REPO/.auto-developer"
  if [ -L "$AD_LINK" ]; then
    ok "$REPO_NAME — .auto-developer/ already linked"
  elif [ ! -d "$AD_LINK" ]; then
    ln -s "$DIR/.claude" "$AD_LINK"
    ok "$REPO_NAME — linked .auto-developer/"
  fi

  # 2. Create CLI agent directory if it doesn't exist
  mkdir -p "$REPO/$CLI_AGENT_DIR"

  # 3. Symlink each agent .md file individually
  for AGENT_FILE in "$AGENTS_SRC"/*.md; do
    [ ! -f "$AGENT_FILE" ] && continue
    AGENT_NAME=$(basename "$AGENT_FILE")
    TARGET="$REPO/$CLI_AGENT_DIR/$AGENT_NAME"

    if [ -L "$TARGET" ]; then
      ok "$REPO_NAME — $AGENT_NAME already linked"
    elif [ -f "$TARGET" ]; then
      warn "$REPO_NAME — $AGENT_NAME already exists (skipped)"
    else
      ln -s "$AGENT_FILE" "$TARGET"
      ok "$REPO_NAME — linked $AGENT_NAME"
    fi
  done

  # 4. Symlink CLAUDE.md (global rules) into CLI config dir
  mkdir -p "$REPO/$CLI_CONFIG_DIR"
  RULES_TARGET="$REPO/$CLI_CONFIG_DIR/CLAUDE.md"
  if [ -L "$RULES_TARGET" ]; then
    ok "$REPO_NAME — CLAUDE.md already linked"
  elif [ -f "$RULES_TARGET" ]; then
    warn "$REPO_NAME — CLAUDE.md already exists (skipped)"
  else
    ln -s "$DIR/.claude/CLAUDE.md" "$RULES_TARGET"
    ok "$REPO_NAME — linked CLAUDE.md"
  fi
done

echo ""
echo -e "${GREEN}  Done.${NC} Run ${CYAN}./start.sh${NC} to start the pipeline."
echo ""
