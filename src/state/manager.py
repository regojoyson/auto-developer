"""
Pipeline state machine.

Tracks each ticket's lifecycle as a JSON file per branch inside
`.pipeline-state/`. Every agent invocation checks state before starting
to prevent duplicate processing.

State flow:
    (new) → analyzing → planning → developing → awaiting-review → merged
                |           |          |              ↓       ↑
                +-----+-----+----------+           reworking ──┘
                      |
                    failed

Usage:
    from src.state.manager import create_state, get_state, transition_state

    create_state("ev-14942_fix_xss", "EV-14942", "/projects/my-app")
    transition_state("ev-14942_fix_xss", "planning")
    state = get_state("ev-14942_fix_xss")
    print(state["state"])  # "planning"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent.parent / ".pipeline-state"

# Defines which state transitions are allowed.
# Key = current state, Value = list of states it can transition to.
VALID_TRANSITIONS = {
    "analyzing": ["planning", "failed"],
    "planning": ["developing", "failed"],
    "developing": ["awaiting-review", "failed"],
    "awaiting-review": ["reworking", "merged"],
    "reworking": ["awaiting-review", "failed"],
}


def _state_path(branch: str) -> Path:
    """Convert a branch name to a safe filesystem path for its state file.

    Args:
        branch: Git branch name (e.g. "ev-14942_fix_xss").

    Returns:
        Path to the JSON state file (slashes replaced with double underscores).
    """
    safe = branch.replace("/", "__")
    return STATE_DIR / f"{safe}.json"


def get_state(branch: str) -> dict | None:
    """Read the current pipeline state for a branch.

    Args:
        branch: Git branch name.

    Returns:
        State dict or None if no state file exists.
    """
    path = _state_path(branch)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def create_state(branch: str, issue_key: str, repo_path: str | None = None) -> dict:
    """Create an initial pipeline state for a new ticket.

    The state starts at "analyzing" with reworkCount=0.

    Args:
        branch: Git branch name (e.g. "ev-14942_fix_xss").
        issue_key: Ticket identifier (e.g. "EV-14942").
        repo_path: Absolute path to the target repo directory (optional).

    Returns:
        The newly created state dict.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
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
    _state_path(branch).write_text(json.dumps(state, indent=2))
    return state


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


def update_state_repo_path(branch: str, repo_path: str) -> None:
    """Update the repoPath field on an existing state record (best-effort).

    Used when the pipeline re-resolves ``repo_dir`` mid-flight (e.g. after
    the repo-picker chooses a sub-repo under a parentDir). If the state
    file doesn't exist, this is a silent no-op.

    Args:
        branch: Git branch name.
        repo_path: New absolute path to the repo directory.
    """
    current = get_state(branch)
    if not current:
        return
    current["repoPath"] = repo_path
    current["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _state_path(branch).write_text(json.dumps(current, indent=2))


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


def is_rework_limit_exceeded(branch: str, max_rework: int = 3) -> bool:
    """Check if the rework iteration cap has been reached.

    Args:
        branch: Git branch name.
        max_rework: Maximum allowed rework iterations (default 3).

    Returns:
        True if reworkCount >= max_rework, False otherwise.
    """
    current = get_state(branch)
    if not current:
        return False
    return current.get("reworkCount", 0) >= max_rework


def delete_state(branch: str) -> bool:
    """Delete the pipeline state for a branch.

    Args:
        branch: Git branch name.

    Returns:
        True if the state file was deleted, False if it didn't exist.
    """
    path = _state_path(branch)
    if path.exists():
        path.unlink()
        return True
    return False


def delete_state_by_issue_key(issue_key: str) -> bool:
    """Delete the pipeline state matching an issue key.

    Scans all state files to find the one matching the given issue key.

    Args:
        issue_key: Ticket identifier (e.g. "PROJ-123").

    Returns:
        True if a state file was found and deleted, False otherwise.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for f in STATE_DIR.glob("*.json"):
        state = json.loads(f.read_text())
        if state.get("issueKey") == issue_key:
            f.unlink()
            return True
    return False


def list_active_states() -> list[dict]:
    """List all pipeline states across all branches.

    Returns:
        List of state dicts (one per branch).
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    states = []
    for f in STATE_DIR.glob("*.json"):
        states.append(json.loads(f.read_text()))
    return states
