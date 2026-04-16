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
from src.providers.output_handler import get_output_handlers

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


@router.get("/{issue_key}/logs")
async def get_pipeline_logs(issue_key: str, agent: str | None = None):
    """Get real-time agent output for a pipeline.

    Returns the captured output from all agents (or a specific one)
    that ran for this issue key.

    Args:
        issue_key: Ticket identifier (e.g. "PROJ-123").
        agent: Optional agent name filter (e.g. "orchestrator").

    Returns:
        dict: ``{"issueKey": ..., "agent": ..., "output": "..."}``
    """
    handlers = get_output_handlers()
    output = handlers.get_output(issue_key, agent)
    return {
        "issueKey": issue_key,
        "agent": agent or "all",
        "output": output,
        "lines": len(output.split("\n")) if output else 0,
    }


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
        handlers = get_output_handlers()
        handlers.delete_logs(issue_key)
        logger.info(f"Pipeline cancelled and logs deleted: {issue_key}")
        return {"cancelled": True, "issueKey": issue_key, "logsDeleted": True}
    return {"error": "Pipeline not found", "issueKey": issue_key}
