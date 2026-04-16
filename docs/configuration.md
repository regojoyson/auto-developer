[< Back to README](../README.md) | [Prerequisites](prerequisites.md) | [Setup](setup.md) | [How It Works](how-it-works.md) | [API Spec](api-spec.md) | [Custom Providers](custom-providers.md)

---

# Configuration Reference

All configuration lives in **one file**: `config.yaml`.
Secrets (tokens, keys) go in `.env`.

Run `./setup.sh` to generate `config.yaml` interactively, or create it manually.

---

## config.yaml — Full Reference

### repo

Controls where your code lives.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mode` | string | Yes | — | `dir`, `parentDir`, or `clone` |
| `path` | string | For dir/parentDir | — | Absolute path to repo or parent directory |
| `urls` | string[] | For clone | — | Git URLs to clone |
| `cloneDir` | string | For clone | `/tmp/auto-pilot-repos` | Where to clone repos |
| `baseBranch` | string | No | `main` | Branch to checkout and branch from for each new ticket |

#### Mode: `dir` — Single repo

```yaml
repo:
  mode: dir
  path: /projects/my-app
  baseBranch: main
```

All tickets use this one directory. On each new ticket, the pipeline runs `git checkout main && git pull` before creating a feature branch.

#### Mode: `parentDir` — Multiple repos

```yaml
repo:
  mode: parentDir
  path: /projects
  baseBranch: main
```

Every subdirectory under `/projects/` is a repo. The Jira ticket's component field selects which subdirectory to use.

```
/projects/
  ├── frontend-app/
  ├── backend-api/
  └── shared-libs/
```

#### Mode: `clone` — Clone from URL(s)

Single repo:
```yaml
repo:
  mode: clone
  urls:
    - https://github.com/org/repo.git
  cloneDir: /tmp/auto-pilot-repos
  baseBranch: main
```

Multiple repos:
```yaml
repo:
  mode: clone
  urls:
    - https://github.com/org/frontend.git
    - https://github.com/org/backend.git
    - https://github.com/org/shared.git
  cloneDir: /tmp/auto-pilot-repos
  baseBranch: develop
```

Repos are cloned on first use and reused after. The pipeline pulls latest before each ticket.

---

### issueTracker

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | Yes | `jira-mcp` | See 4 options below |
| `triggerStatus` | string | No | `Ready for Development` | Status/label that triggers the pipeline |
| `developmentStatus` | string | No | `Development` | Status to transition to when pipeline picks up a ticket |
| `doneStatus` | string | No | `Done` | Status to transition to after MR created |
| `blockedStatus` | string | No | `Blocked` | Status to transition to when ticket lacks info |
| `botUsers` | string[] | No | `[]` | Usernames to ignore in webhooks |

#### Type options

| Type | Platform | Integration | Who calls API | Needs in .env |
|------|----------|------------|--------------|---------------|
| `jira-mcp` | Jira | Agent via CLI MCP | Agent | Nothing (MCP has its own auth) |
| `jira-api` | Jira | Python server REST API | Server | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` |
| `github-mcp` | GitHub Issues | Agent via CLI MCP | Agent | Nothing (MCP has its own auth) |
| `github-api` | GitHub Issues | Python server REST API | Server | `GITHUB_TOKEN`, `GITHUB_OWNER` |

**MCP mode (`*-mcp`):** The AI agent handles all issue tracker interactions (reading tickets, posting comments, transitioning status) through MCP tools configured in your CLI. No REST API credentials needed in `.env`. You must configure the MCP server in your CLI tool (see [Prerequisites](prerequisites.md)).

**API mode (`*-api`):** The Python server handles all issue tracker interactions directly via REST API. No MCP configuration needed for the issue tracker. Credentials are stored in `.env`.

```yaml
# Jira via MCP (agent handles via CLI MCP tools)
issueTracker:
  type: jira-mcp
  triggerStatus: Ready for Development
  developmentStatus: Development
  doneStatus: Done
  blockedStatus: Blocked

# Jira via built-in REST API (server calls Jira directly)
issueTracker:
  type: jira-api
  triggerStatus: Ready for Development
  developmentStatus: Development
  doneStatus: Done
  blockedStatus: Blocked

# GitHub Issues via MCP
issueTracker:
  type: github-mcp
  triggerStatus: ready-for-dev
  developmentStatus: in-progress
  doneStatus: done
  blockedStatus: blocked

# GitHub Issues via built-in REST API
issueTracker:
  type: github-api
  triggerStatus: ready-for-dev
  developmentStatus: in-progress
  doneStatus: done
  blockedStatus: blocked
```

---

### gitProvider

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | Yes | `gitlab` | `gitlab` or `github` |
| `botUsers` | string[] | No | `[]` | Bot usernames to ignore in MR/PR comments |

```yaml
# GitLab
gitProvider:
  type: gitlab
  botUsers:
    - project_bot
    - ghost

# GitHub
gitProvider:
  type: github
  botUsers:
    - dependabot[bot]
    - github-actions[bot]
```

---

### cliAdapter

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | Yes | `claude-code` | `claude-code`, `codex`, or `gemini` |
| `model` | string | No | `null` | Model override (e.g. `claude-sonnet-4-6`) |
| `maxTurnsPerRun` | number | No | `null` | Max agent turns per invocation |
| `timeout` | number | No | `300000` | Agent process timeout in ms |
| `command` | string | No | `null` | Override the CLI command (e.g. custom path) |
| `extraArgs` | string[] | No | `[]` | Additional CLI arguments |

```yaml
# Claude Code (default)
cliAdapter:
  type: claude-code

# Claude Code with model override
cliAdapter:
  type: claude-code
  model: claude-sonnet-4-6
  maxTurnsPerRun: 50

# Codex
cliAdapter:
  type: codex
  model: codex-mini

# Gemini
cliAdapter:
  type: gemini
```

---

### notification (optional)

Omit this section entirely to disable notifications.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | Yes | — | `slack` (more coming) |
| `channel` | string | No | `general` | Channel name to post to |

```yaml
# Slack notifications
notification:
  type: slack
  channel: dev-team

# No notifications — just don't include this section
```

---

### pipeline

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `maxReworkIterations` | number | No | `3` | Max feedback/rework cycles before escalation |
| `agentTimeout` | number | No | `300000` | Default agent process timeout in ms (5 min) |
| `port` | number | No | `3000` | Webhook server port |
| `outputHandlers` | string[] | No | `[file, memory]` | Where to stream agent output |

```yaml
pipeline:
  maxReworkIterations: 3
  agentTimeout: 300000
  port: 3000
  outputHandlers:
    - file      # writes to logs/agents/{issueKey}-{agent}.log (tail -f)
    - memory    # serves via GET /api/status/{issueKey}/logs
```

Output handlers control where you can see real-time agent output:
- **file** — each agent writes to a separate log file, watchable with `tail -f`
- **memory** — keeps output in memory, queryable via the API
- Both are enabled by default. Disable one by removing it from the list.

---

## .env — Secrets Only

Only API tokens go here. Everything else is in `config.yaml`.
Which variables you need depends on your `config.yaml` choices.

```bash
# Git provider (always needed)
# GitLab (when gitProvider.type = gitlab)
GITLAB_BASE_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
# GitHub (when gitProvider.type = github)
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# Issue tracker — only needed for *-api modes
# Jira (when issueTracker.type = jira-api)
JIRA_BASE_URL=https://your-org.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_TOKEN=your-jira-api-token
# GitHub Issues (when issueTracker.type = github-api)
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
GITHUB_OWNER=your-org-or-username
```

**Note:** If using `*-mcp` mode for the issue tracker, no issue tracker credentials are needed in `.env` — the MCP server configured in your CLI handles authentication.

---

## Complete Example

```yaml
repo:
  mode: clone
  urls:
    - https://github.com/acme/backend.git
    - https://github.com/acme/frontend.git
  cloneDir: /tmp/acme-repos
  baseBranch: develop

issueTracker:
  type: jira-api
  triggerStatus: Ready for Development
  developmentStatus: Development
  doneStatus: Done
  blockedStatus: Blocked

gitProvider:
  type: github
  botUsers:
    - dependabot[bot]

cliAdapter:
  type: claude-code
  model: claude-sonnet-4-6

notification:
  type: slack
  channel: acme-engineering

pipeline:
  maxReworkIterations: 5
  agentTimeout: 600000
  port: 8080
```

```bash
# .env
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
JIRA_BASE_URL=https://acme.atlassian.net
JIRA_EMAIL=dev@acme.com
JIRA_TOKEN=ATATT3xxxxxxxxxxx
```

---

## FAQ

**Q: Can I use different baseBranches per repo?**
A: Not yet — baseBranch is global. Use separate auto-pilot instances for repos with different base branches.

**Q: What happens in clone mode if the URL is private?**
A: The `git clone` uses your system's git credentials. Make sure SSH keys or credential helpers are configured.

**Q: Can I use both GitLab and GitHub at the same time?**
A: One git provider per config. For mixed setups, run separate auto-pilot instances.

**Q: How do I add a new provider?**
A: See the [Custom Providers Guide](custom-providers.md).

**Q: Should I use MCP mode or API mode for my issue tracker?**
A: **MCP mode** if you already have the MCP server configured in your CLI and want the agent to handle everything. **API mode** if you don't want to configure MCP for the issue tracker — the Python server handles it directly via REST API. API mode is simpler to set up (just add credentials to `.env`).

**Q: Can I switch between MCP and API mode later?**
A: Yes — just change the `type` field in `config.yaml` and restart. If switching to `*-api`, add the REST API credentials to `.env`. If switching to `*-mcp`, configure the MCP server in your CLI.
