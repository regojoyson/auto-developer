#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — One-shot startup script
#
#  Reads config.yaml + .env, validates, starts webhook server.
# ─────────────────────────────────────────────────────────

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

PY="python3"
command -v python3.12 &>/dev/null && PY="python3.12"

# Helper to read config.yaml via Python
cfg() { $PY -c "import yaml; c=yaml.safe_load(open('config.yaml')); print($1)"; }

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  AI Dev Pipeline — Auto-Pilot Startup${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo ""

# ── 1. Prerequisites ──────────────────────────────────

info "Checking prerequisites..."

$PY --version &>/dev/null || fail "Python 3.10+ is not installed."
PY_VERSION=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VERSION"

# ── 2. Config files ───────────────────────────────────

[ ! -f "config.yaml" ] && fail "config.yaml not found — run ./setup.sh first"
ok "config.yaml exists"

if [ ! -f ".env" ]; then
  cp .env.example .env
  warn ".env created — fill in your tokens, then re-run"
  exit 0
fi
ok ".env exists"

# ── 3. Read config ────────────────────────────────────

GIT_PROVIDER=$(cfg "c.get('gitProvider',{}).get('type','')")
ISSUE_TRACKER=$(cfg "c.get('issueTracker',{}).get('type','')")
CLI_ADAPTER=$(cfg "c.get('cliAdapter',{}).get('type','claude-code')")
REPO_MODE=$(cfg "c.get('repo',{}).get('mode','')")
PORT=$(cfg "c.get('pipeline',{}).get('port',3000)")

[ -z "$GIT_PROVIDER" ] && fail "config.yaml: gitProvider.type not set"
[ -z "$ISSUE_TRACKER" ] && fail "config.yaml: issueTracker.type not set"
[ -z "$REPO_MODE" ] && fail "config.yaml: repo.mode not set"

ok "Providers: $ISSUE_TRACKER + $GIT_PROVIDER + $CLI_ADAPTER"
ok "Repo mode: $REPO_MODE"

# ── 4. Install dependencies ──────────────────────────

info "Installing dependencies..."

if [ -d "venv" ]; then
  source venv/bin/activate
  ok "Virtual environment activated"
else
  $PY -m venv venv
  source venv/bin/activate
  ok "Virtual environment created"
fi

pip install -q -r requirements.txt 2>&1 | tail -1
ok "Python dependencies installed"

# ── 5. Validate secrets ──────────────────────────────

info "Validating secrets..."
set -a; source .env 2>/dev/null; set +a

if [ "$GIT_PROVIDER" = "gitlab" ]; then
  [ -z "$GITLAB_TOKEN" ] && fail "GITLAB_TOKEN not set in .env"
  ok "GitLab token OK (project ID auto-detected from git remote)"
elif [ "$GIT_PROVIDER" = "github" ]; then
  [ -z "$GITHUB_TOKEN" ] && fail "GITHUB_TOKEN not set in .env"
  ok "GitHub token OK (owner/repo auto-detected from git remote)"
fi

# ── 6. Validate repo ─────────────────────────────────

if [ "$REPO_MODE" = "dir" ]; then
  REPO_PATH=$(cfg "c.get('repo',{}).get('path','')")
  [ ! -d "$REPO_PATH" ] && fail "Repo dir does not exist: $REPO_PATH"
  ok "Repo: $REPO_PATH"
elif [ "$REPO_MODE" = "parentDir" ]; then
  REPO_PATH=$(cfg "c.get('repo',{}).get('path','')")
  [ ! -d "$REPO_PATH" ] && fail "Parent dir does not exist: $REPO_PATH"
  ok "Repos: $REPO_PATH"
elif [ "$REPO_MODE" = "clone" ]; then
  URL_COUNT=$(cfg "len(c.get('repo',{}).get('urls',[]))")
  ok "Clone mode: $URL_COUNT URL(s)"
fi

# ── 7. Generate CLI settings ──────────────────────────

info "Generating MCP config..."

CLI_CONFIG_DIR=$($PY scripts/cli_dirs.py configDir 2>/dev/null || echo ".claude")
mkdir -p "$CLI_CONFIG_DIR"

if [ "$GIT_PROVIDER" = "gitlab" ]; then
  cat > "$CLI_CONFIG_DIR/settings.json" << 'EOF'
{"mcpServers":{"git-provider":{"command":"python3","args":["mcp_servers/gitlab_server.py"],"env":{"GITLAB_BASE_URL":"${GITLAB_BASE_URL}","GITLAB_TOKEN":"${GITLAB_TOKEN}"}}}}
EOF
elif [ "$GIT_PROVIDER" = "github" ]; then
  cat > "$CLI_CONFIG_DIR/settings.json" << 'EOF'
{"mcpServers":{"git-provider":{"command":"python3","args":["mcp_servers/github_server.py"],"env":{"GITHUB_TOKEN":"${GITHUB_TOKEN}"}}}}
EOF
fi
ok "MCP config: $GIT_PROVIDER → $CLI_CONFIG_DIR/settings.json"

# ── 8. Start server ──────────────────────────────────

info "Starting webhook server on port $PORT..."
$PY -m uvicorn src.server:app --host 0.0.0.0 --port "$PORT" &
SERVER_PID=$!
sleep 2
kill -0 $SERVER_PID 2>/dev/null || fail "Server failed to start"
ok "Server running (PID: $SERVER_PID)"

# ── Done ──────────────────────────────────────────────

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Auto-Pilot running!${NC}"
echo -e "${GREEN}  $ISSUE_TRACKER + $GIT_PROVIDER + $CLI_ADAPTER${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  Webhook URLs:"
echo -e "    Issue tracker:  ${CYAN}http://<your-host>:${PORT}/webhooks/issue-tracker${NC}"
echo -e "    Git provider:   ${CYAN}http://<your-host>:${PORT}/webhooks/git${NC}"
echo -e "    Manual trigger: ${CYAN}http://<your-host>:${PORT}/api/trigger${NC}"
echo -e "    Status:         ${CYAN}http://<your-host>:${PORT}/api/status${NC}"
echo ""
echo -e "  Health: ${CYAN}curl http://localhost:${PORT}/health${NC}"
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop"
echo ""

cleanup() {
  echo ""
  info "Shutting down..."
  kill $SERVER_PID 2>/dev/null && ok "Server stopped"
  exit 0
}
trap cleanup SIGINT SIGTERM
wait $SERVER_PID
