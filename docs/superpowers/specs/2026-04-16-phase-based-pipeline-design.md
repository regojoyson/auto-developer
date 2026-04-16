# Phase-Based Pipeline Redesign

**Date:** 2026-04-16
**Status:** Approved for Implementation
**Approach:** B — Python server drives phases, agents do focused single jobs

---

## Problem

The current orchestrator agent runs the entire pipeline (analyze, plan, implement, create MR) in a single invocation. The state machine exists but is never updated during execution — state stays at `brainstorming` the entire time. Jira ticket status is not updated between phases. The pipeline produces no visibility into progress (no Jira comments showing analysis or plan).

## Goal

Restructure the pipeline so the **Python server controls the lifecycle** and agents are invoked for one focused phase at a time. Each phase transitions pipeline state, updates Jira status, and posts Jira comments for visibility. The flow is fully automatic (no human gates between phases) but each phase is isolated and trackable.

---

## New Pipeline Flow

### State Machine

```
analyzing -> planning -> developing -> awaiting-review -> merged
    |            |           |              |       ^
    +-----+------+-----------+           reworking --+
          |                                  |
        failed  <----------------------------+
```

New states: `analyzing`, `planning`, `failed`. Replaces old `brainstorming`. Any active phase can transition to `failed` on unrecoverable errors. `failed` is terminal — clear state and re-trigger to retry.

### Phase Sequence (new ticket)

| Step | Phase | Pipeline State | Jira Status | Agent Invoked | Output |
|------|-------|---------------|-------------|---------------|--------|
| 1 | Pickup | `analyzing` | Ready for Dev -> Development | none | Jira transitioned |
| 2 | Analyze | `analyzing` | Development | orchestrator (action=analyze) | TICKET.md written, analysis posted as Jira comment |
| 3 | Plan | `planning` | Development | orchestrator (action=plan) | PLAN.md written, plan posted as Jira comment |
| 4 | Implement | `developing` | Development | orchestrator (action=implement) | Code committed, pushed, MR created |
| 5 | Done | `awaiting-review` | Done | none | Jira comment with MR link, Jira transitioned to Done, Slack notification |

### Blocker Handling (steps 2 and 3)

If the analyze or plan phase detects insufficient information:
1. Agent returns `{"blocked": true, "reason": "..."}`
2. Python server posts a Jira comment explaining what info is needed
3. Python server transitions Jira to Blocked status (from config)
4. Pipeline state stays at current phase — pipeline stops
5. Slack notification sent

### Rework Sequence (PR comment received)

| Step | Phase | Pipeline State | Jira Status | Agent Invoked | Output |
|------|-------|---------------|-------------|---------------|--------|
| 1 | Pickup | `reworking` | Done -> Development | none | Jira transitioned, rework count incremented |
| 2 | Parse feedback | `reworking` | Development | feedback-parser | FEEDBACK.md written |
| 3 | Apply fixes | `reworking` | Development | orchestrator (action=rework) | Code committed, pushed |
| 4 | Done | `awaiting-review` | Done | none | Jira comment, Jira transitioned back to Done |

Rework capped at `maxReworkIterations` from config (default 3). If exceeded: escalate to Slack, post Jira comment, stop.

---

## Config Changes

### New field: `developmentStatus`

```yaml
issueTracker:
  type: jira
  triggerStatus: Ready for Development
  developmentStatus: Development        # NEW
  doneStatus: Done
  blockedStatus: Blocked
```

**File:** `config.yaml` (user config) and `src/config.py` (loader)

The `developmentStatus` is passed to agents in the `statuses` input JSON alongside the existing `trigger`, `done`, and `blocked` statuses.

### Branch Naming Change

Current: `feature/EV-14111-create-dashboard`
New: `ev-14111_create_dashboard`

Format: `{issueKey}_{slug}` where slug is lowercase, underscores, max 40 chars. No `feature/` prefix.

**Files affected:** `src/routes/issue_tracker.py`, `src/routes/trigger.py` (branch name generation)

---

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `src/executor/pipeline.py` | Phase runner — `run_pipeline_phases()` and `run_rework_phases()` functions that drive the lifecycle |

### Modified Files

| File | Changes |
|------|---------|
| `src/config.py` | Add `development_status` to `issue_tracker` config parsing |
| `src/state/manager.py` | Add `analyzing`, `planning`, `failed` states to `VALID_TRANSITIONS`. Update initial state to `analyzing`. Add `record_phase_start()`, `record_phase_end()`, `update_artifacts()`. Extend `transition_state()` with optional `error` param. |
| `src/routes/issue_tracker.py` | Call `run_pipeline_phases()` instead of `run_agent("orchestrator")`. Update branch naming. |
| `src/routes/trigger.py` | Same as issue_tracker — call `run_pipeline_phases()`. Update branch naming. |
| `src/routes/git_provider.py` | Rework path calls `run_rework_phases()` instead of just running feedback-parser. Add Jira status transitions. |
| `agents/orchestrator.md` | Split monolithic `new-ticket` action into `analyze`, `plan`, `implement`, `rework` actions. |
| `dashboard-react/src/styles.css` | Add badge styles for `analyzing` and `planning` states. |
| `docs/configuration.md` | Document the new `developmentStatus` field. |
| `docs/how-it-works.md` | Update phase descriptions and state diagram. |

### Unchanged Files

| File | Why unchanged |
|------|--------------|
| `agents/brainstorm.md` | Still writes PLAN.md — invoked by orchestrator's `plan` action |
| `agents/developer.md` | Still implements from PLAN.md/FEEDBACK.md — invoked by orchestrator's `implement`/`rework` action |
| `agents/feedback-parser.md` | Still parses PR comments into FEEDBACK.md |
| `agents/RULES.md` | Global rules still apply. Update state list in the Pipeline State Machine section. |
| `src/executor/runner.py` | `run_agent()` stays the same — `pipeline.py` calls it |
| `src/providers/base.py` | Add `transition_issue()` and `add_comment()` abstract methods to `IssueTrackerBase` |
| `src/providers/trackers/jira.py` | Implement `transition_issue()` and `add_comment()` via Jira REST API |
| `src/providers/trackers/github_issues.py` | Implement `transition_issue()` and `add_comment()` via GitHub API |
| `src/server.py` | No changes — routes handle the new logic |
| `mcp_servers/*` | No changes |

---

## Detailed Design: `src/executor/pipeline.py`

```python
def run_pipeline_phases(issue_key, branch, summary, project_key, base_branch, statuses, repo_dir):
    """
    Drive the full pipeline: analyze -> plan -> implement -> awaiting-review.
    Runs synchronously in a background thread (called from route handlers).
    """
    # Step 1: Transition Jira to Development status
    # Uses issue tracker MCP or direct Jira API call
    _transition_jira(issue_key, statuses["development"])

    # Step 2: Analyze phase
    transition_state(branch, "analyzing")  # state: analyzing
    input_data = json.dumps({
        "action": "analyze",
        "issueKey": issue_key,
        "branch": branch,
        "projectKey": project_key,
        "baseBranch": base_branch,
        "statuses": statuses,
    })
    result = run_agent("orchestrator", input_data, cwd=repo_dir, issue_key=issue_key)
    if not result.get("success"):
        _handle_agent_failure(issue_key, branch, "orchestrator:analyze", result)
        return
    if _is_blocked(result):
        _handle_blocked(issue_key, branch, statuses, result)
        return

    # Step 3: Plan phase
    transition_state(branch, "planning")
    input_data = json.dumps({
        "action": "plan",
        "issueKey": issue_key,
        "branch": branch,
        "statuses": statuses,
    })
    result = run_agent("orchestrator", input_data, cwd=repo_dir, issue_key=issue_key)
    if not result.get("success"):
        _handle_agent_failure(issue_key, branch, "orchestrator:plan", result)
        return
    if _is_blocked(result):
        _handle_blocked(issue_key, branch, statuses, result)
        return

    # Step 4: Implement phase
    transition_state(branch, "developing")
    input_data = json.dumps({
        "action": "implement",
        "issueKey": issue_key,
        "branch": branch,
        "baseBranch": base_branch,
        "statuses": statuses,
    })
    result = run_agent("orchestrator", input_data, cwd=repo_dir, issue_key=issue_key)
    if not result.get("success"):
        _handle_agent_failure(issue_key, branch, "orchestrator:implement", result)
        return

    # Step 5: Transition to awaiting-review
    transition_state(branch, "awaiting-review")
    _transition_jira(issue_key, statuses["done"])
    _notify_slack(f"MR created for {issue_key}")


def _handle_agent_failure(issue_key, branch, agent_name, result):
    """
    Called when an agent exits with a non-zero exit code (not blocked, just failed).
    Posts a Jira comment noting the failure, sends Slack notification.
    Pipeline state stays at the current phase so it can be retried via /api/trigger.
    """
    logger.error(f"Agent {agent_name} failed for {issue_key}: {result.get('error')}")
    _post_jira_comment(issue_key, f"Pipeline failed during {agent_name}: {result.get('error', 'unknown error')}")
    _notify_slack(f"{issue_key} pipeline failed during {agent_name} — check logs")


def run_rework_phases(issue_key, branch, pr_id, statuses, repo_dir):
    """
    Drive the rework loop: parse feedback -> apply fixes -> awaiting-review.
    """
    # Transition Jira to Development
    _transition_jira(issue_key, statuses["development"])
    transition_state(branch, "reworking")

    # Step 1: Parse feedback
    feedback_input = json.dumps({
        "issueKey": issue_key,
        "branch": branch,
        "prId": pr_id,
    })
    run_agent("feedback-parser", feedback_input, cwd=repo_dir, issue_key=issue_key)

    # Step 2: Apply rework
    rework_input = json.dumps({
        "action": "rework",
        "issueKey": issue_key,
        "branch": branch,
        "statuses": statuses,
    })
    run_agent("orchestrator", rework_input, cwd=repo_dir, issue_key=issue_key)

    # Step 3: Back to awaiting-review
    transition_state(branch, "awaiting-review")
    _transition_jira(issue_key, statuses["done"])
    _notify_slack(f"Rework completed for {issue_key}")
```

**Helper functions** (`_transition_jira`, `_handle_blocked`, `_is_blocked`, `_notify_slack`):
- `_transition_jira`: Calls the issue tracker adapter to transition Jira status. Needs a lightweight way to invoke Jira API from Python (not via agent). Can use the Jira REST API directly or invoke a minimal agent call.
- `_handle_blocked`: Posts Jira comment with reason, transitions to blocked status, sends Slack notification, logs.
- `_is_blocked`: Parses agent output for blocked signal. The orchestrator agent will output a JSON line like `__PIPELINE_RESULT__:{"blocked":true,"reason":"..."}` that the runner can extract.
- `_notify_slack`: Calls the notification adapter to send a Slack message.

### Agent Result Communication

The orchestrator agent needs to communicate structured results back to the Python server. Since agents run as subprocesses, the convention is:

1. Agent writes a result line to stdout: `__PIPELINE_RESULT__:{"blocked":false}` or `__PIPELINE_RESULT__:{"blocked":true,"reason":"Missing AC"}`
2. `run_agent()` (or a wrapper) extracts this line from output
3. `pipeline.py` uses the parsed result to decide next steps

This is a simple stdout-based protocol that doesn't require any new infrastructure.

---

## Detailed Design: `agents/orchestrator.md`

The orchestrator agent is split into four focused actions:

### Action: `analyze`
Input: `issueKey`, `branch`, `projectKey`, `baseBranch`, `statuses`

Steps:
1. Read the full Jira ticket via issue tracker MCP (all fields, attachments, comments, linked issues)
2. Evaluate if ticket has sufficient detail (per RULES.md criteria)
3. If insufficient: output `__PIPELINE_RESULT__:{"blocked":true,"reason":"<details>"}` and stop
4. Create the feature branch from baseBranch using git provider MCP
5. Write TICKET.md to the branch root with full ticket context
6. Commit TICKET.md to the feature branch
7. Post a Jira comment with the analysis summary (scope, key requirements, relevant files identified)
8. Output `__PIPELINE_RESULT__:{"blocked":false}`

### Action: `plan`
Input: `issueKey`, `branch`, `statuses`

Steps:
1. Invoke the brainstorm agent (reads TICKET.md, explores codebase, writes PLAN.md)
2. After brainstorm completes, read PLAN.md
3. If plan reveals fundamental blockers: output `__PIPELINE_RESULT__:{"blocked":true,"reason":"<details>"}` and stop
4. Post a Jira comment with the plan summary (chosen approach, file changes, implementation notes)
5. Output `__PIPELINE_RESULT__:{"blocked":false}`

### Action: `implement`
Input: `issueKey`, `branch`, `baseBranch`, `statuses`

Steps:
1. Invoke the developer agent (first-pass mode — reads PLAN.md, implements code)
2. After developer completes, verify commits were pushed to the feature branch
3. Create MR/PR to baseBranch via git provider MCP:
   - Title: `feat({issueKey}): {summary}`
   - Description: plan summary + file changes + ticket link
4. Post a Jira comment: "Implementation completed. MR: {link}"
5. Send Slack notification: "MR created for {issueKey} — {link}"

### Action: `rework`
Input: `issueKey`, `branch`, `statuses`

Steps:
1. Read FEEDBACK.md from the branch root
2. Invoke the developer agent in rework mode
3. After developer completes, verify commits were pushed
4. Post a Jira comment: "Rework completed based on review feedback"

### Action: `merge-approved` (unchanged)
Input: `issueKey`, `branch`, `prId`, `statuses`

Steps:
1. Transition Jira to Done status
2. Send Slack notification: "{issueKey} merged successfully"

### Action: `rework-limit-exceeded` (unchanged)
Input: `issueKey`, `branch`, `reworkCount`

Steps:
1. Send Slack notification: "{issueKey} exceeded rework limit"
2. Post Jira comment noting escalation

---

## Detailed Design: State Machine Changes

### `src/state/manager.py`

```python
VALID_TRANSITIONS = {
    "analyzing": ["planning", "failed"],
    "planning": ["developing", "failed"],
    "developing": ["awaiting-review", "failed"],
    "awaiting-review": ["reworking", "merged"],
    "reworking": ["awaiting-review", "failed"],
}
```

Initial state changes from `"brainstorming"` to `"analyzing"` in `create_state()`.

Initial state file now includes `phases: []`, `artifacts: {}`, and `error: null`.

---

## Detailed Design: Branch Naming

Current format: `feature/{issueKey}-{slug}`
New format: `{issueKey_lower}_{slug}`

Example: `ev-14111_create_dashboard`

Changes in `issue_tracker.py` and `trigger.py`:
```python
# Old
branch = f"feature/{issue_key}-{slug}"

# New
branch = f"{issue_key.lower()}_{slug}"
```

---

## Detailed Design: Config Changes

### `config.yaml`

```yaml
issueTracker:
  type: jira
  triggerStatus: Ready for Development
  developmentStatus: Development        # NEW
  doneStatus: Done
  blockedStatus: Blocked
```

### `src/config.py`

Add to the `issue_tracker` section:
```python
"development_status": raw.get("issueTracker", {}).get("developmentStatus", "Development"),
```

Add to the `statuses` dict passed to agents:
```python
"statuses": {
    "trigger": tracker_cfg["trigger_status"],
    "development": tracker_cfg["development_status"],  # NEW
    "done": tracker_cfg["done_status"],
    "blocked": tracker_cfg["blocked_status"],
},
```

---

## Detailed Design: Dashboard CSS

Add badge styles for new states in `dashboard-react/src/styles.css`:

```css
.badge-analyzing     { background: #e0f2fe; color: #0369a1; }
.badge-planning      { background: #dbeafe; color: #1e40af; }
.badge-failed        { background: #fee2e2; color: #991b1b; }
```

The existing `badge-brainstorming` can be kept for backward compatibility or removed.

---

## Detailed Design: Route Changes

### `src/routes/issue_tracker.py`

```python
# Branch naming
branch = f"{issue_key.lower()}_{slug}"

# Launch pipeline phases instead of single orchestrator
threading.Thread(
    target=run_pipeline_phases,
    args=(issue_key, branch, summary, project_key, base_branch, statuses, repo_dir),
    daemon=True
).start()
```

### `src/routes/trigger.py`

Same changes as issue_tracker.py.

### `src/routes/git_provider.py`

For the comment (rework) event:
```python
# Check rework limit first (existing)
# Then call run_rework_phases instead of just feedback-parser
threading.Thread(
    target=run_rework_phases,
    args=(issue_key, branch, pr_id, statuses, repo_dir),
    daemon=True
).start()
```

---

## Detailed Design: Jira Transition from Python

The `_transition_jira()` helper in `pipeline.py` needs to call the Jira API to change ticket status. Two options:

**Chosen approach:** Extend the existing Jira adapter (`src/providers/trackers/jira.py`) with `transition_issue(issue_key, status_name)` and `add_comment(issue_key, comment_body)` methods. This keeps all Jira logic centralized in one provider. The GitHub Issues adapter gets equivalent methods.

These methods use the Jira REST API directly (via `requests`), using `JIRA_TOKEN` / `JIRA_BASE_URL` from `.env`. No agent invocation needed for status transitions or comments from the Python server.

The `IssueTrackerBase` abstract class in `src/providers/base.py` gets two new abstract methods: `transition_issue()` and `add_comment()`, so all tracker adapters must implement them.

---

## RULES.md Update

Update the Pipeline State Machine section:
```
States: `analyzing` -> `planning` -> `developing` -> `awaiting-review` -> `reworking` -> `merged`
```

---

## Detailed Design: Error Handling

Every external call (Jira API, Slack, git operations, agent invocations) can fail. The pipeline must handle failures gracefully, leave the state machine in a recoverable position, and provide visibility into what went wrong.

### Error Categories and Behavior

| Category | Examples | Pipeline Behavior | State |
|----------|---------|-------------------|-------|
| **Agent failure** | Agent exits non-zero, times out | Post Jira comment with error, Slack notification, set state to `failed` | `failed` |
| **Agent blocked** | Insufficient ticket info, plan reveals blocker | Post Jira comment with reason, transition Jira to Blocked, Slack notification | Stays at current phase (e.g. `analyzing`) |
| **Jira API failure** | Transition fails, comment fails | Log error, continue pipeline — Jira updates are best-effort, don't block the work | No change |
| **Slack failure** | Channel not found, token expired | Log warning, continue — notifications are best-effort | No change |
| **Git operation failure** | Branch creation fails, MR creation fails | Post Jira comment, set state to `failed` — git failures are fatal | `failed` |

### New State: `failed`

Added to the state machine:

```
analyzing -> planning -> developing -> awaiting-review -> merged
    |            |           |              |       ^
    +-----+------+-----------+           reworking --+
          |
        failed
```

Any phase can transition to `failed`. The `failed` state is terminal — the pipeline stops. To retry, the user cancels the pipeline via `DELETE /api/status/{issueKey}` and re-triggers.

```python
VALID_TRANSITIONS = {
    "analyzing": ["planning", "failed"],
    "planning": ["developing", "failed"],
    "developing": ["awaiting-review", "failed"],
    "awaiting-review": ["reworking", "merged"],
    "reworking": ["awaiting-review", "failed"],
}
```

### Error Details in State File

When the pipeline enters `failed` state, the error details are stored:

```json
{
  "state": "failed",
  "error": {
    "phase": "developing",
    "agent": "orchestrator:implement",
    "message": "Agent timed out after 300s",
    "timestamp": "2026-04-16T22:15:00Z"
  }
}
```

### `_handle_agent_failure` — Full Implementation

```python
def _handle_agent_failure(issue_key, branch, agent_name, result, statuses):
    """Handle a non-zero agent exit."""
    error_msg = result.get("error", "unknown error")
    logger.error(f"Agent {agent_name} failed for {issue_key}: {error_msg}")

    # 1. Transition pipeline state to failed (with error details)
    transition_state(branch, "failed", error={
        "phase": get_state(branch)["state"],
        "agent": agent_name,
        "message": error_msg,
    })

    # 2. Post Jira comment (best-effort)
    try:
        tracker.add_comment(issue_key,
            f"Pipeline failed during {agent_name}.\n\nError: {error_msg}\n\nCheck logs for details.")
    except Exception as e:
        logger.warning(f"Failed to post Jira comment for {issue_key}: {e}")

    # 3. Slack notification (best-effort)
    try:
        _notify_slack(f"{issue_key} pipeline failed during {agent_name} — check logs")
    except Exception as e:
        logger.warning(f"Failed to send Slack notification for {issue_key}: {e}")
```

### `_handle_blocked` — Full Implementation

```python
def _handle_blocked(issue_key, branch, statuses, result):
    """Handle an agent reporting the ticket is blocked."""
    reason = _extract_blocked_reason(result)
    logger.info(f"Pipeline blocked for {issue_key}: {reason}")

    # 1. Post Jira comment (best-effort)
    try:
        tracker.add_comment(issue_key,
            f"Pipeline blocked — additional information needed:\n\n{reason}")
    except Exception as e:
        logger.warning(f"Failed to post Jira comment for {issue_key}: {e}")

    # 2. Transition Jira to Blocked status (best-effort)
    try:
        tracker.transition_issue(issue_key, statuses["blocked"])
    except Exception as e:
        logger.warning(f"Failed to transition Jira for {issue_key}: {e}")

    # 3. Slack notification (best-effort)
    try:
        _notify_slack(f"{issue_key} blocked — {reason}")
    except Exception as e:
        logger.warning(f"Failed to send Slack notification for {issue_key}: {e}")

    # Pipeline state stays at current phase — NOT transitioned to failed.
    # The ticket can be unblocked and re-triggered.
```

### Wrapping Phase Calls with try/except

Each phase in `run_pipeline_phases` is wrapped:

```python
try:
    result = run_agent("orchestrator", input_data, cwd=repo_dir, issue_key=issue_key)
except Exception as e:
    _handle_agent_failure(issue_key, branch, "orchestrator:analyze",
        {"success": False, "error": str(e)}, statuses)
    return
```

This catches unexpected exceptions (subprocess crashes, OOM, etc.) that `run_agent` doesn't handle internally.

### Jira/Slack Calls Are Best-Effort

All Jira transitions and Slack notifications in the happy path are also wrapped in try/except:

```python
# Best-effort Jira transition — don't stop the pipeline if Jira is down
try:
    tracker.transition_issue(issue_key, statuses["development"])
except Exception as e:
    logger.warning(f"Failed to transition Jira {issue_key} to Development: {e}")
```

The pipeline continues even if Jira or Slack calls fail. The only fatal failures are agent failures and git operation failures.

---

## Detailed Design: Pipeline State Tracking

### Enriched State File

The pipeline state file is the single source of truth for tracking. It gets new fields for phase history, timing, and artifact tracking:

```json
{
  "branch": "ev-14111_create_dashboard",
  "issueKey": "EV-14111",
  "state": "developing",
  "createdAt": "2026-04-16T21:30:00Z",
  "updatedAt": "2026-04-16T21:45:00Z",
  "reworkCount": 0,
  "repoPath": "/Users/admin/data/workspace/EdgeReg",
  "error": null,
  "phases": [
    {
      "phase": "analyzing",
      "startedAt": "2026-04-16T21:30:05Z",
      "completedAt": "2026-04-16T21:32:10Z",
      "agent": "orchestrator:analyze",
      "exitCode": 0,
      "result": "success"
    },
    {
      "phase": "planning",
      "startedAt": "2026-04-16T21:32:11Z",
      "completedAt": "2026-04-16T21:38:45Z",
      "agent": "orchestrator:plan",
      "exitCode": 0,
      "result": "success"
    },
    {
      "phase": "developing",
      "startedAt": "2026-04-16T21:38:46Z",
      "completedAt": null,
      "agent": "orchestrator:implement",
      "exitCode": null,
      "result": null
    }
  ],
  "artifacts": {
    "mrUrl": null,
    "prId": null,
    "ticketMdCommit": "abc1234",
    "planMdCommit": "def5678"
  }
}
```

### `phases` Array

Every phase execution is recorded with:
- `phase`: state name when this ran
- `startedAt` / `completedAt`: ISO timestamps
- `agent`: which agent ran (e.g. `orchestrator:analyze`, `feedback-parser`)
- `exitCode`: agent process exit code (null while running)
- `result`: `"success"`, `"failed"`, `"blocked"`, or null while running

Rework phases append to the same array, so you get a full timeline:
```json
{
  "phase": "reworking",
  "startedAt": "2026-04-17T10:00:00Z",
  "completedAt": "2026-04-17T10:15:00Z",
  "agent": "orchestrator:rework",
  "exitCode": 0,
  "result": "success",
  "reworkIteration": 1
}
```

### `artifacts` Object

Tracks key outputs:
- `mrUrl`: MR/PR URL once created
- `prId`: MR/PR numeric ID for webhook matching
- `ticketMdCommit`: commit SHA of TICKET.md
- `planMdCommit`: commit SHA of PLAN.md

### State Manager Changes

`transition_state()` signature extends to accept optional metadata:

```python
def transition_state(branch: str, new_state: str, error: dict | None = None) -> dict:
    # existing validation...
    current["state"] = new_state
    current["updatedAt"] = now
    if error:
        current["error"] = {**error, "timestamp": now}
    if new_state == "reworking":
        current["reworkCount"] = current.get("reworkCount", 0) + 1
    _state_path(branch).write_text(json.dumps(current, indent=2))
    return current
```

New helper functions:

```python
def record_phase_start(branch: str, phase: str, agent: str) -> dict:
    """Record the start of a phase execution in the phases array."""
    current = get_state(branch)
    phases = current.get("phases", [])
    phases.append({
        "phase": phase,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "completedAt": None,
        "agent": agent,
        "exitCode": None,
        "result": None,
    })
    current["phases"] = phases
    current["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _state_path(branch).write_text(json.dumps(current, indent=2))
    return current


def record_phase_end(branch: str, exit_code: int, result: str) -> dict:
    """Record the completion of the current phase."""
    current = get_state(branch)
    phases = current.get("phases", [])
    if phases and phases[-1]["completedAt"] is None:
        phases[-1]["completedAt"] = datetime.now(timezone.utc).isoformat()
        phases[-1]["exitCode"] = exit_code
        phases[-1]["result"] = result
    current["phases"] = phases
    current["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _state_path(branch).write_text(json.dumps(current, indent=2))
    return current


def update_artifacts(branch: str, **kwargs) -> dict:
    """Update artifact tracking (mrUrl, prId, etc.)."""
    current = get_state(branch)
    artifacts = current.get("artifacts", {})
    artifacts.update(kwargs)
    current["artifacts"] = artifacts
    current["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _state_path(branch).write_text(json.dumps(current, indent=2))
    return current
```

### Updated `run_pipeline_phases` with Tracking

```python
def run_pipeline_phases(issue_key, branch, summary, project_key, base_branch, statuses, repo_dir):
    # Step 1: Jira transition (best-effort)
    _try_transition_jira(issue_key, statuses["development"])

    # Step 2: Analyze
    record_phase_start(branch, "analyzing", "orchestrator:analyze")
    try:
        result = run_agent("orchestrator", analyze_input, cwd=repo_dir, issue_key=issue_key)
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, "orchestrator:analyze", {"error": str(e)}, statuses)
        return

    if not result.get("success"):
        record_phase_end(branch, result.get("exit_code", -1), "failed")
        _handle_agent_failure(issue_key, branch, "orchestrator:analyze", result, statuses)
        return
    if _is_blocked(result):
        record_phase_end(branch, 0, "blocked")
        _handle_blocked(issue_key, branch, statuses, result)
        return
    record_phase_end(branch, 0, "success")

    # Step 3: Plan
    transition_state(branch, "planning")
    record_phase_start(branch, "planning", "orchestrator:plan")
    # ... same pattern ...

    # Step 4: Implement
    transition_state(branch, "developing")
    record_phase_start(branch, "developing", "orchestrator:implement")
    # ... same pattern ...

    # Step 5: Awaiting review
    transition_state(branch, "awaiting-review")
    _try_transition_jira(issue_key, statuses["done"])
    _try_notify_slack(f"MR created for {issue_key}")
```

### Dashboard / API Tracking

The `GET /api/status/{issue_key}` endpoint already returns the full state file. With the enriched state, the dashboard automatically gets:
- Current phase and how long it's been running
- Full phase history with timing
- Error details if failed
- Artifact links (MR URL)
- Rework count and iteration history

The dashboard `PipelineDetail.jsx` can render the `phases` array as a timeline. A `badge-failed` CSS class is needed:

```css
.badge-failed { background: #fee2e2; color: #991b1b; }
```

---

## Detailed Design: Retry / Re-trigger After Failure

When a pipeline is in `failed` state:
1. User calls `DELETE /api/status/{issueKey}` to clear the state
2. User calls `POST /api/trigger` with the same issue key to re-trigger
3. Pipeline starts fresh from `analyzing`

No partial retry (e.g. "resume from planning") in this version — that adds complexity. The pipeline is fast enough that re-running from the start is acceptable.

---

## What This Does NOT Change

- Agent autonomy rules (RULES.md) — agents remain fully autonomous
- MCP server implementations
- Output handler system (file + memory)
- CLI adapter system (claude-code, codex, gemini)
- Git provider adapters (gitlab.py, github.py)
- Notification adapters (slack.py)
- The brainstorm agent's behavior (still writes PLAN.md)
- The developer agent's behavior (still implements from PLAN.md)
- The feedback-parser agent's behavior (still writes FEEDBACK.md)

---

## Migration

- Existing `.pipeline-state/*.json` files with `state: "brainstorming"` become invalid. They can be deleted or the state machine can treat `brainstorming` as an alias for `analyzing` during a transition period.
- The `config.yaml` needs a new `developmentStatus` field. Default is `"Development"` so existing configs work without changes.
