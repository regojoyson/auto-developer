"""Git provider webhook route.

Provides a ``POST /webhooks/git`` endpoint that receives webhook payloads
from the configured git provider (GitLab or GitHub). Handles three event
types:

- **approved** -- Marks the pipeline as merged and triggers post-merge actions.
- **push** -- Logs human pushes on tracked branches.
- **comment** -- Triggers the feedback parser agent when a review comment
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
from src.providers.git_provider import get_git_provider

logger = logging.getLogger(__name__)
router = APIRouter()


def _run_async(agent, input_data, cwd):
    """Launch an agent in a background daemon thread.

    Args:
        agent: Name of the agent to run (e.g. ``"orchestrator"``).
        input_data: JSON-encoded input string for the agent.
        cwd: Working directory for the agent process.
    """
    threading.Thread(target=run_agent, args=(agent, input_data), kwargs={"cwd": cwd}, daemon=True).start()


@router.post("/")
async def handle_webhook(request: Request):
    """Handle an incoming git provider webhook.

    Delegates payload parsing to the configured adapter, then dispatches
    based on the event type: transitions state on approval, logs pushes,
    and triggers the feedback parser on review comments (respecting the
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
        _run_async("orchestrator", json.dumps({
            "action": "merge-approved", "issueKey": state["issueKey"], "branch": branch, "prId": pr_id,
        }), state.get("repoPath", "."))

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
            _run_async("orchestrator", json.dumps({
                "action": "rework-limit-exceeded", "issueKey": state["issueKey"],
                "branch": resolved_branch, "reworkCount": state.get("reworkCount", 0),
            }), state.get("repoPath", "."))
            return {"received": True}

        logger.info(f"Review comment for {state['issueKey']}, invoking feedback parser")
        _run_async("feedback-parser", json.dumps({
            "issueKey": state["issueKey"], "branch": resolved_branch, "prId": pr_id,
        }), state.get("repoPath", "."))

    return {"received": True}
