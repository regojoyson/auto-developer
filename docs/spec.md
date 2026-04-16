[< Back to README](../README.md) | [Prerequisites](prerequisites.md) | [Setup](setup.md) | [How It Works](how-it-works.md) | [Configuration](configuration.md) | [API Spec](api-spec.md) | [Custom Providers](custom-providers.md)

---

# AI-Powered Development Automation — Specification

**Team:** Sentinels — Cadmium Engineering
**Status:** Draft — For Implementation
**Tool:** Claude Code (multi-agent)
**Integrations:** Jira MCP, GitLab API, Slack MCP

---

## 1. Objective

Automate the full development lifecycle from Jira ticket creation to GitLab merge request, removing manual handoffs between PO, developer, and reviewer. The system uses Claude Code agents to perform brainstorming, planning, and implementation autonomously — then hands control back to the human reviewer for approval, manual editing, or feedback.

**Goal:** Zero manual steps between "Ready for Development" and "Awaiting Review". The developer agent does the work; the human owns the decision.

---

## 2. Scope

### In Scope

- Jira ticket detection on status transition to "Ready for Development"
- Automated brainstorm and PLAN.md generation per ticket
- Code implementation by a developer agent on an isolated git branch
- GitLab MR creation with auto-generated description and plan summary
- Review loop: approve, manual edit, or feedback-driven rework
- Rework cycle: agent re-applies changes from MR comments, updates MR, notifies reviewer

### Out of Scope (Phase 1)

- Automated test execution or QA agent
- Automated code review agent
- Deployment or CI/CD trigger post-merge
- Multi-repo or monorepo cross-cutting changes

---

## 3. Pipeline Overview

The pipeline runs in four phases:

| Phase | Name | What Happens | Output |
|-------|------|-------------|--------|
| 1 | Trigger | Jira webhook fires on status -> Ready for Dev. Orchestrator fetches ticket context. | Branch created, ticket context loaded |
| 2 | Agents | Brainstorm agent explores approaches and writes PLAN.md. Developer agent implements from the plan. | Committed code on feature branch |
| 3 | Review | MR created on GitLab. Reviewer is notified. Human reads diff and decides. | Approve / Manual edit / Feedback |
| 4 | Rework | Feedback parser reads MR comments, builds task list. Developer agent applies changes, pushes commit, updates MR. | Updated MR, reviewer re-notified |

---

## 4. Agent Definitions

All agents live in `.claude/agents/` as Markdown files. Each file contains a system prompt, tool list, and input/output contract.

### 4.1 Orchestrator Agent

| Field | Value |
|-------|-------|
| **Trigger** | Jira webhook POST — status transitions to "Ready for Development" |
| **Inputs** | Jira issue key, webhook payload |
| **Outputs** | Feature branch created (`feature/PROJ-123-slug`), TICKET.md written, brainstorm agent invoked |
| **Tools** | Jira MCP (read ticket + AC), GitLab MCP (create branch, commit), Slack MCP |

**Behavior:**
- Reads full Jira description, acceptance criteria, linked tickets, and any attached designs before invoking brainstorm
- Sets pipeline state to `brainstorming`
- Also handles post-merge actions (Jira transition, Slack notification) and rework-limit escalation

### 4.2 Brainstorm Agent

| Field | Value |
|-------|-------|
| **Trigger** | Invoked by orchestrator after branch and TICKET.md are ready |
| **Inputs** | TICKET.md, codebase context (relevant files auto-loaded by Claude Code) |
| **Outputs** | PLAN.md committed to branch |
| **Tools** | Filesystem (read codebase, write PLAN.md), GitLab MCP (commit) |

**Behavior:**
- Generates 2-3 candidate approaches, evaluates trade-offs, selects one
- Writes a structured plan with file change list, implementation notes, and AC mapping
- Does NOT write any implementation code

### 4.3 Developer Agent

| Field | Value |
|-------|-------|
| **Trigger** | Invoked by orchestrator after PLAN.md is committed. Also re-invoked during rework. |
| **Inputs** | First pass: PLAN.md + codebase. Rework pass: PLAN.md + codebase + FEEDBACK.md |
| **Outputs** | Code changes committed to feature branch |
| **Tools** | Filesystem (read/write code), GitLab MCP (commit), shell (run test scripts) |

**Behavior:**
- Follows PLAN.md strictly on first pass
- On rework, reads FEEDBACK.md and applies only the changes requested
- Does not re-plan unless PLAN.md is modified
- Commit messages reference Jira key

### 4.4 Feedback Parser Agent

| Field | Value |
|-------|-------|
| **Trigger** | GitLab webhook fires on new MR comment (`note:created` event, human author only) |
| **Inputs** | MR comment thread (all comments since last rework commit) |
| **Outputs** | FEEDBACK.md committed to branch |
| **Tools** | GitLab MCP (read MR comments), filesystem (write FEEDBACK.md) |

**Behavior:**
- Filters out bot comments and automated pipeline comments
- Groups related feedback
- Flags ambiguous comments for the developer agent to use best judgment

---

## 5. Review Loop — Decision Branches

After the MR is created, the pipeline pauses and waits for a GitLab event. Three outcomes are handled:

### Branch A — Approve

- **Trigger:** `merge_request:approved` event from GitLab webhook
- Pipeline state -> `merged`
- Orchestrator transitions Jira ticket to Done
- Branch is deleted post-merge by GitLab (standard)
- Slack notification sent to team channel

### Branch B — Manual Edit

- **Trigger:** `push` event on the MR branch from a non-bot author
- Pipeline detects a human commit on the feature branch
- No agent action — pipeline waits for the reviewer to approve
- MR description updated with a note: "Human edits applied — awaiting re-approval"
- If reviewer then approves, follow Branch A

### Branch C — Feedback / Rework

- **Trigger:** `note:created` event on the MR from a human reviewer
- Feedback parser agent reads full comment thread
- Produces FEEDBACK.md and commits it to the branch
- Developer agent re-invoked with FEEDBACK.md as additional context
- New commit pushed to branch, MR description updated with changelog
- Reviewer notified via Slack or GitLab @mention
- Pipeline state reset to `awaiting-review` — loop repeats

---

## 6. Folder Structure

| Path | Purpose |
|------|---------|
| `.claude/agents/orchestrator.md` | Orchestrator system prompt + tool config |
| `.claude/agents/brainstorm.md` | Brainstorm agent prompt |
| `.claude/agents/developer.md` | Developer agent prompt (first pass + rework) |
| `.claude/agents/feedback-parser.md` | Feedback parser agent prompt |
| `.claude/CLAUDE.md` | Global rules: code style, commit format, branch naming |
| `src/webhook/server.js` | Express webhook receiver (entry point) |
| `src/webhook/routes/jira.js` | Jira webhook handler |
| `src/webhook/routes/gitlab.js` | GitLab webhook handler (3 event types) |
| `src/state/manager.js` | Pipeline state machine (JSON per branch) |
| `src/agents/runner.js` | Claude Code CLI agent spawner |
| `src/utils/gitlab-api.js` | GitLab REST API wrapper class |
| `src/utils/logger.js` | Structured logging utility |
| `mcp-servers/gitlab/index.js` | Custom GitLab MCP server (8 tools) |
| `TICKET.md` (per branch) | Jira ticket context written by orchestrator |
| `PLAN.md` (per branch) | Implementation plan written by brainstorm agent |
| `FEEDBACK.md` (per branch) | Parsed review feedback written by feedback parser |

---

## 7. Webhook Receiver Service

A Node.js Express service handles incoming webhooks from both Jira and GitLab.

### Jira Webhook

| Field | Value |
|-------|-------|
| Event | `issue_updated` |
| Filter | `status.name == 'Ready for Development'` |
| Action | Invoke orchestrator agent with issue key |

### GitLab Webhook

| Event | Filter | Action |
|-------|--------|--------|
| `merge_request` | `action == "approved"` | Branch A: merge flow |
| `push` | MR branch, non-bot author | Branch B: human edit |
| `note` | MR notes, human author | Branch C: rework flow |

### Pipeline State

Track pipeline state (`brainstorming` / `developing` / `awaiting-review` / `reworking` / `merged`) as a JSON file per branch in `.pipeline-state/`. This prevents duplicate agent invocations when multiple events arrive.

---

## 8. MCP Servers Required

| MCP Server | Used By | Operations |
|------------|---------|-----------|
| Atlassian (Jira) | Orchestrator | `getJiraIssue`, `searchJiraIssuesUsingJql`, `addCommentToJiraIssue`, `transitionJiraIssue` |
| GitLab (custom) | All agents | Create branch, commit files, create MR, read MR comments, post MR comment |
| Slack | Orchestrator | `slack_send_message` to team channel on key events |
| Filesystem | Brainstorm, Developer, Feedback Parser | Read codebase, write PLAN.md / FEEDBACK.md, run shell commands |

### GitLab MCP Tools

| Tool | GitLab API Endpoint | Used By |
|------|-------------------|---------|
| `create_branch` | `POST /projects/:id/repository/branches` | Orchestrator |
| `commit_files` | `POST /projects/:id/repository/commits` | All agents |
| `create_merge_request` | `POST /projects/:id/merge_requests` | Orchestrator |
| `get_merge_request` | `GET /projects/:id/merge_requests/:iid` | Orchestrator |
| `update_merge_request` | `PUT /projects/:id/merge_requests/:iid` | Developer, Orchestrator |
| `list_mr_comments` | `GET /projects/:id/merge_requests/:iid/notes` | Feedback Parser |
| `post_mr_comment` | `POST /projects/:id/merge_requests/:iid/notes` | Orchestrator |
| `get_file` | `GET /projects/:id/repository/files/:path` | All agents |

---

## 9. CLAUDE.md — Global Rules

The `.claude/CLAUDE.md` file is loaded by every agent. It contains:

- **Commit message format:** `feat(PROJ-123): <desc>` for features, `fix(PROJ-123): <desc>` for bugs
- **Branch naming:** `feature/PROJ-123-kebab-slug` (slug from Jira summary, max 40 chars)
- **Agent behavior rules:**
  - Never modify files outside the ticket scope
  - Never push directly to main or develop
  - Never modify TICKET.md after it is written by the orchestrator
  - On rework: only change what FEEDBACK.md requests — no speculative refactors
- **Code standards:** Language-specific rules for the target codebase

---

## 10. Recommended Build Order

Build incrementally — validate each layer before adding the next.

| Step | What to Build | Done When |
|------|--------------|-----------|
| 0 | Environment setup, project scaffold, CLAUDE.md | Folder structure exists, dependencies installed |
| 1 | GitLab MCP server | Can create branches and commit files from Claude Code |
| 2 | Jira webhook receiver | Receives a status transition and logs the issue key |
| 3 | Orchestrator agent | Creates a branch and writes TICKET.md from a real Jira ticket |
| 4 | Brainstorm agent | Produces a coherent PLAN.md for a simple feature ticket |
| 5 | Developer agent (first pass) | Commits working code that matches the plan |
| 6 | MR creation | MR appears in GitLab with correct description and branch |
| 7 | GitLab webhook receiver | Detects approve / push / note events and routes correctly |
| 8 | Feedback parser agent | Produces a clean FEEDBACK.md from a real MR comment thread |
| 9 | Developer agent (rework pass) | Applies feedback correctly without touching unrelated code |
| 10 | Pipeline state machine + Slack | No duplicate agent invocations across a full ticket lifecycle |

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Agent commits to wrong branch | High | CLAUDE.md rule + orchestrator validates branch name before any commit |
| Infinite rework loop | Medium | Cap rework at 3 iterations; escalate to Slack if exceeded |
| Ambiguous Jira ticket | Medium | Brainstorm agent posts a clarifying comment on Jira before coding |
| Webhook duplicate events | Low | Pipeline state check at entry of every agent invocation |
| Large codebase context overflow | Medium | Scope codebase loading to changed files + direct imports only |

---

## 12. Runtime Requirements

### Where to Run

The pipeline must run **on a machine with access to:**
1. The target codebase (local clone for agent context)
2. The GitLab API (for branch/commit/MR operations)
3. Claude Code CLI (authenticated)
4. Internet access for Jira and Slack APIs

The webhook receiver runs as an Express server. Deploy it on a server with a public IP or domain so issue trackers and git providers can send webhooks to it.

### How Agents Access the Codebase

Agents **do not clone or pull** the repo. They:
- Read the local filesystem for codebase context (understanding patterns, existing files)
- Commit changes remotely via the GitLab MCP server (REST API)

This means the local clone provides context but the agent's changes go directly to GitLab. The local repo does not need to be on the same branch as the agent's feature branch.

---

## 12.1 Multi-Repo Support

The pipeline supports three repo modes via `config.yaml`:

### dir — Single Repo

```yaml
repo:
  mode: dir
  path: /projects/my-app
  baseBranch: main
```

### parentDir — Multiple Repos

```yaml
repo:
  mode: parentDir
  path: /projects
  baseBranch: main
```

```
/projects/
  ├── frontend-app/
  ├── backend-api/
  └── shared-libs/
```

The ticket's component field selects the subdirectory.

### clone — Clone from URL(s)

```yaml
repo:
  mode: clone
  urls:
    - https://github.com/org/frontend.git
    - https://github.com/org/backend.git
  cloneDir: /tmp/auto-pilot-repos
  baseBranch: develop
```

Repos are cloned on first ticket and reused after. On each new ticket, the pipeline runs `git stash`, checks out `baseBranch`, and resets to origin.

---

## 13. Next Steps

1. Set up a test Jira project with a "Ready for Development" status
2. Create a sandbox GitLab repo that mirrors the real project structure
3. Configure `.env` with actual tokens and IDs
4. Follow the build order in Section 10
5. Test with a real ticket through the full lifecycle
