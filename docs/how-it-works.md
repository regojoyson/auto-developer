[< Back to README](../README.md) | [Prerequisites](prerequisites.md) | [Setup](setup.md) | [Configuration](configuration.md) | [API Spec](api-spec.md) | [Custom Providers](custom-providers.md)

---

# How It Works

This document explains the full pipeline — from ticket to merged code.

---

## Overview

```
  Ticket Created                        Code Merged
       │                                     ▲
       ▼                                     │
  ┌─────────┐    ┌───────────┐    ┌──────────────┐    ┌─────────┐
  │ Webhook  │───▶│Orchestrator│───▶│  Brainstorm  │───▶│Developer │
  │ Receiver │    │   Agent    │    │    Agent     │    │  Agent   │
  └─────────┘    └───────────┘    └──────────────┘    └────┬─────┘
                       ▲                                    │
                       │                                    ▼
                  ┌────┴─────┐                      ┌──────────────┐
                  │ Feedback │◀─────────────────────│  PR / MR     │
                  │  Parser  │     Review comment    │  Created     │
                  └──────────┘                      └──────────────┘
```

---

## Phase 1: Trigger

A ticket becomes ready for development. This can happen two ways:

**Automatic (webhook):**
The issue tracker (Jira / GitHub Issues) sends a webhook when the ticket status changes to the configured `triggerStatus` (e.g. "Ready for Development").

**Manual (API call):**
```bash
curl -X POST http://localhost:3000/api/trigger \
  -d '{"issueKey": "PROJ-42"}'
```

Either way, the pipeline does the same thing next.

---

## Phase 2: Preparation

Before any agent starts, the pipeline:

1. **Resolves the target repo** — based on `config.yaml` repo mode (local dir, parent dir, or clone)
2. **Checks out the base branch** — `git checkout main && git pull` (or whatever `baseBranch` is configured)
3. **Creates pipeline state** — a JSON file tracking this ticket's progress
4. **Responds immediately** — the webhook gets a 202 response, everything after is async

---

## Phase 3: Orchestrator Agent

The orchestrator is the coordinator. It:

1. Reads the full ticket details via the issue tracker MCP (description, acceptance criteria, linked issues)
2. Creates a feature branch: `feature/PROJ-42-add-login-page`
3. Writes `TICKET.md` to the branch with all ticket context
4. Invokes the **brainstorm agent**

---

## Phase 4: Brainstorm Agent

The brainstorm agent analyzes the ticket and codebase:

1. Reads `TICKET.md` for requirements
2. Explores the codebase (file structure, patterns, dependencies)
3. Generates 2-3 candidate approaches with trade-offs
4. Selects the best approach
5. Writes `PLAN.md` with:
   - Chosen approach and reasoning
   - File change list (create/modify/delete)
   - Implementation steps
   - Acceptance criteria mapping

The brainstorm agent does **not** write code — only the plan.

---

## Phase 5: Developer Agent

The developer agent implements from the plan:

1. Reads `PLAN.md`
2. Implements every file change listed
3. Runs tests if present
4. Commits with message: `feat(PROJ-42): add login page`

---

## Phase 6: PR/MR Creation

The orchestrator creates a pull/merge request:

- Title: `feat(PROJ-42): Add login page`
- Description: plan summary + file changes + ticket link
- Target branch: the configured `baseBranch`
- Posts a comment on the ticket with the PR link
- Sends a notification (if configured)

The pipeline state moves to `awaiting-review` and **pauses** — waiting for a human.

---

## Phase 7: Review Loop

The human reviewer reads the diff and has three options:

### Option A: Approve

- Reviewer approves the PR/MR
- Pipeline transitions the ticket to "Done"
- Notification sent: "PROJ-42 merged successfully"
- Done.

### Option B: Push edits

- Reviewer pushes their own commits to the branch
- Pipeline detects the human push, does nothing — waits for approval
- Reviewer can then approve normally (back to Option A)

### Option C: Comment feedback

- Reviewer posts a comment on the PR/MR
- **Feedback Parser Agent** reads the comment thread, produces `FEEDBACK.md`:
  ```
  ## Change Requests
  ### 1. [File: src/login.js, Line: 42]
  Rename `processLogin` to `handleLogin`
  ### 2. [General]
  Add error handling for timeout case
  ```
- **Developer Agent** (rework mode) reads `FEEDBACK.md` and applies only the requested changes
- New commit pushed, PR updated with changelog
- Reviewer re-notified
- Back to **awaiting-review** — loop repeats

### Rework limit

After 3 rework cycles (configurable), the pipeline stops and sends an escalation:
"PROJ-42 has exceeded the rework limit — human intervention needed"

---

## Pipeline States

```
brainstorming → developing → awaiting-review → merged
                                   ↓       ↑
                                reworking ──┘
```

| State | What's happening |
|-------|-----------------|
| `brainstorming` | Brainstorm agent is writing PLAN.md |
| `developing` | Developer agent is implementing code |
| `awaiting-review` | PR/MR is open, waiting for human |
| `reworking` | Developer is applying review feedback |
| `merged` | PR approved, ticket closed |

You can check the current state anytime:
```bash
curl http://localhost:3000/api/status
curl http://localhost:3000/api/status/PROJ-42
```

---

## Monitoring

<p align="center">
  <img src="monitoring.svg" alt="Monitoring — Real-time Agent Visibility" width="700"/>
</p>

While agents run, their output streams in real-time to pluggable output handlers:

| Method | Command |
|--------|---------|
| **Log files** | `tail -f logs/agents/PROJ-42-orchestrator.log` |
| **API** | `curl http://localhost:3000/api/status/PROJ-42/logs` |
| **API (one agent)** | `curl http://localhost:3000/api/status/PROJ-42/logs?agent=brainstorm` |
| **Server log** | `tail -f logs/server.log` |

Configure which handlers are active in `config.yaml`:
```yaml
pipeline:
  outputHandlers:
    - file      # logs/agents/ — tail -f
    - memory    # API — /api/status/{key}/logs
```

---

## Artifacts

Each ticket produces three markdown files on the feature branch:

| File | Written by | Contains |
|------|-----------|----------|
| `TICKET.md` | Orchestrator | Full ticket context from issue tracker |
| `PLAN.md` | Brainstorm agent | Implementation plan with file changes |
| `FEEDBACK.md` | Feedback parser | Structured review comments (only during rework) |

---

## What runs where

| Component | Runs from | Accesses |
|-----------|-----------|----------|
| Webhook server | Auto-pilot directory | HTTP endpoints |
| Agents (via CLI) | Target repo directory (cwd) | Local filesystem for context |
| Git operations | GitLab/GitHub REST API | Remote — no local git push |
| Issue tracker | Jira/GitHub MCP | Remote API |
| Notifications | Slack MCP | Remote API |

The auto-pilot server and the target repo can be on the same machine but in different directories. Agents read local files for context but commit code remotely via the git provider API.
