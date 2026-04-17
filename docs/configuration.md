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
| `type` | string | Yes | `jira` | `jira` or `github-issues` |
| `triggerStatus` | string | No | `Ready for Development` | Status/label that triggers the pipeline |
| `developmentStatus` | string | No | `Development` | Status to transition to after the analysis is posted |
| `doneStatus` | string | No | `Done` | Status to transition to after MR created |
| `blockedStatus` | string | No | `Blocked` | Status to transition to when ticket lacks info |
| `botUsers` | string[] | No | `[]` | Usernames to ignore in webhooks |

#### Type options

| Type | Platform | Integration | Needs in .env |
|------|----------|------------|---------------|
| `jira` | Jira | REST API (server-side) | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` |
| `github-issues` | GitHub Issues | REST API (server-side) | `GITHUB_TOKEN`, `GITHUB_OWNER` |

The Python server handles all issue tracker interactions (reading tickets, posting comments, transitioning status) directly via REST API — agents never call the issue tracker. Credentials are stored in `.env`.

The old values `jira-mcp` / `jira-api` / `github-mcp` / `github-api` are still accepted for backward compatibility; they all resolve to the same REST-API behavior.

```yaml
# Jira
issueTracker:
  type: jira
  triggerStatus: Ready for Development
  developmentStatus: Development
  doneStatus: Code Review
  blockedStatus: Blocked

# GitHub Issues
issueTracker:
  type: github-issues
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
| `allowCliSkills` | boolean | No | `false` | Allow agents to use CLI skills/plugins. When false (default), agents ignore all skills to avoid interference with pipeline execution. |

```yaml
pipeline:
  maxReworkIterations: 3
  agentTimeout: 300000
  port: 3000
  allowCliSkills: false    # set true only if you have pipeline-compatible skills
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
# GitHub Issues (when issueTracker.type = github-issues)
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
GITHUB_OWNER=your-org-or-username
```

REST API credentials are always required. The Python server uses them for ticket reads, status transitions, and posting pipeline comments (analysis summary, plan, MR links).

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
  type: jira
  triggerStatus: Ready for Development
  developmentStatus: Development
  doneStatus: Code Review
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

**Q: I see my config uses `jira-mcp` — do I need to migrate?**
A: No — `jira-mcp`, `jira-api`, `github-mcp`, `github-api` are all accepted as aliases for `jira` / `github-issues` and resolve to the same REST-API behavior. New setups pick the short form. Re-running `./setup.sh` migrates the value automatically.
