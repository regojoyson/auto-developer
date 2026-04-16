"""Pipeline state machine — tracks each ticket's lifecycle as JSON files."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent.parent / ".pipeline-state"

VALID_TRANSITIONS = {
    "brainstorming": ["developing"],
    "developing": ["awaiting-review"],
    "awaiting-review": ["reworking", "merged"],
    "reworking": ["awaiting-review"],
}


def _state_path(branch: str) -> Path:
    safe = branch.replace("/", "__")
    return STATE_DIR / f"{safe}.json"


def get_state(branch: str) -> dict | None:
    path = _state_path(branch)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def create_state(branch: str, issue_key: str, repo_path: str | None = None) -> dict:
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
    current = get_state(branch)
    if not current:
        return False
    return current.get("reworkCount", 0) >= max_rework


def list_active_states() -> list[dict]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    states = []
    for f in STATE_DIR.glob("*.json"):
        states.append(json.loads(f.read_text()))
    return states
