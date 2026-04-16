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
