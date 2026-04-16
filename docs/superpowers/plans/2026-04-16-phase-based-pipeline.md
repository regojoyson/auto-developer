# Phase-Based Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the auto-pilot pipeline so the Python server drives phases one at a time (analyze -> plan -> implement -> review), with state tracking, Jira comments, error handling, and a `failed` state.

**Architecture:** The Python server becomes the lifecycle controller via a new `pipeline.py` module. Agents are invoked for one focused phase and return. State transitions, Jira updates, and error handling happen in Python. A `__PIPELINE_RESULT__` stdout protocol lets agents signal blocked/success back to the server.

**Tech Stack:** Python 3.12, FastAPI, pyyaml, requests (for Jira REST API)

**Spec:** `docs/superpowers/specs/2026-04-16-phase-based-pipeline-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/executor/pipeline.py` | Phase runner: `run_pipeline_phases()`, `run_rework_phases()`, helper functions for Jira/Slack/error handling |

### Modified Files
| File | What changes |
|------|-------------|
| `src/config.py` | Add `development_status` config field |
| `src/state/manager.py` | New states, new tracking functions (`record_phase_start`, `record_phase_end`, `update_artifacts`), extend `transition_state` with error param, enriched initial state |
| `src/providers/base.py` | Add `transition_issue()` and `add_comment()` abstract methods to `IssueTrackerBase` |
| `src/providers/trackers/jira.py` | Implement `transition_issue()` and `add_comment()` via Jira REST API |
| `src/providers/trackers/github_issues.py` | Implement `transition_issue()` and `add_comment()` via GitHub API |
| `src/routes/issue_tracker.py` | New branch naming, call `run_pipeline_phases()`, pass `development` status |
| `src/routes/trigger.py` | Same as issue_tracker route changes |
| `src/routes/git_provider.py` | Rework path calls `run_rework_phases()`, pass `development` status |
| `agents/orchestrator.md` | Split into `analyze`, `plan`, `implement`, `rework` actions with `__PIPELINE_RESULT__` output |
| `agents/RULES.md` | Update state list |
| `dashboard-react/src/styles.css` | Add badge styles for `analyzing`, `planning`, `failed` |
| `docs/configuration.md` | Document `developmentStatus` field |
| `docs/how-it-works.md` | Update phase descriptions and state diagram |

---

### Task 1: Config — Add `developmentStatus`

**Files:**
- Modify: `src/config.py:62-67`

- [ ] **Step 1: Add `development_status` to config loader**

In `src/config.py`, add the new field to the `issue_tracker` dict inside `load()`:

```python
"issue_tracker": {
    "type": raw.get("issueTracker", {}).get("type", "jira"),
    "trigger_status": raw.get("issueTracker", {}).get("triggerStatus", "Ready for Development"),
    "development_status": raw.get("issueTracker", {}).get("developmentStatus", "Development"),
    "done_status": raw.get("issueTracker", {}).get("doneStatus", "Done"),
    "blocked_status": raw.get("issueTracker", {}).get("blockedStatus", "Blocked"),
    "bot_users": raw.get("issueTracker", {}).get("botUsers", []),
},
```

The new line is:
```python
"development_status": raw.get("issueTracker", {}).get("developmentStatus", "Development"),
```

- [ ] **Step 2: Verify config loads**

Run: `cd /Users/admin/data/workspace/claude-skils/auto-pilot && python3 -c "from src.config import config; print(config['issue_tracker']['development_status'])"`

Expected: `Development` (the default value, since config.yaml may not have it yet)

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat: add developmentStatus to config loader"
```

---

### Task 2: State Manager — New States, Tracking Functions, Enriched State

**Files:**
- Modify: `src/state/manager.py`

- [ ] **Step 1: Update VALID_TRANSITIONS**

Replace the existing `VALID_TRANSITIONS` dict (line 33-38) with:

```python
VALID_TRANSITIONS = {
    "analyzing": ["planning", "failed"],
    "planning": ["developing", "failed"],
    "developing": ["awaiting-review", "failed"],
    "awaiting-review": ["reworking", "merged"],
    "reworking": ["awaiting-review", "failed"],
}
```

- [ ] **Step 2: Update `create_state()` initial state**

Change the initial state from `"brainstorming"` to `"analyzing"` and add new tracking fields. Replace the `state` dict in `create_state()` (line 85-93) with:

```python
state = {
    "branch": branch,
    "issueKey": issue_key,
    "state": "analyzing",
    "createdAt": now,
    "updatedAt": now,
    "reworkCount": 0,
    "repoPath": repo_path,
    "error": None,
    "phases": [],
    "artifacts": {},
}
```

- [ ] **Step 3: Extend `transition_state()` with error param**

Update the `transition_state` function signature and body. Replace the entire function (lines 98-129) with:

```python
def transition_state(branch: str, new_state: str, error: dict | None = None) -> dict:
    """Transition a branch's pipeline to a new state.

    Validates the transition against VALID_TRANSITIONS. Increments
    reworkCount when transitioning to "reworking". Stores error details
    when transitioning to "failed".

    Args:
        branch: Git branch name.
        new_state: Target state (e.g. "developing", "awaiting-review", "failed").
        error: Optional error details dict with keys (phase, agent, message).
            Only used when new_state is "failed".

    Returns:
        Updated state dict.

    Raises:
        ValueError: If no state exists for the branch, or the transition
            is not allowed.
    """
    current = get_state(branch)
    if not current:
        raise ValueError(f"No pipeline state for branch: {branch}")

    allowed = VALID_TRANSITIONS.get(current["state"], [])
    if new_state not in allowed:
        raise ValueError(f"Invalid transition: {current['state']} -> {new_state} (branch: {branch})")

    now = datetime.now(timezone.utc).isoformat()
    current["state"] = new_state
    current["updatedAt"] = now
    if new_state == "reworking":
        current["reworkCount"] = current.get("reworkCount", 0) + 1
    if error:
        current["error"] = {**error, "timestamp": now}

    _state_path(branch).write_text(json.dumps(current, indent=2))
    return current
```

- [ ] **Step 4: Add phase tracking functions**

Add these three new functions at the end of the file, before `delete_state`:

```python
def record_phase_start(branch: str, phase: str, agent: str) -> dict:
    """Record the start of a phase execution in the phases array.

    Args:
        branch: Git branch name.
        phase: Pipeline state name (e.g. "analyzing", "planning").
        agent: Agent identifier (e.g. "orchestrator:analyze").

    Returns:
        Updated state dict.
    """
    current = get_state(branch)
    if not current:
        raise ValueError(f"No pipeline state for branch: {branch}")

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
    """Record the completion of the most recent phase.

    Finds the last phase entry with completedAt=None and fills in
    the completion timestamp, exit code, and result.

    Args:
        branch: Git branch name.
        exit_code: Agent process exit code (0 = success).
        result: One of "success", "failed", "blocked".

    Returns:
        Updated state dict.
    """
    current = get_state(branch)
    if not current:
        raise ValueError(f"No pipeline state for branch: {branch}")

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
    """Update artifact tracking fields (mrUrl, prId, etc.).

    Args:
        branch: Git branch name.
        **kwargs: Key-value pairs to merge into the artifacts dict.

    Returns:
        Updated state dict.
    """
    current = get_state(branch)
    if not current:
        raise ValueError(f"No pipeline state for branch: {branch}")

    artifacts = current.get("artifacts", {})
    artifacts.update(kwargs)
    current["artifacts"] = artifacts
    current["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _state_path(branch).write_text(json.dumps(current, indent=2))
    return current
```

- [ ] **Step 5: Verify state machine works**

Run:
```bash
cd /Users/admin/data/workspace/claude-skils/auto-pilot && python3 -c "
from src.state.manager import create_state, transition_state, record_phase_start, record_phase_end, get_state, delete_state
s = create_state('test/branch', 'TEST-1', '/tmp')
print('Initial state:', s['state'])
print('Has phases:', 'phases' in s)
record_phase_start('test/branch', 'analyzing', 'orchestrator:analyze')
record_phase_end('test/branch', 0, 'success')
transition_state('test/branch', 'planning')
s = get_state('test/branch')
print('After transition:', s['state'])
print('Phase count:', len(s['phases']))
print('Phase 1 result:', s['phases'][0]['result'])
delete_state('test/branch')
print('Cleanup done')
"
```

Expected:
```
Initial state: analyzing
Has phases: True
After transition: planning
Phase count: 1
Phase 1 result: success
Cleanup done
```

- [ ] **Step 6: Commit**

```bash
git add src/state/manager.py
git commit -m "feat: update state machine with new states, tracking, and failed state"
```

---

### Task 3: Issue Tracker Base — Add Abstract Methods

**Files:**
- Modify: `src/providers/base.py:21-55`

- [ ] **Step 1: Add abstract methods to IssueTrackerBase**

Add two new abstract methods after the existing `parse_webhook` method in the `IssueTrackerBase` class (after line 55):

```python
    @abstractmethod
    def transition_issue(self, issue_key: str, status_name: str) -> None:
        """Transition an issue to a new status.

        Looks up the transition ID matching status_name and applies it.

        Args:
            issue_key: Issue identifier (e.g. "PROJ-123").
            status_name: Target status name (e.g. "Development", "Done").

        Raises:
            Exception: If the transition fails or status_name is not found.
        """
        ...

    @abstractmethod
    def add_comment(self, issue_key: str, body: str) -> None:
        """Add a comment to an issue.

        Args:
            issue_key: Issue identifier (e.g. "PROJ-123").
            body: Comment text body.

        Raises:
            Exception: If the API call fails.
        """
        ...
```

- [ ] **Step 2: Commit**

```bash
git add src/providers/base.py
git commit -m "feat: add transition_issue and add_comment to IssueTrackerBase"
```

---

### Task 4: Jira Adapter — Implement `transition_issue` and `add_comment`

**Files:**
- Modify: `src/providers/trackers/jira.py`

- [ ] **Step 1: Add imports and Jira API methods**

Replace the entire file with:

```python
"""Jira issue tracker adapter.

Handles incoming Jira webhooks by detecting status transitions on issues.
Also provides methods for transitioning issues and adding comments via
the Jira REST API, used by the pipeline runner for status updates.

The module exposes a singleton ``adapter`` instance at module level for
use by the issue tracker factory.
"""

import logging
import os

import requests

from src.providers.base import IssueTrackerBase

logger = logging.getLogger(__name__)


class JiraAdapter(IssueTrackerBase):
    """Adapter that parses Jira webhook payloads and calls Jira REST API.

    Webhook parsing looks for changelog entries where the ``status`` field
    changed to the configured trigger status. API methods use JIRA_BASE_URL
    and JIRA_TOKEN from environment variables.
    """

    name = "jira"
    event_label = "ticket"

    def _api_headers(self):
        """Build authorization headers for Jira REST API calls."""
        token = os.environ.get("JIRA_TOKEN", "")
        email = os.environ.get("JIRA_EMAIL", "")
        if email:
            import base64
            creds = base64.b64encode(f"{email}:{token}".encode()).decode()
            return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _base_url(self):
        """Get the Jira base URL from environment."""
        return os.environ.get("JIRA_BASE_URL", "https://jira.atlassian.com").rstrip("/")

    def parse_webhook(self, headers, payload, config):
        """Parse a Jira webhook payload for a matching status transition.

        Args:
            headers: HTTP request headers from the incoming webhook.
            payload: The JSON body of the Jira webhook event.
            config: The ``issue_tracker`` section from config.yaml, must
                contain a ``trigger_status`` key with the target status name.

        Returns:
            dict or None: A dict with keys ``issue_key`` (str), ``summary``
                (str), and ``component`` (str or None) if the webhook
                represents a status change to the trigger status. Returns
                None if the event should be ignored.
        """
        changelog = payload.get("changelog", {})
        items = changelog.get("items", [])
        if not items:
            return None

        status_change = next((i for i in items if i.get("field") == "status"), None)
        if not status_change:
            return None

        new_status = status_change.get("toString", "")
        if new_status != config["trigger_status"]:
            return None

        issue = payload.get("issue", {})
        issue_key = issue.get("key")
        if not issue_key:
            return None

        fields = issue.get("fields", {})
        components = fields.get("components", [])
        return {
            "issue_key": issue_key,
            "summary": fields.get("summary", ""),
            "component": components[0]["name"] if components else None,
        }

    def transition_issue(self, issue_key: str, status_name: str) -> None:
        """Transition a Jira issue to a new status.

        Fetches available transitions, finds the one matching status_name,
        and applies it via POST.

        Args:
            issue_key: Jira issue key (e.g. "EV-14942").
            status_name: Target status name (e.g. "Development").
        """
        base = self._base_url()
        headers = self._api_headers()

        # Get available transitions
        resp = requests.get(f"{base}/rest/api/3/issue/{issue_key}/transitions", headers=headers)
        resp.raise_for_status()
        transitions = resp.json().get("transitions", [])

        # Find matching transition
        match = next((t for t in transitions if t["name"] == status_name), None)
        if not match:
            available = [t["name"] for t in transitions]
            raise ValueError(f"No transition to '{status_name}' for {issue_key}. Available: {available}")

        # Apply transition
        resp = requests.post(
            f"{base}/rest/api/3/issue/{issue_key}/transitions",
            headers=headers,
            json={"transition": {"id": match["id"]}},
        )
        resp.raise_for_status()
        logger.info(f"Transitioned {issue_key} to '{status_name}'")

    def add_comment(self, issue_key: str, body: str) -> None:
        """Add a comment to a Jira issue.

        Args:
            issue_key: Jira issue key (e.g. "EV-14942").
            body: Comment text.
        """
        base = self._base_url()
        headers = self._api_headers()

        resp = requests.post(
            f"{base}/rest/api/3/issue/{issue_key}/comment",
            headers=headers,
            json={"body": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": body}]}
            ]}},
        )
        resp.raise_for_status()
        logger.info(f"Posted comment on {issue_key}")


adapter = JiraAdapter()
```

- [ ] **Step 2: Commit**

```bash
git add src/providers/trackers/jira.py
git commit -m "feat: add transition_issue and add_comment to Jira adapter"
```

---

### Task 5: GitHub Issues Adapter — Implement `transition_issue` and `add_comment`

**Files:**
- Modify: `src/providers/trackers/github_issues.py`

- [ ] **Step 1: Add GitHub API methods**

Replace the entire file with:

```python
"""GitHub Issues issue tracker adapter.

Handles incoming GitHub webhook events by detecting when a specific label is
applied to an issue. Also provides methods for managing issue labels and
adding comments via the GitHub API, used by the pipeline runner.

The module exposes a singleton ``adapter`` instance at module level for
use by the issue tracker factory.
"""

import logging
import os

import requests

from src.providers.base import IssueTrackerBase

logger = logging.getLogger(__name__)


class GitHubIssuesAdapter(IssueTrackerBase):
    """Adapter that parses GitHub Issues webhook payloads and calls GitHub API.

    Webhook parsing listens for ``issues`` events with ``labeled`` action.
    API methods use GITHUB_TOKEN from environment variables.
    """

    name = "github-issues"
    event_label = "issue"

    def _api_headers(self):
        """Build authorization headers for GitHub API calls."""
        token = os.environ.get("GITHUB_TOKEN", "")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _parse_issue_key(self, issue_key: str):
        """Parse 'repo#123' into (repo, number)."""
        repo, number = issue_key.split("#")
        owner = os.environ.get("GITHUB_OWNER", "")
        return f"{owner}/{repo}", int(number)

    def parse_webhook(self, headers, payload, config):
        """Parse a GitHub Issues webhook payload for a matching label event.

        Args:
            headers: HTTP request headers. Must contain ``x-github-event``
                to identify the event type.
            payload: The JSON body of the GitHub webhook event.
            config: The ``issue_tracker`` section from config.yaml, must
                contain a ``trigger_status`` key with the target label name.

        Returns:
            dict or None: A dict with keys ``issue_key`` (str, formatted as
                ``repo#number``), ``summary`` (str), and ``component``
                (always None for GitHub Issues) if the webhook represents
                the trigger label being applied. Returns None otherwise.
        """
        event = headers.get("x-github-event")
        if event != "issues":
            return None

        if payload.get("action") != "labeled":
            return None

        label_name = payload.get("label", {}).get("name")
        if label_name != config["trigger_status"]:
            return None

        issue = payload.get("issue", {})
        repo_name = payload.get("repository", {}).get("name", "")
        return {
            "issue_key": f"{repo_name}#{issue.get('number', '')}",
            "summary": issue.get("title", ""),
            "component": None,
        }

    def transition_issue(self, issue_key: str, status_name: str) -> None:
        """Transition a GitHub issue by adding/removing labels.

        For GitHub Issues, "status" is represented by labels. This method
        adds the target label. It does not remove previous status labels.

        Args:
            issue_key: Issue key in "repo#123" format.
            status_name: Label name to add (e.g. "in-progress", "done").
        """
        repo_full, number = self._parse_issue_key(issue_key)
        headers = self._api_headers()
        resp = requests.post(
            f"https://api.github.com/repos/{repo_full}/issues/{number}/labels",
            headers=headers,
            json={"labels": [status_name]},
        )
        resp.raise_for_status()
        logger.info(f"Added label '{status_name}' to {issue_key}")

    def add_comment(self, issue_key: str, body: str) -> None:
        """Add a comment to a GitHub issue.

        Args:
            issue_key: Issue key in "repo#123" format.
            body: Comment text (Markdown supported).
        """
        repo_full, number = self._parse_issue_key(issue_key)
        headers = self._api_headers()
        resp = requests.post(
            f"https://api.github.com/repos/{repo_full}/issues/{number}/comments",
            headers=headers,
            json={"body": body},
        )
        resp.raise_for_status()
        logger.info(f"Posted comment on {issue_key}")


adapter = GitHubIssuesAdapter()
```

- [ ] **Step 2: Commit**

```bash
git add src/providers/trackers/github_issues.py
git commit -m "feat: add transition_issue and add_comment to GitHub Issues adapter"
```

---

### Task 6: Pipeline Runner — `src/executor/pipeline.py`

**Files:**
- Create: `src/executor/pipeline.py`

- [ ] **Step 1: Create the pipeline module**

Create `src/executor/pipeline.py` with the full phase runner implementation:

```python
"""
Pipeline phase runner.

Drives the ticket lifecycle phase-by-phase: analyze -> plan -> implement -> review.
Each phase invokes an agent, checks the result, and transitions state.
Jira/Slack calls are best-effort (logged on failure, never block the pipeline).

Usage:
    from src.executor.pipeline import run_pipeline_phases, run_rework_phases

    # Called from route handlers in a background thread:
    threading.Thread(target=run_pipeline_phases, args=(...), daemon=True).start()
"""

import json
import logging
import re

from src.config import config
from src.executor.runner import run_agent
from src.state.manager import (
    get_state,
    transition_state,
    record_phase_start,
    record_phase_end,
    update_artifacts,
)
from src.providers.issue_tracker import get_issue_tracker
from src.providers.notification import get_notification

logger = logging.getLogger(__name__)

# Marker that agents write to stdout to communicate structured results.
RESULT_MARKER = "__PIPELINE_RESULT__:"


def _extract_pipeline_result(agent_output: str) -> dict | None:
    """Extract the __PIPELINE_RESULT__ JSON from agent stdout.

    Scans agent output for a line starting with the result marker,
    parses the JSON payload, and returns it.

    Args:
        agent_output: Full stdout from the agent process.

    Returns:
        Parsed dict (e.g. {"blocked": false}) or None if no marker found.
    """
    for line in agent_output.split("\n"):
        line = line.strip()
        if line.startswith(RESULT_MARKER):
            try:
                return json.loads(line[len(RESULT_MARKER):])
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse pipeline result: {line}")
    return None


def _is_blocked(result: dict) -> bool:
    """Check if the agent result indicates a blocked ticket."""
    pipeline_result = _extract_pipeline_result(result.get("output", ""))
    if pipeline_result and pipeline_result.get("blocked"):
        return True
    return False


def _extract_blocked_reason(result: dict) -> str:
    """Extract the blocked reason from agent output."""
    pipeline_result = _extract_pipeline_result(result.get("output", ""))
    if pipeline_result:
        return pipeline_result.get("reason", "No reason provided")
    return "Unknown reason"


def _try_transition_jira(issue_key: str, status_name: str) -> None:
    """Transition Jira status (best-effort — logs and continues on failure)."""
    try:
        adapter, _ = get_issue_tracker()
        adapter.transition_issue(issue_key, status_name)
    except Exception as e:
        logger.warning(f"Failed to transition Jira {issue_key} to '{status_name}': {e}")


def _try_add_jira_comment(issue_key: str, body: str) -> None:
    """Post a Jira comment (best-effort — logs and continues on failure)."""
    try:
        adapter, _ = get_issue_tracker()
        adapter.add_comment(issue_key, body)
    except Exception as e:
        logger.warning(f"Failed to post Jira comment on {issue_key}: {e}")


def _try_notify_slack(message: str) -> None:
    """Send a Slack notification (best-effort — logs and continues on failure)."""
    try:
        result = get_notification()
        if result:
            adapter, notif_config = result
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                loop.create_task(adapter.send(message, notif_config))
            else:
                asyncio.run(adapter.send(message, notif_config))
    except Exception as e:
        logger.warning(f"Failed to send Slack notification: {e}")


def _handle_agent_failure(issue_key: str, branch: str, agent_name: str, result: dict, statuses: dict) -> None:
    """Handle a non-zero agent exit by transitioning to failed state."""
    error_msg = result.get("error", "unknown error")
    logger.error(f"Agent {agent_name} failed for {issue_key}: {error_msg}")

    current = get_state(branch)
    current_phase = current["state"] if current else "unknown"

    transition_state(branch, "failed", error={
        "phase": current_phase,
        "agent": agent_name,
        "message": error_msg,
    })

    _try_add_jira_comment(issue_key,
        f"Pipeline failed during {agent_name}.\n\nError: {error_msg}\n\nCheck logs for details.")
    _try_notify_slack(f"{issue_key} pipeline failed during {agent_name} — check logs")


def _handle_blocked(issue_key: str, branch: str, statuses: dict, result: dict) -> None:
    """Handle an agent reporting the ticket is blocked."""
    reason = _extract_blocked_reason(result)
    logger.info(f"Pipeline blocked for {issue_key}: {reason}")

    _try_add_jira_comment(issue_key,
        f"Pipeline blocked — additional information needed:\n\n{reason}")
    _try_transition_jira(issue_key, statuses["blocked"])
    _try_notify_slack(f"{issue_key} blocked — {reason}")


def _run_phase(issue_key: str, branch: str, agent_name: str, phase_label: str,
               input_data: str, statuses: dict, repo_dir: str) -> dict | None:
    """Run a single pipeline phase with full tracking and error handling.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name.
        agent_name: Agent to invoke (e.g. "orchestrator").
        phase_label: Label for tracking (e.g. "orchestrator:analyze").
        input_data: JSON string input for the agent.
        statuses: Dict of Jira status names.
        repo_dir: Working directory for the agent.

    Returns:
        Agent result dict on success, or None if the phase failed/blocked
        (error handling already done internally).
    """
    record_phase_start(branch, get_state(branch)["state"], phase_label)

    try:
        result = run_agent(agent_name, input_data, cwd=repo_dir, issue_key=issue_key)
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, phase_label,
            {"success": False, "error": str(e)}, statuses)
        return None

    if not result.get("success"):
        record_phase_end(branch, result.get("exit_code", -1), "failed")
        _handle_agent_failure(issue_key, branch, phase_label, result, statuses)
        return None

    if _is_blocked(result):
        record_phase_end(branch, 0, "blocked")
        _handle_blocked(issue_key, branch, statuses, result)
        return None

    record_phase_end(branch, 0, "success")
    return result


def run_pipeline_phases(issue_key: str, branch: str, summary: str,
                        project_key: str, base_branch: str,
                        statuses: dict, repo_dir: str) -> None:
    """Drive the full pipeline: analyze -> plan -> implement -> awaiting-review.

    Runs synchronously in a background thread. Each phase invokes an agent,
    checks the result, transitions state, and posts Jira comments.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name (e.g. "ev-14942_fix_xss").
        summary: Ticket summary text.
        project_key: Project key (e.g. "EV").
        base_branch: Base branch to create feature branch from (e.g. "main").
        statuses: Dict with keys: trigger, development, done, blocked.
        repo_dir: Absolute path to the target repo directory.
    """
    logger.info(f"--- Pipeline started for {issue_key} (branch: {branch}) ---")

    # Step 1: Transition Jira to Development status
    _try_transition_jira(issue_key, statuses["development"])

    # Step 2: Analyze phase
    analyze_input = json.dumps({
        "action": "analyze",
        "issueKey": issue_key,
        "branch": branch,
        "summary": summary,
        "projectKey": project_key,
        "baseBranch": base_branch,
        "statuses": statuses,
    })
    result = _run_phase(issue_key, branch, "orchestrator", "orchestrator:analyze",
                        analyze_input, statuses, repo_dir)
    if result is None:
        return

    # Step 3: Plan phase
    transition_state(branch, "planning")
    plan_input = json.dumps({
        "action": "plan",
        "issueKey": issue_key,
        "branch": branch,
        "statuses": statuses,
    })
    result = _run_phase(issue_key, branch, "orchestrator", "orchestrator:plan",
                        plan_input, statuses, repo_dir)
    if result is None:
        return

    # Step 4: Implement phase
    transition_state(branch, "developing")
    implement_input = json.dumps({
        "action": "implement",
        "issueKey": issue_key,
        "branch": branch,
        "summary": summary,
        "baseBranch": base_branch,
        "statuses": statuses,
    })
    result = _run_phase(issue_key, branch, "orchestrator", "orchestrator:implement",
                        implement_input, statuses, repo_dir)
    if result is None:
        return

    # Step 5: Transition to awaiting-review, update Jira to Done
    transition_state(branch, "awaiting-review")
    _try_transition_jira(issue_key, statuses["done"])
    _try_add_jira_comment(issue_key, f"Implementation completed for {issue_key}. Awaiting review.")
    _try_notify_slack(f"MR created for {issue_key}")

    logger.info(f"--- Pipeline completed for {issue_key} ---")


def run_rework_phases(issue_key: str, branch: str, pr_id: str,
                      statuses: dict, repo_dir: str) -> None:
    """Drive the rework loop: parse feedback -> apply fixes -> awaiting-review.

    Runs synchronously in a background thread.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name.
        pr_id: PR/MR identifier.
        statuses: Dict with keys: trigger, development, done, blocked.
        repo_dir: Absolute path to the target repo directory.
    """
    logger.info(f"--- Rework started for {issue_key} ---")

    # Transition Jira to Development
    _try_transition_jira(issue_key, statuses["development"])
    transition_state(branch, "reworking")

    # Step 1: Parse feedback
    record_phase_start(branch, "reworking", "feedback-parser")
    try:
        feedback_input = json.dumps({
            "issueKey": issue_key,
            "branch": branch,
            "prId": pr_id,
        })
        feedback_result = run_agent("feedback-parser", feedback_input, cwd=repo_dir, issue_key=issue_key)
        if not feedback_result.get("success"):
            record_phase_end(branch, feedback_result.get("exit_code", -1), "failed")
            _handle_agent_failure(issue_key, branch, "feedback-parser", feedback_result, statuses)
            return
        record_phase_end(branch, 0, "success")
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, "feedback-parser",
            {"success": False, "error": str(e)}, statuses)
        return

    # Step 2: Apply rework
    record_phase_start(branch, "reworking", "orchestrator:rework")
    try:
        rework_input = json.dumps({
            "action": "rework",
            "issueKey": issue_key,
            "branch": branch,
            "statuses": statuses,
        })
        rework_result = run_agent("orchestrator", rework_input, cwd=repo_dir, issue_key=issue_key)
        if not rework_result.get("success"):
            record_phase_end(branch, rework_result.get("exit_code", -1), "failed")
            _handle_agent_failure(issue_key, branch, "orchestrator:rework", rework_result, statuses)
            return
        record_phase_end(branch, 0, "success")
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, "orchestrator:rework",
            {"success": False, "error": str(e)}, statuses)
        return

    # Step 3: Back to awaiting-review
    transition_state(branch, "awaiting-review")
    _try_transition_jira(issue_key, statuses["done"])
    _try_add_jira_comment(issue_key, f"Rework completed for {issue_key}. Awaiting re-review.")
    _try_notify_slack(f"Rework completed for {issue_key}")

    logger.info(f"--- Rework completed for {issue_key} ---")
```

- [ ] **Step 2: Commit**

```bash
git add src/executor/pipeline.py
git commit -m "feat: add pipeline phase runner with tracking and error handling"
```

---

### Task 7: Route Changes — Issue Tracker Webhook

**Files:**
- Modify: `src/routes/issue_tracker.py`

- [ ] **Step 1: Update imports, branch naming, and pipeline call**

Replace the entire file with:

```python
"""Issue tracker webhook route.

Provides a ``POST /webhooks/issue-tracker`` endpoint that receives webhook
payloads from the configured issue tracker (Jira or GitHub Issues). When a
matching event is detected (e.g. a ticket status change to "Ready for
Development"), the handler creates a feature branch name, initializes
pipeline state, and launches the pipeline phases in a background thread.

Mount this router under ``/webhooks/issue-tracker`` in the FastAPI app.
"""

import json
import logging
import re
import threading

from fastapi import APIRouter, Request

from src.config import config as app_config
from src.state.manager import get_state, create_state
from src.executor.pipeline import run_pipeline_phases
from src.repos.resolver import get_repo_dir, prepare_repo, get_base_branch
from src.providers.issue_tracker import get_issue_tracker

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/")
async def handle_webhook(request: Request):
    """Handle an incoming issue tracker webhook.

    Delegates payload parsing to the configured adapter. If the event matches
    the trigger criteria, creates pipeline state and launches the pipeline
    phases in a background thread.

    Args:
        request: The incoming FastAPI request containing webhook headers
            and JSON body.

    Returns:
        dict: ``{"accepted": True, ...}`` if a pipeline was started,
            ``{"ignored": True}`` if the event was filtered out or a
            pipeline is already active for the branch.
    """
    adapter, tracker_config = get_issue_tracker()
    payload = await request.json()
    headers = dict(request.headers)

    parsed = adapter.parse_webhook(headers, payload, tracker_config)
    if not parsed:
        return {"ignored": True}

    issue_key = parsed["issue_key"]
    summary = parsed["summary"]
    component = parsed.get("component")

    slug = re.sub(r"[^a-z0-9\s_]", "", summary.lower())
    slug = re.sub(r"\s+", "_", slug)[:40].rstrip("_")
    branch = f"{issue_key.lower()}_{slug}"

    if get_state(branch):
        logger.warning(f"Pipeline already active for {branch}")
        return {"ignored": True, "reason": "already active"}

    repo_dir = get_repo_dir(component)
    logger.info(f"Processing {adapter.event_label}: {issue_key}", extra={"branch": branch, "repo_dir": repo_dir})

    prepare_repo(repo_dir)
    create_state(branch, issue_key, repo_path=repo_dir)

    base_branch = get_base_branch()
    tracker_cfg = app_config["issue_tracker"]
    statuses = {
        "trigger": tracker_cfg["trigger_status"],
        "development": tracker_cfg["development_status"],
        "done": tracker_cfg["done_status"],
        "blocked": tracker_cfg["blocked_status"],
    }

    threading.Thread(
        target=run_pipeline_phases,
        args=(issue_key, branch, summary, issue_key.split("-")[0], base_branch, statuses, repo_dir),
        daemon=True,
    ).start()

    return {"accepted": True, "issueKey": issue_key, "branch": branch, "repoDir": repo_dir}
```

- [ ] **Step 2: Commit**

```bash
git add src/routes/issue_tracker.py
git commit -m "feat: update issue tracker route for phase-based pipeline"
```

---

### Task 8: Route Changes — Manual Trigger

**Files:**
- Modify: `src/routes/trigger.py`

- [ ] **Step 1: Update imports, branch naming, and pipeline call**

Replace the entire file with:

```python
"""Manual pipeline trigger route.

Provides a ``POST /api/trigger`` endpoint that allows manually starting the
pipeline for a given issue key without waiting for a webhook event. Useful
for testing, retries, or triggering work on issues that have already
transitioned past the webhook trigger status.

Mount this router under ``/api/trigger`` in the FastAPI app.

Example request::

    POST /api/trigger
    {"issueKey": "PROJ-123", "summary": "Add login page", "component": "frontend"}
"""

import json
import logging
import re
import threading

from fastapi import APIRouter
from pydantic import BaseModel

from src.config import config as app_config
from src.state.manager import get_state, create_state
from src.executor.pipeline import run_pipeline_phases
from src.repos.resolver import get_repo_dir, prepare_repo, get_base_branch

logger = logging.getLogger(__name__)
router = APIRouter()


class TriggerRequest(BaseModel):
    """Request body for the manual pipeline trigger endpoint.

    Attributes:
        issueKey: The issue tracker key (e.g. ``"PROJ-123"`` or
            ``"myrepo#42"``). Required.
        summary: Human-readable summary of the issue. Defaults to the
            issue key if not provided.
        component: Optional component name used to resolve which
            repository to target in multi-repo setups.
    """

    issueKey: str
    summary: str | None = None
    component: str | None = None


@router.post("/")
async def manual_trigger(body: TriggerRequest):
    """Manually trigger the pipeline for an issue.

    Creates a feature branch name from the issue key and summary, initializes
    pipeline state, and launches the pipeline phases in a background thread.

    Args:
        body: The trigger request containing the issue key and optional
            summary and component.

    Returns:
        dict: ``{"accepted": True, ...}`` with the issue key, branch name,
            and repo directory if a pipeline was started. Returns an error
            dict if a pipeline is already active for the computed branch.
    """
    issue_key = body.issueKey
    summary = body.summary or issue_key
    component = body.component

    slug = re.sub(r"[^a-z0-9\s_]", "", summary.lower())
    slug = re.sub(r"\s+", "_", slug)[:40].rstrip("_")
    branch = f"{issue_key.lower()}_{slug}"

    if get_state(branch):
        return {"error": "Pipeline already active for this ticket", "branch": branch}

    repo_dir = get_repo_dir(component)
    logger.info(f"Manual trigger: {issue_key}", extra={"branch": branch, "repo_dir": repo_dir})

    prepare_repo(repo_dir)
    create_state(branch, issue_key, repo_path=repo_dir)

    base_branch = get_base_branch()
    tracker_cfg = app_config["issue_tracker"]
    statuses = {
        "trigger": tracker_cfg["trigger_status"],
        "development": tracker_cfg["development_status"],
        "done": tracker_cfg["done_status"],
        "blocked": tracker_cfg["blocked_status"],
    }

    threading.Thread(
        target=run_pipeline_phases,
        args=(issue_key, branch, summary, issue_key.split("-")[0], base_branch, statuses, repo_dir),
        daemon=True,
    ).start()

    return {"accepted": True, "issueKey": issue_key, "branch": branch, "repoDir": repo_dir}
```

- [ ] **Step 2: Commit**

```bash
git add src/routes/trigger.py
git commit -m "feat: update trigger route for phase-based pipeline"
```

---

### Task 9: Route Changes — Git Provider Webhook (Rework Path)

**Files:**
- Modify: `src/routes/git_provider.py`

- [ ] **Step 1: Update imports and rework flow**

Replace the entire file with:

```python
"""Git provider webhook route.

Provides a ``POST /webhooks/git`` endpoint that receives webhook payloads
from the configured git provider (GitLab or GitHub). Handles three event
types:

- **approved** -- Marks the pipeline as merged and triggers post-merge actions.
- **push** -- Logs human pushes on tracked branches.
- **comment** -- Triggers the rework pipeline when a review comment
  arrives on a PR that is awaiting review, subject to rework limits.

Mount this router under ``/webhooks/git`` in the FastAPI app.
"""

import json
import logging
import threading

from fastapi import APIRouter, Request

from src.config import config
from src.state.manager import get_state, transition_state, is_rework_limit_exceeded, list_active_states
from src.executor.runner import run_agent
from src.executor.pipeline import run_rework_phases
from src.providers.git_provider import get_git_provider

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_statuses():
    """Build the statuses dict from config."""
    tracker_cfg = config["issue_tracker"]
    return {
        "trigger": tracker_cfg["trigger_status"],
        "development": tracker_cfg["development_status"],
        "done": tracker_cfg["done_status"],
        "blocked": tracker_cfg["blocked_status"],
    }


@router.post("/")
async def handle_webhook(request: Request):
    """Handle an incoming git provider webhook.

    Delegates payload parsing to the configured adapter, then dispatches
    based on the event type: transitions state on approval, logs pushes,
    and triggers the rework pipeline on review comments (respecting the
    configured rework iteration limit).

    Args:
        request: The incoming FastAPI request containing webhook headers
            and JSON body.

    Returns:
        dict: ``{"received": True}`` for processed events, or
            ``{"ignored": True}`` if the event was filtered out by the
            adapter.
    """
    adapter, git_config = get_git_provider()
    payload = await request.json()
    headers = dict(request.headers)

    parsed = adapter.parse_webhook(headers, payload, git_config)
    if not parsed:
        return {"ignored": True}

    event = parsed["event"]
    branch = parsed.get("branch")
    pr_id = parsed.get("pr_id")
    author = parsed.get("author")

    if event == "approved":
        state = get_state(branch)
        if not state:
            return {"received": True}
        logger.info(f"PR approved for {state['issueKey']} ({branch})")
        transition_state(branch, "merged")
        statuses = _get_statuses()

        def _run_merge():
            run_agent("orchestrator", json.dumps({
                "action": "merge-approved",
                "issueKey": state["issueKey"],
                "branch": branch,
                "prId": pr_id,
                "statuses": statuses,
            }), cwd=state.get("repoPath", "."), issue_key=state["issueKey"])

        threading.Thread(target=_run_merge, daemon=True).start()

    elif event == "push":
        state = get_state(branch)
        if state:
            logger.info(f"Human push on {branch} by {author}")

    elif event == "comment":
        resolved_branch = branch
        if not resolved_branch:
            match = next((s for s in list_active_states() if s.get("prId") == pr_id), None)
            if match:
                resolved_branch = match["branch"]
        if not resolved_branch:
            return {"received": True}

        state = get_state(resolved_branch)
        if not state or state["state"] != "awaiting-review":
            return {"received": True}

        max_rework = config["pipeline"]["max_rework_iterations"]
        if is_rework_limit_exceeded(resolved_branch, max_rework):
            logger.warning(f"Rework limit exceeded for {state['issueKey']}")
            statuses = _get_statuses()

            def _run_escalation():
                run_agent("orchestrator", json.dumps({
                    "action": "rework-limit-exceeded",
                    "issueKey": state["issueKey"],
                    "branch": resolved_branch,
                    "reworkCount": state.get("reworkCount", 0),
                    "statuses": statuses,
                }), cwd=state.get("repoPath", "."), issue_key=state["issueKey"])

            threading.Thread(target=_run_escalation, daemon=True).start()
            return {"received": True}

        logger.info(f"Review comment for {state['issueKey']}, starting rework pipeline")
        statuses = _get_statuses()
        threading.Thread(
            target=run_rework_phases,
            args=(state["issueKey"], resolved_branch, pr_id, statuses, state.get("repoPath", ".")),
            daemon=True,
        ).start()

    return {"received": True}
```

- [ ] **Step 2: Commit**

```bash
git add src/routes/git_provider.py
git commit -m "feat: update git provider route to use rework pipeline phases"
```

---

### Task 10: Orchestrator Agent — Split Into Focused Actions

**Files:**
- Modify: `agents/orchestrator.md`

- [ ] **Step 1: Rewrite the orchestrator agent**

Replace the entire `agents/orchestrator.md` file with the new action-based version. This is the agent prompt — it tells the AI what to do per action.

```markdown
# Orchestrator Agent

> **CRITICAL — READ THIS FIRST:**
> You are a FULLY AUTOMATED agent. There is NO human reading your output. Nobody will answer your questions. NEVER write questions in your output. NEVER say "before I proceed" or "should I" or "is that correct". NEVER ask for confirmation. If you write a question, the pipeline dies. Just DO the work silently. Execute every step. Make every decision yourself. Output actions and results only — never questions.

You are the orchestrator for an AI-powered development pipeline. Your role is to execute one specific action per invocation, as directed by the `action` field in your input JSON.

**You run in STRICT NO-INTERACTION MODE. Never ask questions, never wait for input, never use interactive tools. Make decisions and proceed. If something fails, log it and continue. See RULES.md for the full autonomy policy.**

## Result Protocol

At the END of every action, you MUST output exactly one result line in this format:

```
__PIPELINE_RESULT__:{"blocked":false}
```

Or if the ticket lacks sufficient information to proceed:

```
__PIPELINE_RESULT__:{"blocked":true,"reason":"<explanation of what information is missing>"}
```

This line MUST appear in your output. The pipeline server reads it to determine next steps. If you do not output this line, the pipeline cannot advance.

## Input

You receive a JSON input with an `action` field and action-specific fields.

---

### Action: analyze

Fields: `issueKey`, `branch`, `summary`, `projectKey`, `baseBranch`, `statuses`

**Steps:**
1. Read the full ticket using the issue tracker MCP with **ALL fields**:
   - Use `getJiraIssue` with all fields (summary, description, status, priority, labels, components, attachments, comments, linked issues, AND all custom fields)
   - Fetch attachments list — if there are design mockups or spec documents, note them in TICKET.md
   - Read existing comments on the ticket for additional context
   - Check linked issues and pull their summaries for context
2. **Evaluate if the ticket has sufficient detail** (see RULES.md "Insufficient Ticket Details" section):
   - If insufficient: post a comment on the ticket explaining what's missing, then output `__PIPELINE_RESULT__:{"blocked":true,"reason":"<what is missing>"}` and **STOP**
   - If sufficient: continue to step 3
3. Create the feature branch from `baseBranch` using the git provider MCP (`create_branch`)
4. Write `TICKET.md` to the branch root with the full ticket context:
   - Issue key and summary
   - Full description (from description field AND any relevant custom fields)
   - Acceptance criteria (from any field where they appear)
   - Attachments list with descriptions
   - Linked issues with summaries (if any)
   - Design notes (if any)
5. Commit `TICKET.md` to the feature branch using the git provider MCP (`commit_files`)
6. Post a Jira comment with the analysis summary:
   - Scope of the ticket as understood
   - Key requirements identified
   - Relevant existing files/patterns found in codebase
7. Output `__PIPELINE_RESULT__:{"blocked":false}`

### Action: plan

Fields: `issueKey`, `branch`, `statuses`

**Steps:**
1. Invoke the **brainstorm** agent with the issue key and branch name
2. After the brainstorm agent completes, read `PLAN.md` from the branch root
3. If the plan reveals fundamental blockers (e.g. required external service not available, massive scope that needs decomposition): output `__PIPELINE_RESULT__:{"blocked":true,"reason":"<details>"}` and **STOP**
4. Post a Jira comment with the plan summary:
   - Chosen approach and why
   - File changes planned
   - Key implementation notes
5. Output `__PIPELINE_RESULT__:{"blocked":false}`

### Action: implement

Fields: `issueKey`, `branch`, `summary`, `baseBranch`, `statuses`

**Steps:**
1. Invoke the **developer** agent with `issueKey`, `branch`, and `mode: "first-pass"`
2. After the developer agent completes, verify commits were pushed to the feature branch
3. Create a pull/merge request via the git provider MCP:
   - Title: `feat({issueKey}): {summary}`
   - Description: include a summary of PLAN.md, link to the ticket, and the file change list
   - Target branch: use `baseBranch` from input
4. Post a comment on the ticket with the MR/PR link
5. Send a Slack notification to the configured channel: "MR created for {issueKey} — {MR link}"
6. Output `__PIPELINE_RESULT__:{"blocked":false}`

### Action: rework

Fields: `issueKey`, `branch`, `statuses`

**Steps:**
1. Read `FEEDBACK.md` from the branch root (written by the feedback-parser agent)
2. Invoke the **developer** agent with `issueKey`, `branch`, and `mode: "rework"`
3. After the developer agent completes, verify commits were pushed
4. Post a Jira comment: "Rework completed based on review feedback"
5. Output `__PIPELINE_RESULT__:{"blocked":false}`

### Action: merge-approved

Fields: `issueKey`, `branch`, `prId`, `statuses`

**Steps:**
1. Transition the ticket to the done status (use `statuses.done` from your input JSON to find the correct transition)
2. Send a Slack notification: "{issueKey} merged successfully"
3. Output `__PIPELINE_RESULT__:{"blocked":false}`

### Action: rework-limit-exceeded

Fields: `issueKey`, `branch`, `reworkCount`

**Steps:**
1. Send a Slack notification: "{issueKey} has exceeded the rework limit ({reworkCount} iterations) — human intervention needed"
2. Post a comment on the ticket noting the escalation
3. Output `__PIPELINE_RESULT__:{"blocked":false}`

## Rules
- Always follow the commit message format in the global rules
- Always follow the branch naming convention
- Never push directly to main or develop
- **STRICT: Never ask questions, never wait for input, never use interactive tools — you are fully autonomous**
- Always fetch ALL Jira fields (including custom fields and attachments) — never rely on description alone
- Block tickets with insufficient details rather than guessing wildly
- **All decisions are self-driven and auto-approved** — never present options and wait for selection. You choose the best path and execute it.
- **ALWAYS output a __PIPELINE_RESULT__ line at the end of every action** — the pipeline depends on it.

**If any step fails:** log the error, skip to the next step, and continue. Do not stop the pipeline. Still output the __PIPELINE_RESULT__ line at the end.
```

- [ ] **Step 2: Commit**

```bash
git add agents/orchestrator.md
git commit -m "feat: split orchestrator into analyze/plan/implement/rework actions"
```

---

### Task 11: RULES.md — Update State List

**Files:**
- Modify: `agents/RULES.md:102`

- [ ] **Step 1: Update the Pipeline State Machine section**

Find the line (around line 102):
```
States: `brainstorming` → `developing` → `awaiting-review` → `reworking` → `merged`
```

Replace with:
```
States: `analyzing` → `planning` → `developing` → `awaiting-review` → `reworking` → `merged` | `failed`
```

- [ ] **Step 2: Commit**

```bash
git add agents/RULES.md
git commit -m "feat: update RULES.md state list for new pipeline phases"
```

---

### Task 12: Dashboard CSS — New Badge Styles

**Files:**
- Modify: `dashboard-react/src/styles.css:47-51`

- [ ] **Step 1: Add badge styles for new states**

After the existing `.badge-brainstorming` line (line 47), add three new badge styles:

```css
.badge-analyzing     { background: #e0f2fe; color: #0369a1; }
.badge-planning      { background: #dbeafe; color: #1e40af; }
.badge-failed        { background: #fee2e2; color: #991b1b; }
```

Keep `.badge-brainstorming` for backward compatibility with any existing state files.

- [ ] **Step 2: Commit**

```bash
git add dashboard-react/src/styles.css
git commit -m "feat: add dashboard badge styles for analyzing, planning, and failed states"
```

---

### Task 13: Documentation Updates

**Files:**
- Modify: `docs/configuration.md`
- Modify: `docs/how-it-works.md`

- [ ] **Step 1: Update configuration.md**

In `docs/configuration.md`, find the `issueTracker` table (around line 87-93). Add a new row after `triggerStatus`:

```markdown
| `developmentStatus` | string | No | `Development` | Status to transition to when pipeline picks up a ticket |
```

And update the Jira example YAML block to include:
```yaml
issueTracker:
  type: jira
  triggerStatus: Ready for Development
  developmentStatus: Development
  doneStatus: Done
  blockedStatus: Blocked
```

- [ ] **Step 2: Update how-it-works.md**

In `docs/how-it-works.md`, update the Pipeline States section (around line 155-168).

Replace the state diagram:
```
brainstorming → developing → awaiting-review → merged
                                   ↓       ↑
                                reworking ──┘
```

With:
```
analyzing → planning → developing → awaiting-review → merged
    |           |          |              ↓       ↑
    +-----+-----+----------+          reworking ──┘
          |
        failed
```

Update the state table:

```markdown
| State | What's happening |
|-------|-----------------|
| `analyzing` | Orchestrator is reading ticket, writing TICKET.md, posting analysis |
| `planning` | Brainstorm agent is writing PLAN.md, posting plan summary |
| `developing` | Developer agent is implementing code |
| `awaiting-review` | PR/MR is open, waiting for human |
| `reworking` | Developer is applying review feedback |
| `merged` | PR approved, ticket closed |
| `failed` | Pipeline encountered an unrecoverable error |
```

- [ ] **Step 3: Commit**

```bash
git add docs/configuration.md docs/how-it-works.md
git commit -m "docs: update configuration and how-it-works for phase-based pipeline"
```

---

### Task 14: Verify Full Import Chain

- [ ] **Step 1: Verify all imports resolve**

Run:
```bash
cd /Users/admin/data/workspace/claude-skils/auto-pilot && python3 -c "
from src.config import config
from src.state.manager import create_state, transition_state, record_phase_start, record_phase_end, update_artifacts, get_state, delete_state
from src.executor.pipeline import run_pipeline_phases, run_rework_phases
from src.routes import issue_tracker, trigger, git_provider, status
print('All imports OK')
print('Config development_status:', config['issue_tracker']['development_status'])
"
```

Expected:
```
All imports OK
Config development_status: Development
```

- [ ] **Step 2: Quick state machine round-trip**

Run:
```bash
cd /Users/admin/data/workspace/claude-skils/auto-pilot && python3 -c "
from src.state.manager import *
s = create_state('test/verify', 'TEST-99', '/tmp')
assert s['state'] == 'analyzing'
assert s['phases'] == []
assert s['error'] is None

record_phase_start('test/verify', 'analyzing', 'orchestrator:analyze')
record_phase_end('test/verify', 0, 'success')
transition_state('test/verify', 'planning')
record_phase_start('test/verify', 'planning', 'orchestrator:plan')
record_phase_end('test/verify', 0, 'success')
transition_state('test/verify', 'developing')
transition_state('test/verify', 'awaiting-review')
s = get_state('test/verify')
assert s['state'] == 'awaiting-review'
assert len(s['phases']) == 2

# Test failed transition
create_state('test/fail', 'TEST-F', '/tmp')
transition_state('test/fail', 'failed', error={'phase': 'analyzing', 'agent': 'test', 'message': 'boom'})
s = get_state('test/fail')
assert s['state'] == 'failed'
assert s['error']['message'] == 'boom'

delete_state('test/verify')
delete_state('test/fail')
print('All state machine assertions passed')
"
```

Expected: `All state machine assertions passed`

- [ ] **Step 3: Commit (no code changes — verification only)**

No commit needed — this is just a verification step.
