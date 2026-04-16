"""POST /api/trigger — manual pipeline trigger."""

import json
import logging
import re
import threading

from fastapi import APIRouter
from pydantic import BaseModel

from src.state.manager import get_state, create_state
from src.agents.runner import run_agent
from src.repos.resolver import get_repo_dir, prepare_repo, get_base_branch

logger = logging.getLogger(__name__)
router = APIRouter()


class TriggerRequest(BaseModel):
    issueKey: str
    summary: str | None = None
    component: str | None = None


@router.post("/")
async def manual_trigger(body: TriggerRequest):
    issue_key = body.issueKey
    summary = body.summary or issue_key
    component = body.component

    slug = re.sub(r"[^a-z0-9\s-]", "", summary.lower())
    slug = re.sub(r"\s+", "-", slug)[:40].rstrip("-")
    branch = f"feature/{issue_key}-{slug}"

    if get_state(branch):
        return {"error": "Pipeline already active for this ticket", "branch": branch}

    repo_dir = get_repo_dir(component)
    logger.info(f"Manual trigger: {issue_key}", extra={"branch": branch, "repo_dir": repo_dir})

    prepare_repo(repo_dir)
    create_state(branch, issue_key, repo_path=repo_dir)

    base_branch = get_base_branch()
    input_data = json.dumps({
        "issueKey": issue_key,
        "branch": branch,
        "summary": summary,
        "projectKey": issue_key.split("-")[0],
        "baseBranch": base_branch,
    })

    threading.Thread(
        target=run_agent, args=("orchestrator", input_data), kwargs={"cwd": repo_dir}, daemon=True
    ).start()

    return {"accepted": True, "issueKey": issue_key, "branch": branch, "repoDir": repo_dir}
