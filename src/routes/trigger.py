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
    summary: str = None
    component: str = None


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
