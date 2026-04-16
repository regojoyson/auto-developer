"""
Pipeline state machine.

Tracks each ticket's lifecycle as a JSON file per branch inside
`.pipeline-state/`. Every agent invocation checks state before starting
to prevent duplicate processing.

State flow:
    (new) → brainstorming → developing → awaiting-review → merged
                                               ↓       ↑
                                            reworking ──┘

Usage:
    from src.state.manager import create_state, get_state, transition_state

    create_state("feature/PROJ-1-login", "PROJ-1", "/projects/my-app")
    transition_state("feature/PROJ-1-login", "developing")
    state = get_state("feature/PROJ-1-login")
    print(state["state"])  # "developing"
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent.parent / ".pipeline-state"

# Defines which state transitions are allowed.
# Key = current state, Value = list of states it can transition to.
VALID_TRANSITIONS = {
    "brainstorming": ["developing"],
    "developing": ["awaiting-review"],
    "awaiting-review": ["reworking", "merged"],
    "reworking": ["awaiting-review"],
}


def _state_path(branch: str) -> Path:
    """Convert a branch name to a safe filesystem path for its state file.

    Args:
        branch: Git branch name (e.g. "feature/PROJ-1-login").

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
        State dict with keys (branch, issueKey, state, createdAt, updatedAt,
        reworkCount, repoPath), or None if no state file exists.
    """
    path = _state_path(branch)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def create_state(branch: str, issue_key: str, repo_path: str | None = None) -> dict:
    """Create an initial pipeline state for a new ticket.

    The state starts at "brainstorming" with reworkCount=0.

    Args:
        branch: Git branch name (e.g. "feature/PROJ-1-login").
        issue_key: Ticket identifier (e.g. "PROJ-1").
        repo_path: Absolute path to the target repo directory (optional).

    Returns:
        The newly created state dict.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "branch": branch,
        "issueKey": issue_key,
        "state": "brainstorming",
        "createdAt": now,
        "updatedAt": now,
        "reworkCount": 0,
        "repoPath": repo_path,
    }
    _state_path(branch).write_text(json.dumps(state, indent=2))
    return state


def transition_state(branch: str, new_state: str) -> dict:
    """Transition a branch's pipeline to a new state.

    Validates the transition against VALID_TRANSITIONS. Increments
    reworkCount when transitioning to "reworking".

    Args:
        branch: Git branch name.
        new_state: Target state (e.g. "developing", "awaiting-review").

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

    current["state"] = new_state
    current["updatedAt"] = datetime.now(timezone.utc).isoformat()
    if new_state == "reworking":
        current["reworkCount"] = current.get("reworkCount", 0) + 1

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
