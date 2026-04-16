#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — One-shot startup script
#
#  Reads config.yaml + .env, validates, starts server + ngrok.
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

# Helper to read config.yaml fields via node
cfg() { node -e "const y=require('js-yaml'),f=require('fs');const c=y.load(f.readFileSync('config.yaml','utf-8'));console.log($1)"; }

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  AI Dev Pipeline — Auto-Pilot Startup${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo ""

# ── 1. Prerequisites ──────────────────────────────────

info "Checking prerequisites..."

if ! command -v node &>/dev/null; then
  fail "Node.js is not installed. Install Node >= 18."
fi
NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
[ "$NODE_VERSION" -lt 18 ] && fail "Node.js >= 18 required (found $(node -v))"
ok "Node.js $(node -v)"

command -v claude &>/dev/null && ok "Claude Code CLI found" || warn "Claude Code CLI not found"

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

GIT_PROVIDER=$(cfg "c.gitProvider?.type||''")
ISSUE_TRACKER=$(cfg "c.issueTracker?.type||''")
CLI_ADAPTER=$(cfg "c.cliAdapter?.type||'claude-code'")
REPO_MODE=$(cfg "c.repo?.mode||''")
PORT=$(cfg "c.pipeline?.port||3000")

[ -z "$GIT_PROVIDER" ] && fail "config.yaml: gitProvider.type not set"
[ -z "$ISSUE_TRACKER" ] && fail "config.yaml: issueTracker.type not set"
[ -z "$REPO_MODE" ] && fail "config.yaml: repo.mode not set"

ok "Providers: $ISSUE_TRACKER + $GIT_PROVIDER + $CLI_ADAPTER"
ok "Repo mode: $REPO_MODE"

# ── 4. Install dependencies ──────────────────────────

info "Installing dependencies..."

[ ! -d "node_modules" ] && npm install --silent 2>&1 | tail -1 && ok "Root deps installed" || ok "Root deps OK"

if [ -d "mcp-servers/$GIT_PROVIDER" ] && [ ! -d "mcp-servers/$GIT_PROVIDER/node_modules" ]; then
  (cd "mcp-servers/$GIT_PROVIDER" && npm install --silent 2>&1 | tail -1)
  ok "$GIT_PROVIDER MCP deps installed"
else
  ok "$GIT_PROVIDER MCP deps OK"
fi

# ── 5. Validate secrets ──────────────────────────────

info "Validating secrets..."
source .env 2>/dev/null || true

if [ "$GIT_PROVIDER" = "gitlab" ]; then
  [ -z "$GITLAB_TOKEN" ] && fail "GITLAB_TOKEN not set in .env"
  [ -z "$GITLAB_PROJECT_ID" ] && fail "GITLAB_PROJECT_ID not set in .env"
  ok "GitLab tokens OK"
elif [ "$GIT_PROVIDER" = "github" ]; then
  [ -z "$GITHUB_TOKEN" ] && fail "GITHUB_TOKEN not set in .env"
  [ -z "$GITHUB_OWNER" ] && fail "GITHUB_OWNER not set in .env"
  [ -z "$GITHUB_REPO" ] && fail "GITHUB_REPO not set in .env"
  ok "GitHub tokens OK"
fi

# ── 6. Validate repo ─────────────────────────────────

if [ "$REPO_MODE" = "dir" ]; then
  REPO_PATH=$(cfg "c.repo?.path||''")
  [ ! -d "$REPO_PATH" ] && fail "Repo dir does not exist: $REPO_PATH"
  ok "Repo: $REPO_PATH"
elif [ "$REPO_MODE" = "parentDir" ]; then
  REPO_PATH=$(cfg "c.repo?.path||''")
  [ ! -d "$REPO_PATH" ] && fail "Parent dir does not exist: $REPO_PATH"
  REPO_COUNT=$(ls -d "$REPO_PATH"/*/ 2>/dev/null | wc -l | tr -d ' ')
  ok "Repos: $REPO_PATH ($REPO_COUNT found)"
elif [ "$REPO_MODE" = "clone" ]; then
  URL_COUNT=$(cfg "(c.repo?.urls||[]).length")
  ok "Clone mode: $URL_COUNT URL(s) (will clone on first ticket)"
fi

# ── 7. Generate CLI settings ──────────────────────────

info "Generating MCP config for $CLI_ADAPTER..."

CLI_CONFIG_DIR=$(node src/providers/cli-dirs.js configDir 2>/dev/null || echo ".claude")
mkdir -p "$CLI_CONFIG_DIR"

if [ "$GIT_PROVIDER" = "gitlab" ]; then
  cat > "$CLI_CONFIG_DIR/settings.json" << 'EOF'
{"mcpServers":{"git-provider":{"command":"node","args":["mcp-servers/gitlab/index.js"],"env":{"GITLAB_BASE_URL":"${GITLAB_BASE_URL}","GITLAB_TOKEN":"${GITLAB_TOKEN}","GITLAB_PROJECT_ID":"${GITLAB_PROJECT_ID}"}}}}
EOF
elif [ "$GIT_PROVIDER" = "github" ]; then
  cat > "$CLI_CONFIG_DIR/settings.json" << 'EOF'
{"mcpServers":{"git-provider":{"command":"node","args":["mcp-servers/github/index.js"],"env":{"GITHUB_TOKEN":"${GITHUB_TOKEN}","GITHUB_OWNER":"${GITHUB_OWNER}","GITHUB_REPO":"${GITHUB_REPO}"}}}}
EOF
fi
ok "MCP config: $GIT_PROVIDER → $CLI_CONFIG_DIR/settings.json"

# ── 8. Start server ──────────────────────────────────

info "Starting webhook server on port $PORT..."
node src/webhook/server.js &
SERVER_PID=$!
sleep 1
kill -0 $SERVER_PID 2>/dev/null || fail "Server failed to start"
ok "Server running (PID: $SERVER_PID)"

# ── 9. ngrok ──────────────────────────────────────────

if command -v ngrok &>/dev/null; then
  info "Starting ngrok..."
  ngrok http $PORT --log=stdout > /tmp/ngrok-autopilot.log 2>&1 &
  NGROK_PID=$!
  sleep 2
  NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | node -e "let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>{try{console.log(JSON.parse(d).tunnels[0].public_url)}catch(e){console.log('')}})" 2>/dev/null)
  if [ -n "$NGROK_URL" ]; then
    ok "ngrok: $NGROK_URL"
    echo ""
    echo -e "  ${CYAN}Webhook URLs:${NC}"
    echo -e "    Issue tracker: ${GREEN}${NGROK_URL}/webhooks/issue-tracker${NC}"
    echo -e "    Git provider:  ${GREEN}${NGROK_URL}/webhooks/git${NC}"
  fi
else
  warn "ngrok not found — server is local-only on port $PORT"
fi

# ── Done ──────────────────────────────────────────────

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Auto-Pilot running!${NC}"
echo -e "${GREEN}  $ISSUE_TRACKER + $GIT_PROVIDER + $CLI_ADAPTER${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  Health: ${CYAN}curl http://localhost:${PORT}/health${NC}"
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop"
echo ""

cleanup() {
  echo ""
  info "Shutting down..."
  kill $SERVER_PID 2>/dev/null && ok "Server stopped"
  [ -n "$NGROK_PID" ] && kill $NGROK_PID 2>/dev/null && ok "ngrok stopped"
  exit 0
}
trap cleanup SIGINT SIGTERM
wait $SERVER_PID
