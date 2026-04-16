[< Back to README](../README.md) | [Prerequisites](prerequisites.md) | [Setup](setup.md) | [How It Works](how-it-works.md) | [Configuration](configuration.md) | [Custom Providers](custom-providers.md)

---

# API Specification

Base URL: `http://localhost:<port>` (port configured in config.yaml, default 3000)

---

## Endpoints Summary

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| POST | `/api/trigger` | Manually start pipeline for a ticket |
| GET | `/api/status` | List all pipelines |
| GET | `/api/status/:issueKey` | Get pipeline status for a ticket |
| POST | `/webhooks/issue-tracker` | Receive issue tracker webhooks |
| POST | `/webhooks/git` | Receive git provider webhooks |

---

## GET /health

Health check endpoint.

**Request:** No body required.

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2026-04-16T10:00:00.000Z"
}
```

| Status | Meaning |
|--------|---------|
| 200 | Server is running |

---

## POST /api/trigger

Manually start the pipeline for a ticket. No webhook needed.

**Request:**
```json
{
  "issueKey": "PROJ-42",
  "summary": "Add login page",
  "component": "frontend-app"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `issueKey` | string | Yes | Ticket identifier (e.g. `PROJ-42`, `my-repo#5`) |
| `summary` | string | No | Ticket title. Used for branch naming. Defaults to issueKey. |
| `component` | string | No | Repo subdirectory name (for parentDir/clone modes). Defaults to primary repo. |

**Response (202 Accepted):**
```json
{
  "accepted": true,
  "issueKey": "PROJ-42",
  "branch": "feature/PROJ-42-add-login-page",
  "repoDir": "/projects/frontend-app"
}
```

| Status | Meaning |
|--------|---------|
| 202 | Pipeline started (processing async) |
| 400 | `issueKey` missing from request body |
| 409 | Pipeline already active for this ticket |
| 500 | Internal error |

**Example:**
```bash
# Minimal
curl -X POST http://localhost:3000/api/trigger \
  -H 'Content-Type: application/json' \
  -d '{"issueKey": "PROJ-42"}'

# With details
curl -X POST http://localhost:3000/api/trigger \
  -H 'Content-Type: application/json' \
  -d '{"issueKey": "PROJ-42", "summary": "Add login page", "component": "frontend-app"}'
```

**Side effects:**
1. Checks out baseBranch and pulls latest in the target repo
2. Creates pipeline state file (state: `brainstorming`)
3. Spawns orchestrator agent asynchronously

---

## GET /api/status

List all active and completed pipelines.

**Request:** No body required.

**Response (200):**
```json
{
  "count": 2,
  "pipelines": [
    {
      "branch": "feature/PROJ-42-add-login-page",
      "issueKey": "PROJ-42",
      "state": "awaiting-review",
      "createdAt": "2026-04-16T09:00:00.000Z",
      "updatedAt": "2026-04-16T09:15:00.000Z",
      "reworkCount": 0,
      "repoPath": "/projects/my-app"
    },
    {
      "branch": "feature/PROJ-43-fix-auth-bug",
      "issueKey": "PROJ-43",
      "state": "developing",
      "createdAt": "2026-04-16T10:00:00.000Z",
      "updatedAt": "2026-04-16T10:05:00.000Z",
      "reworkCount": 0,
      "repoPath": "/projects/my-app"
    }
  ]
}
```

**Example:**
```bash
curl http://localhost:3000/api/status
```

---

## GET /api/status/:issueKey

Get the pipeline status for a specific ticket.

**Request:** Issue key as URL parameter.

**Response (200):**
```json
{
  "branch": "feature/PROJ-42-add-login-page",
  "issueKey": "PROJ-42",
  "state": "awaiting-review",
  "createdAt": "2026-04-16T09:00:00.000Z",
  "updatedAt": "2026-04-16T09:15:00.000Z",
  "reworkCount": 1,
  "repoPath": "/projects/my-app"
}
```

| Status | Meaning |
|--------|---------|
| 200 | Pipeline found |
| 404 | No pipeline for this issue key |

**Example:**
```bash
curl http://localhost:3000/api/status/PROJ-42
```

---

## POST /webhooks/issue-tracker

Receives webhooks from issue trackers (Jira, GitHub Issues).

The payload format depends on the configured issue tracker. The adapter parses it and extracts `issueKey`, `summary`, and `component`.

### Jira payload

Jira sends this when a ticket's status changes:
```json
{
  "changelog": {
    "items": [
      { "field": "status", "toString": "Ready for Development" }
    ]
  },
  "issue": {
    "key": "PROJ-42",
    "fields": {
      "summary": "Add login page",
      "components": [{ "name": "frontend-app" }]
    }
  }
}
```

The adapter only triggers when `toString` matches the `triggerStatus` in config.yaml.

### GitHub Issues payload

GitHub sends this when an issue is labeled:
```json
{
  "action": "labeled",
  "label": { "name": "ready-for-dev" },
  "issue": { "number": 5, "title": "Add login page" },
  "repository": { "name": "my-repo" }
}
```

The adapter only triggers when the label matches `triggerStatus` in config.yaml.

**Response:**

| Status | Body | Meaning |
|--------|------|---------|
| 202 | `{ "accepted": true, "issueKey": "...", "branch": "...", "repoDir": "..." }` | Pipeline started |
| 200 | `{ "ignored": true }` | Event didn't match trigger criteria |
| 200 | `{ "ignored": true, "reason": "already active" }` | Duplicate — pipeline already running |
| 500 | `{ "error": "Internal server error" }` | Something went wrong |

**Side effects (on 202):**
1. Resolves repo directory
2. Checks out baseBranch and pulls latest
3. Creates pipeline state
4. Spawns orchestrator agent

---

## POST /webhooks/git

Receives webhooks from git providers (GitLab, GitHub).

Three event types are handled:

### Event: approved (PR/MR approved)

**GitLab** sends `Merge Request Hook` with `action: "approved"`.
**GitHub** sends `pull_request_review` with `review.state: "approved"`.

**Side effects:**
- Transitions pipeline state to `merged`
- Spawns orchestrator with `action: "merge-approved"` (closes ticket, sends notification)

### Event: push (human edit on PR branch)

**GitLab** sends `Push Hook`.
**GitHub** sends `push` event.

Bot-authored pushes are ignored (filtered by `gitProvider.botUsers` in config.yaml).

**Side effects:**
- Logs the human edit
- No agent action — waits for approval

### Event: comment (review feedback)

**GitLab** sends `Note Hook` with `noteable_type: "MergeRequest"`.
**GitHub** sends `issue_comment` or `pull_request_review_comment`.

Bot-authored comments are ignored.

**Side effects:**
- If rework limit exceeded: spawns orchestrator with `action: "rework-limit-exceeded"` (escalation)
- Otherwise: spawns feedback-parser agent → developer agent rework cycle

**Response:**

| Status | Body | Meaning |
|--------|------|---------|
| 200 | `{ "received": true }` | Event processed |
| 200 | `{ "ignored": true }` | Event didn't match any handler |
| 500 | `{ "error": "Internal server error" }` | Something went wrong |

---

## Pipeline State Schema

Each pipeline is stored as a JSON file in `.pipeline-state/`.

```json
{
  "branch": "feature/PROJ-42-add-login-page",
  "issueKey": "PROJ-42",
  "state": "awaiting-review",
  "createdAt": "2026-04-16T09:00:00.000Z",
  "updatedAt": "2026-04-16T09:15:00.000Z",
  "reworkCount": 1,
  "repoPath": "/projects/my-app"
}
```

### State transitions

```
brainstorming → developing → awaiting-review → merged
                                   ↓       ↑
                                reworking ──┘
```

| From | To | Trigger |
|------|----|---------|
| (new) | `brainstorming` | Ticket received (webhook or manual trigger) |
| `brainstorming` | `developing` | Brainstorm agent completes PLAN.md |
| `developing` | `awaiting-review` | Developer agent commits code, MR/PR created |
| `awaiting-review` | `merged` | Reviewer approves |
| `awaiting-review` | `reworking` | Reviewer posts feedback comment |
| `reworking` | `awaiting-review` | Developer agent applies feedback, updates MR/PR |

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `branch` | string | Git branch name (e.g. `feature/PROJ-42-slug`) |
| `issueKey` | string | Ticket identifier |
| `state` | string | Current pipeline state |
| `createdAt` | ISO 8601 | When the pipeline was created |
| `updatedAt` | ISO 8601 | When the state last changed |
| `reworkCount` | number | How many rework cycles have occurred (0+) |
| `repoPath` | string | Absolute path to the repo directory |

---

## Error Responses

All endpoints return errors in a consistent format:

```json
{
  "error": "Human-readable error message"
}
```

Common status codes:
- `400` — Bad request (missing required fields)
- `404` — Resource not found
- `409` — Conflict (duplicate pipeline)
- `500` — Internal server error
