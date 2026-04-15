#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Auto-Pilot — One-shot startup script
#
#  Usage:  ./start.sh
#
#  What it does:
#    1. Checks prerequisites (node, claude CLI)
#    2. Installs dependencies (root + GitLab MCP server)
#    3. Creates .env from .env.example if missing
#    4. Validates required config (repos.json, .env tokens)
#    5. Starts the webhook server
#    6. Starts ngrok tunnel (if ngrok is available)
# ─────────────────────────────────────────────────────────

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  AI Dev Pipeline — Auto-Pilot Startup${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo ""

# ── 1. Prerequisites ──────────────────────────────────────

info "Checking prerequisites..."

if ! command -v node &>/dev/null; then
  fail "Node.js is not installed. Install Node >= 18 and retry."
fi

NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
  fail "Node.js version >= 18 required (found v$(node -v))"
fi
ok "Node.js $(node -v)"

if ! command -v claude &>/dev/null; then
  warn "Claude Code CLI not found. Agents will fail to run."
  warn "Install it: https://docs.anthropic.com/en/docs/claude-code"
else
  ok "Claude Code CLI found"
fi

# ── 2. Install dependencies ──────────────────────────────

info "Installing dependencies..."

if [ ! -d "node_modules" ]; then
  npm install --silent 2>&1 | tail -1
  ok "Root dependencies installed"
else
  ok "Root dependencies already installed"
fi

if [ ! -d "mcp-servers/gitlab/node_modules" ]; then
  (cd mcp-servers/gitlab && npm install --silent 2>&1 | tail -1)
  ok "GitLab MCP server dependencies installed"
else
  ok "GitLab MCP server dependencies already installed"
fi

# ── 3. Environment file ──────────────────────────────────

if [ ! -f ".env" ]; then
  cp .env.example .env
  warn ".env created from .env.example — edit it with your real tokens"
  warn "Then re-run this script."
  echo ""
  echo -e "  ${YELLOW}Required values to set:${NC}"
  echo "    GITLAB_BASE_URL     — your GitLab instance URL"
  echo "    GITLAB_TOKEN        — personal access token (api scope)"
  echo "    GITLAB_PROJECT_ID   — numeric project ID"
  echo ""
  exit 0
else
  ok ".env file exists"
fi

# ── 4. Validate config ───────────────────────────────────

info "Validating configuration..."

# Check .env has required values
source .env 2>/dev/null || true

if [ -z "$GITLAB_TOKEN" ] || [ "$GITLAB_TOKEN" = "your-personal-access-token" ]; then
  fail "GITLAB_TOKEN not set in .env — add your GitLab personal access token"
fi

if [ -z "$GITLAB_PROJECT_ID" ] || [ "$GITLAB_PROJECT_ID" = "12345" ]; then
  fail "GITLAB_PROJECT_ID not set in .env — add your GitLab project ID"
fi
ok "GitLab credentials configured"

# Check repos.json
if [ ! -f "repos.json" ]; then
  fail "repos.json not found — create it (see README for format)"
fi

REPO_MODE=$(node -e "console.log(require('./repos.json').mode || 'not set')")
if [ "$REPO_MODE" = "single" ]; then
  REPO_DIR=$(node -e "console.log(require('./repos.json').single?.repoDir || '')")
  if [ -z "$REPO_DIR" ]; then
    fail "repos.json: single.repoDir is not set"
  fi
  if [ ! -d "$REPO_DIR" ]; then
    fail "repos.json: single.repoDir directory does not exist: $REPO_DIR"
  fi
  ok "Repo mode: single — $REPO_DIR"
elif [ "$REPO_MODE" = "multi" ]; then
  PARENT_DIR=$(node -e "console.log(require('./repos.json').multi?.parentDir || '')")
  if [ -z "$PARENT_DIR" ]; then
    fail "repos.json: multi.parentDir is not set"
  fi
  if [ ! -d "$PARENT_DIR" ]; then
    fail "repos.json: multi.parentDir directory does not exist: $PARENT_DIR"
  fi
  REPO_COUNT=$(ls -d "$PARENT_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')
  ok "Repo mode: multi — $PARENT_DIR ($REPO_COUNT repos found)"
else
  fail "repos.json: mode must be 'single' or 'multi' (found: $REPO_MODE)"
fi

# ── 5. Start webhook server ──────────────────────────────

PORT=${PORT:-3000}
info "Starting webhook server on port $PORT..."

node src/webhook/server.js &
SERVER_PID=$!

# Wait for server to be ready
sleep 1
if ! kill -0 $SERVER_PID 2>/dev/null; then
  fail "Webhook server failed to start"
fi
ok "Webhook server running (PID: $SERVER_PID)"

# ── 6. Start ngrok tunnel (optional) ─────────────────────

if command -v ngrok &>/dev/null; then
  info "Starting ngrok tunnel..."
  ngrok http $PORT --log=stdout > /tmp/ngrok-autopilot.log 2>&1 &
  NGROK_PID=$!
  sleep 2

  # Try to get the public URL
  NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | node -e "
    let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>{
      try{console.log(JSON.parse(d).tunnels[0].public_url)}catch(e){console.log('')}
    })
  " 2>/dev/null)

  if [ -n "$NGROK_URL" ]; then
    ok "ngrok tunnel: $NGROK_URL"
    echo ""
    echo -e "  ${CYAN}Configure your webhooks:${NC}"
    echo -e "    Jira:   ${GREEN}${NGROK_URL}/webhooks/jira${NC}"
    echo -e "    GitLab: ${GREEN}${NGROK_URL}/webhooks/gitlab${NC}"
  else
    warn "ngrok started but could not detect URL — check http://localhost:4040"
  fi
else
  warn "ngrok not found — webhook server is local-only on port $PORT"
  warn "Install ngrok or use another tunnel to expose webhooks"
fi

# ── Done ──────────────────────────────────────────────────

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Auto-Pilot is running!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  Health check: ${CYAN}curl http://localhost:${PORT}/health${NC}"
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop"
echo ""

# Trap Ctrl+C to clean up
cleanup() {
  echo ""
  info "Shutting down..."
  kill $SERVER_PID 2>/dev/null && ok "Webhook server stopped"
  [ -n "$NGROK_PID" ] && kill $NGROK_PID 2>/dev/null && ok "ngrok stopped"
  exit 0
}

trap cleanup SIGINT SIGTERM

# Keep script alive
wait $SERVER_PID
