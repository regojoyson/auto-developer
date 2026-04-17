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

import logging
import threading

from fastapi import APIRouter, Request

from src.config import config
from src.state.manager import get_state, transition_state, is_rework_limit_exceeded, list_active_states, find_repo_by_pr_id
from src.executor.pipeline import run_rework_phases, try_add_comment, try_notify_slack
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
        try_add_comment(state["issueKey"], f"{state['issueKey']} merged successfully")
        try_notify_slack(f"{state['issueKey']} merged")

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
            try_add_comment(
                state["issueKey"],
                f"{state['issueKey']} has exceeded the rework limit ({state.get('reworkCount', 0)} iterations) — human intervention needed",
            )
            try_notify_slack(f"{state['issueKey']} escalation: rework limit exceeded")
            return {"received": True}

        # Route rework to the specific repo whose MR was commented on.
        # Multi-repo tickets have N MRs; we only want to rework the one
        # the reviewer actually commented on, leaving the others untouched.
        repo_entry = find_repo_by_pr_id(state, pr_id)
        if repo_entry:
            repo_dir = repo_entry["path"]
            logger.info(
                f"Review comment for {state['issueKey']} on MR {pr_id} "
                f"(repo: {repo_entry['name']}), starting rework pipeline"
            )
        else:
            # Backward-compat: legacy single-repo state records or states
            # where the pr_id wasn't recorded per-repo yet. Fall back to the
            # top-level repoPath.
            repo_dir = state.get("repoPath", ".")
            logger.info(
                f"Review comment for {state['issueKey']} on MR {pr_id} "
                f"(no repo match, using repoPath), starting rework pipeline"
            )

        statuses = _get_statuses()
        threading.Thread(
            target=run_rework_phases,
            args=(state["issueKey"], resolved_branch, pr_id, statuses, repo_dir),
            daemon=True,
        ).start()

    return {"received": True}
