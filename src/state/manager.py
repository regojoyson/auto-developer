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


def _atomic_write(branch: str, state: dict) -> None:
    """Write state JSON atomically (temp file + rename).

    Prevents a partial write from corrupting the state if the process dies
    mid-write or two threads try to write at the same time.
    """
    import os
    import tempfile

    path = _state_path(branch)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a sibling temp file then atomic rename onto the target.
    fd, tmp = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


def create_state(
    branch: str,
    issue_key: str,
    repo_path: str | None = None,
    repos: list[dict] | None = None,
) -> dict:
    """Create an initial pipeline state for a new ticket.

    Either ``repo_path`` (single-repo ticket) or ``repos`` (multi-repo) must
    be provided. When ``repos`` is given, the state record's ``repos`` field
    is populated with per-repo sub-state tracking; the top-level
    ``repoPath`` convenience field mirrors ``repos[0]["path"]`` for
    backward-compatible dashboard display.

    The state starts at "analyzing" with reworkCount=0.

    Args:
        branch: Feature branch name (reused across all repos in multi-repo mode).
        issue_key: Ticket identifier (e.g. "EV-14942").
        repo_path: Absolute path to the repo (single-repo mode). Ignored
            when ``repos`` is provided.
        repos: List of ``{"name", "path"}`` dicts (multi-repo mode). Each
            entry is expanded to
            ``{"name", "path", "state": "pending", "prId": None, "mrUrl": None, "error": None}``.

    Returns:
        The newly created state dict.

    Raises:
        ValueError: If neither ``repo_path`` nor ``repos`` is provided.
    """
    if repos is None and repo_path is None:
        raise ValueError("create_state requires either repo_path or repos")

    # Normalise: always produce repos[] internally. Single-repo mode
    # converts repo_path to a one-element list.
    if repos is None:
        repos = [{"name": Path(repo_path).name, "path": repo_path}]

    normalised_repos = [
        {
            "name": r["name"],
            "path": r["path"],
            "state": "pending",
            "prId": None,
            "mrUrl": None,
            "error": None,
        }
        for r in repos
    ]

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "branch": branch,
        "issueKey": issue_key,
        "state": "analyzing",
        "createdAt": now,
        "updatedAt": now,
        "reworkCount": 0,
        "repoPath": normalised_repos[0]["path"],
        "repos": normalised_repos,
        "error": None,
        "phases": [],
        "artifacts": {},
    }
    _atomic_write(branch, state)
    logger.info(f"Created state for {branch} with {len(normalised_repos)} repo(s)")
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

    _atomic_write(branch, current)
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
    _atomic_write(branch, current)
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
    _atomic_write(branch, current)
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
    # Keep repos[0]["path"] in sync for single-repo flow (the only path
    # that ever re-resolves mid-flight via the repo-picker).
    repos = current.get("repos") or []
    if repos:
        repos[0]["path"] = repo_path
    current["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(branch, current)


def update_repo_sub_state(
    branch: str,
    repo_name: str,
    new_sub_state: str,
    **extra,
) -> dict | None:
    """Update one entry in ``state["repos"][]`` atomically.

    Args:
        branch: Feature branch name.
        repo_name: Value of the ``name`` field on the repo entry to update.
        new_sub_state: New sub-state for this repo (e.g. "analyzing",
            "developing", "completed", "failed", "reworking").
        **extra: Additional fields to set on the entry (e.g. ``prId=123``,
            ``mrUrl="..."``, ``error="git push failed"``).

    Returns:
        The updated state dict, or None if the state or repo was not found.
    """
    state = get_state(branch)
    if not state:
        return None

    repos = state.get("repos") or []
    match = next((r for r in repos if r.get("name") == repo_name), None)
    if not match:
        logger.warning(f"update_repo_sub_state: no repo named {repo_name!r} in {branch}")
        return None

    match["state"] = new_sub_state
    for key, value in extra.items():
        match[key] = value

    # Keep top-level shortcuts in sync when the first repo changes
    if repos and repos[0].get("name") == repo_name:
        if "prId" in extra:
            state["prId"] = extra["prId"]
        if "mrUrl" in extra:
            state["mrUrl"] = extra["mrUrl"]

    state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(branch, state)
    return state


def set_state_repos(branch: str, repos: list[dict]) -> dict | None:
    """Replace the ``repos`` array on an existing state record.

    Used when the pipeline's picker resolves the list of affected repos
    AFTER initial state creation (which only has a placeholder repo_path).

    Args:
        branch: Feature branch name.
        repos: List of ``{"name", "path"}`` dicts. Each entry is expanded
            to ``{"name", "path", "state": "pending", "prId": None,
            "mrUrl": None, "error": None}``.

    Returns:
        The updated state dict, or None if no state record exists for
        the branch.
    """
    state = get_state(branch)
    if not state:
        return None
    normalised = [
        {
            "name": r["name"],
            "path": r["path"],
            "state": "pending",
            "prId": None,
            "mrUrl": None,
            "error": None,
        }
        for r in repos
    ]
    state["repos"] = normalised
    state["repoPath"] = normalised[0]["path"] if normalised else state.get("repoPath")
    state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(branch, state)
    return state


def find_repo_by_pr_id(state: dict, pr_id) -> dict | None:
    """Find the repo entry that owns a given PR/MR id.

    Args:
        state: A state dict (as returned by ``get_state``).
        pr_id: The PR/MR id to look up (usually an int, but string-safe).

    Returns:
        The matching ``{"name", "path", "state", "prId", "mrUrl", ...}``
        dict, or None if no repo in this state owns that PR id.
    """
    if not state:
        return None
    for repo in state.get("repos") or []:
        # Compare as-is AND as string to handle int/str drift.
        if repo.get("prId") == pr_id or str(repo.get("prId")) == str(pr_id):
            return repo
    return None


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
    _atomic_write(branch, current)
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
