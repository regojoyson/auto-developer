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
from src.state.manager import get_state, create_state, find_state_by_issue_key
from src.executor.pipeline import run_pipeline_phases, resume_from_blocked
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

    event_type = parsed.get("event_type", "trigger")
    issue_key = parsed["issue_key"]

    # ── Comment event: resume a blocked pipeline if applicable ─
    if event_type == "comment":
        # Skip bot/self comments so the pipeline's own posts don't trigger
        # a resume loop. We identify self-posts by checking the author
        # against configured bot users on the git provider section (best
        # proxy for "our" service account) and by ignoring the resume
        # acknowledgement itself.
        body = parsed.get("comment_body", "")
        author = parsed.get("comment_author", "")
        git_bots = app_config.get("git_provider", {}).get("bot_users", []) or []
        if author and any(bot.lower() in author.lower() for bot in git_bots):
            return {"ignored": True, "reason": "comment from bot"}
        if body.startswith("Reply received — resuming pipeline"):
            return {"ignored": True, "reason": "self comment"}

        state = find_state_by_issue_key(issue_key)
        if not state or state.get("state") != "blocked":
            return {"ignored": True, "reason": "not blocked"}

        logger.info(f"Resuming blocked pipeline for {issue_key} — comment from {author or 'unknown'}")
        threading.Thread(
            target=resume_from_blocked,
            args=(issue_key, body),
            daemon=True,
        ).start()
        return {"accepted": True, "resumed": True, "issueKey": issue_key}

    # ── Trigger event: start a fresh pipeline ──────────
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
