"""Pipeline status and management routes.

Provides endpoints for querying and cancelling pipelines:

    GET    /api/status              -- list all active pipelines
    GET    /api/status/{issue_key}  -- get status for a specific issue
    DELETE /api/status/{issue_key}  -- cancel/remove a pipeline

Mount this router under ``/api/status`` in the FastAPI app.
"""

import logging
from fastapi import APIRouter
from src.state.manager import list_active_states, delete_state_by_issue_key

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
async def list_pipelines():
    """List all active pipelines.

    Returns:
        dict: ``{"count": N, "pipelines": [...]}``
    """
    states = list_active_states()
    return {"count": len(states), "pipelines": states}


@router.get("/{issue_key}")
async def get_pipeline(issue_key: str):
    """Get pipeline status for a specific issue.

    Args:
        issue_key: Ticket identifier (e.g. "PROJ-123").
    """
    states = list_active_states()
    match = next((s for s in states if s.get("issueKey") == issue_key), None)
    if not match:
        return {"error": "Pipeline not found", "issueKey": issue_key}
    return match


@router.delete("/{issue_key}")
async def cancel_pipeline(issue_key: str):
    """Cancel and remove a pipeline by issue key.

    Deletes the pipeline state file so the ticket can be re-triggered.

    Args:
        issue_key: Ticket identifier (e.g. "PROJ-123").

    Returns:
        dict: ``{"cancelled": True, ...}`` if found, or error if not found.
    """
    deleted = delete_state_by_issue_key(issue_key)
    if deleted:
        logger.info(f"Pipeline cancelled: {issue_key}")
        return {"cancelled": True, "issueKey": issue_key}
    return {"error": "Pipeline not found", "issueKey": issue_key}
