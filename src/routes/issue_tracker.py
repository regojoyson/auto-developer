"""Issue tracker webhook route.

Provides a ``POST /webhooks/issue-tracker`` endpoint that receives webhook
payloads from the configured issue tracker (Jira or GitHub Issues). When a
matching event is detected (e.g. a ticket status change to "Ready for
Development"), the handler creates a feature branch name, initializes
pipeline state, and launches the pipeline phases in a background thread.

Mount this router under ``/webhooks/issue-tracker`` in the FastAPI app.
"""

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

    import time
    slug = re.sub(r"[^a-z0-9\s_]", "", summary.lower())
    slug = re.sub(r"\s+", "_", slug)[:40].rstrip("_")
    suffix = str(int(time.time()))[-6:]  # last 6 digits of epoch for uniqueness
    branch = f"{issue_key.lower()}_{slug}_{suffix}"

    if get_state(branch):
        logger.warning(f"Pipeline already active for {branch}")
        return {"ignored": True, "reason": "already active"}

    try:
        repo_dir = get_repo_dir(component)
    except ValueError as e:
        logger.warning(f"{issue_key}: cannot select repo — {e}")
        # Best-effort: tell the human what went wrong.
        from src.executor.pipeline import try_add_comment
        try_add_comment(issue_key, f"Pipeline could not start: {e}")
        return {"accepted": False, "issueKey": issue_key, "reason": str(e)}
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
