# AI-Powered Development Automation Pipeline

**Jira  ->  Claude Code Agents  ->  GitLab MR  ->  Review Loop**

Automates the full development lifecycle from Jira ticket creation to GitLab merge request. Claude Code agents handle brainstorming, planning, and implementation autonomously — then hand control back to the human reviewer for approval, editing, or feedback.

**Goal:** Zero manual steps between "Ready for Development" and "Awaiting Review". The developer agent does the work; the human owns the decision.

---

## Quick Start

```bash
git clone https://github.com/regojoyson/auto-developer.git
cd auto-developer

# 1. Edit repos.json — point to your project directory:
#    Single repo:  { "mode": "single", "single": { "repoDir": "/path/to/your/project" } }
#    Multi repo:   { "mode": "multi",  "multi":  { "parentDir": "/path/to/parent" } }

# 2. Link agent configs into your repo(s)
./setup.sh

# 3. Start everything
./start.sh
```

On first run `start.sh` creates `.env` and tells you what tokens to fill in. Fill them, re-run `./start.sh`, and you're live.

```bash
./stop.sh      # kills server + ngrok, removes symlinks from your repos
```

Three scripts, that's it:

| Script | What it does |
|--------|-------------|
| `./setup.sh` | Symlinks `.claude/` into your repo(s) — run once |
| `./start.sh` | Installs deps, validates config, starts server + ngrok |
| `./stop.sh` | Kills server + ngrok, removes `.claude/` symlinks (clean shutdown) |

---

## Table of Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Where to Run](#where-to-run)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Configuration](#configuration)
- [Running](#running) (setup.sh / start.sh / stop.sh)
- [Project Structure](#project-structure)
- [Agent Definitions](#agent-definitions)
- [GitLab MCP Server](#gitlab-mcp-server)
- [Pipeline States](#pipeline-states)
- [Review Loop](#review-loop)
- [Troubleshooting](#troubleshooting)
- [Spec Documentation](#spec-documentation)

---

## How It Works

```
Jira Ticket                    GitLab
"Ready for Dev"                  MR
      |                          ^
      v                          |
 [Webhook Receiver]         [Webhook Receiver]
      |                     /    |    \
      v                    v     v     v
 Orchestrator         Approve  Push  Comment
      |                  |      |      |
      v                  v      v      v
  Brainstorm          Merge   Wait  Feedback
   Agent              Jira    for    Parser
      |               Done   human    |
      v                        ok     v
  Developer                        Developer
   Agent                           (Rework)
      |                               |
      v                               v
  Create MR  ----------------------> Update MR
```

1. A Jira ticket transitions to **"Ready for Development"** -> webhook fires
2. **Orchestrator agent** creates a feature branch and writes `TICKET.md`
3. **Brainstorm agent** explores the codebase, produces `PLAN.md` with the implementation approach
4. **Developer agent** implements from the plan, commits code
5. **Orchestrator** creates a GitLab Merge Request with auto-generated description
6. **Reviewer** (human) reads the diff and decides:
   - **Approve** -> Jira transitions to Done, Slack notified
   - **Push edits** -> pipeline waits for re-approval
   - **Comment feedback** -> feedback parser + developer rework cycle

---

## Where to Run

This pipeline must be run **inside the target project's working directory** — the same repo where the developer agent will write code.

The agents use Claude Code CLI, which reads the local filesystem to understand the codebase. They do **not** clone or pull the repo themselves. Instead:

- The **webhook receiver** (`src/webhook/server.js`) runs as a local Node.js server
- The **GitLab MCP server** handles all remote Git operations (creating branches, committing files, creating MRs) via the GitLab REST API
- The **agents** read the local codebase for context (file structure, existing patterns) but commit their changes via the GitLab API — they do not run `git push` directly

**In practice:**

The auto-pilot runs from its own directory. You don't copy files into your project. Instead:

1. Edit `repos.json` to point at your repo(s)
2. Run `./setup.sh` — this symlinks `.claude/` (agent configs) into your target repo(s)
3. Run `./start.sh` — the webhook server and agents run from here

The agents are spawned with `cwd` set to your target repo, so they read that repo's codebase for context. Code changes are committed remotely via the GitLab REST API.

### Multi-Repo vs Single Repo

Configure `repos.json` with one of two modes:

**Single repo (mono-repo)** — one directory, all tickets run here:

```json
{
  "mode": "single",
  "single": { "repoDir": "/projects/my-app" }
}
```

**Multi repo** — a parent directory where every subdirectory is a repo:

```json
{
  "mode": "multi",
  "multi": { "parentDir": "/projects" }
}
```

```
/projects/           <-- parentDir
  ├── frontend-app/
  ├── backend-api/
  └── shared-libs/
```

In multi mode, the pipeline uses the Jira ticket's **component** field to pick the subdirectory. If no component is set, it uses the parent directory itself.

---

## Prerequisites

- **Node.js** >= 18
- **Claude Code CLI** installed and authenticated (`claude` command available)
- **GitLab** personal access token with `api` scope
- **Jira** project with a "Ready for Development" status
- **ngrok** (or similar) for exposing local webhooks during development

---

## Setup

### 1. Clone

```bash
git clone https://github.com/regojoyson/auto-developer.git
cd auto-developer
```

### 2. Point at your repo(s)

Edit `repos.json`:

```json
{ "mode": "single", "single": { "repoDir": "/path/to/your/project" } }
```

Or for multiple repos in a parent directory:

```json
{ "mode": "multi", "multi": { "parentDir": "/path/to/parent" } }
```

### 3. Run setup + start

```bash
./setup.sh     # symlinks .claude/ into your repo(s) — run once
./start.sh     # installs deps, creates .env, validates, starts server + ngrok
```

On first run, `start.sh` creates `.env` and tells you exactly which values to fill in:

| Variable | Description |
|----------|-------------|
| `GITLAB_BASE_URL` | GitLab instance URL (e.g. `https://gitlab.com`) |
| `GITLAB_TOKEN` | Personal access token with `api` scope |
| `GITLAB_PROJECT_ID` | Numeric project ID from GitLab |
| `SLACK_CHANNEL` | Slack channel name for notifications |
| `PORT` | Webhook server port (default: `3000`) |
| `MAX_REWORK_ITERATIONS` | Rework cap before escalation (default: `3`) |
| `AGENT_TIMEOUT_MS` | Agent process timeout in ms (default: `300000` / 5 min) |
| `TARGET_BRANCH` | MR target branch (default: `main`) |

Fill in the tokens, re-run `./start.sh`, and it prints the webhook URLs.

### 4. Configure webhooks

Use the URLs printed by `start.sh`:

**Jira:**
- Settings > System > Webhooks
- URL: `https://<ngrok-url>/webhooks/jira`
- Events: `issue_updated`

**GitLab:**
- Project > Settings > Webhooks
- URL: `https://<ngrok-url>/webhooks/gitlab`
- Triggers: Merge request events, Push events, Comments

---

## Configuration

### CLAUDE.md (Global Agent Rules)

The file `.claude/CLAUDE.md` is loaded by every agent as shared context. It contains:

- Commit message format (`feat(PROJ-123): ...`)
- Branch naming conventions (`feature/PROJ-123-kebab-slug`)
- Agent behavior constraints (scope limits, push restrictions)
- Code standards for your project

Edit this file to match your team's conventions before running.

### Agent Prompts

Each agent's behavior is defined in `.claude/agents/<name>.md`. You can customize these to adjust how agents reason, what tools they use, and what output format they produce.

---

## Running

### One-shot startup (recommended)

```bash
./start.sh        # or: npm run go
```

This single command will:
1. Check prerequisites (Node.js, Claude CLI)
2. Install all dependencies (root + GitLab MCP server)
3. Create `.env` from template if missing (and tell you what to fill in)
4. Validate config (GitLab tokens, repos.json directory paths)
5. Start the webhook server
6. Start ngrok tunnel (if ngrok is installed)
7. Print the webhook URLs to configure in Jira and GitLab

### Stop everything

```bash
./stop.sh         # or: npm run stop
```

Kills the webhook server and ngrok tunnel, then removes the `.claude/` symlinks from your target repos. Only removes symlinks that point back to this auto-pilot project — it won't touch existing `.claude/` directories that were already there.

### Manual startup

```bash
# Just the webhook server
npm start

# Development mode (auto-restart on file changes)
npm run dev
```

Verify the server is running:
```bash
curl http://localhost:3000/health
# => {"status":"ok","timestamp":"..."}
```

---

## Project Structure

```
auto-pilot/
├── .claude/
│   ├── agents/
│   │   ├── orchestrator.md      # Coordinates full ticket lifecycle
│   │   ├── brainstorm.md        # Produces PLAN.md from ticket context
│   │   ├── developer.md         # Implements code (first pass + rework)
│   │   └── feedback-parser.md   # Structures MR review comments
│   ├── CLAUDE.md                # Global rules for all agents
│   └── settings.json            # MCP server configuration
├── src/
│   ├── webhook/
│   │   ├── server.js            # Express HTTP server (entry point)
│   │   └── routes/
│   │       ├── jira.js          # Jira webhook handler
│   │       └── gitlab.js        # GitLab webhook handler
│   ├── state/
│   │   └── manager.js           # Pipeline state machine (JSON per branch)
│   ├── repos/
│   │   └── resolver.js          # Multi-repo resolver (reads repos.json)
│   ├── agents/
│   │   └── runner.js            # Spawns Claude Code CLI agent processes
│   └── utils/
│       ├── gitlab-api.js        # GitLab REST API wrapper class
│       └── logger.js            # Structured logging utility
├── mcp-servers/
│   └── gitlab/
│       ├── index.js             # GitLab MCP server (8 tools)
│       └── package.json
├── .pipeline-state/             # Per-branch JSON state files (gitignored)
├── docs/
│   └── spec.md                  # Full specification document
├── repos.json                   # Repo config (single dir or parent dir)
├── setup.sh                     # Symlinks .claude/ into target repos (run once)
├── start.sh                     # Install, validate, start server + ngrok
├── stop.sh                      # Kill server + ngrok
├── .env.example                 # Environment variable template
├── .gitignore
├── package.json
└── README.md
```

---

## Agent Definitions

| Agent | File | Trigger | Produces |
|-------|------|---------|----------|
| Orchestrator | `.claude/agents/orchestrator.md` | Jira webhook / GitLab events | Branch, TICKET.md, MR, notifications |
| Brainstorm | `.claude/agents/brainstorm.md` | Invoked by orchestrator | PLAN.md |
| Developer | `.claude/agents/developer.md` | Invoked by orchestrator | Code commits |
| Feedback Parser | `.claude/agents/feedback-parser.md` | GitLab note webhook | FEEDBACK.md |

Each agent runs as a Claude Code CLI process:
```
claude --agent <name> --print --input '<json>'
```

---

## GitLab MCP Server

A custom MCP server (`mcp-servers/gitlab/`) wraps the GitLab REST API v4. It provides 8 tools:

| Tool | Operation |
|------|-----------|
| `create_branch` | Create a new branch from a ref |
| `commit_files` | Commit file create/update/delete actions |
| `create_merge_request` | Open a new MR |
| `get_merge_request` | Read MR details |
| `update_merge_request` | Update MR title/description |
| `list_mr_comments` | List all notes on an MR |
| `post_mr_comment` | Post a comment on an MR |
| `get_file` | Read a file at a specific branch/ref |

Configured in `.claude/settings.json` and loaded automatically by Claude Code.

---

## Pipeline States

Each active ticket has a JSON state file in `.pipeline-state/`:

```
(new) --> brainstorming --> developing --> awaiting-review --> merged
                                               |       ^
                                            reworking --+
```

| State | Meaning |
|-------|---------|
| `brainstorming` | Brainstorm agent is generating PLAN.md |
| `developing` | Developer agent is implementing code |
| `awaiting-review` | MR is open, waiting for human reviewer |
| `reworking` | Developer agent is applying review feedback |
| `merged` | MR approved and merged, ticket closed |

State is checked before every agent invocation to prevent duplicates.

---

## Review Loop

After the MR is created, three outcomes are handled:

### Branch A — Approve
- Reviewer approves the MR in GitLab
- Pipeline transitions Jira to "Done"
- Slack notification sent

### Branch B — Manual Edit
- Reviewer pushes commits directly to the feature branch
- Pipeline detects the human push and waits (no agent action)
- Reviewer can then approve normally

### Branch C — Feedback / Rework
- Reviewer posts a comment on the MR
- Feedback parser agent produces `FEEDBACK.md`
- Developer agent reworks code based on feedback
- MR updated, reviewer re-notified
- Capped at 3 rework iterations (configurable) — escalation to Slack if exceeded

---

## Troubleshooting

**Webhook not received:**
- Check ngrok is running and URL matches Jira/GitLab config
- Verify with `curl -X POST http://localhost:3000/webhooks/jira -H 'Content-Type: application/json' -d '{}'`

**Agent timeout:**
- Increase `AGENT_TIMEOUT_MS` in `.env` (default 5 min)
- Check Claude Code CLI is authenticated: `claude --version`

**Duplicate agent invocations:**
- Check `.pipeline-state/` for the branch's JSON file
- Verify state is correct for the expected transition

**GitLab MCP errors:**
- Verify `GITLAB_TOKEN` has `api` scope
- Verify `GITLAB_PROJECT_ID` is correct (numeric ID, not path)
- Test: `curl -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$GITLAB_BASE_URL/api/v4/projects/$GITLAB_PROJECT_ID"`

---

## Spec Documentation

The full specification document is available at [docs/spec.md](docs/spec.md). It covers:

- Detailed objective and scope
- Pipeline phase-by-phase walkthrough
- Agent input/output contracts
- Review loop decision branches
- Webhook receiver service design
- MCP server requirements
- CLAUDE.md rule definitions
- Recommended build order
- Risk mitigations
