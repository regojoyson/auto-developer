"""Pipeline status query routes.

Provides ``GET /api/status`` endpoints for querying the current state of
active pipelines. Supports listing all active pipelines and looking up a
specific pipeline by issue key.

Mount this router under ``/api/status`` in the FastAPI app.

Example requests::

    GET /api/status          -- list all active pipelines
    GET /api/status/PROJ-123 -- get status for a specific issue
"""

from fastapi import APIRouter
from src.state.manager import list_active_states

router = APIRouter()


@router.get("/")
async def list_pipelines():
    """List all currently active pipelines.

    Returns:
        dict: A dict with ``count`` (int) and ``pipelines`` (list of
            pipeline state dicts).
    """
    states = list_active_states()
    return {"count": len(states), "pipelines": states}


@router.get("/{issue_key}")
async def get_pipeline(issue_key: str):
    """Get the pipeline status for a specific issue.

    Args:
        issue_key: The issue tracker key to look up (e.g. ``"PROJ-123"``).

    Returns:
        dict: The pipeline state dict if found, or an error dict with
            ``{"error": "Pipeline not found", "issueKey": ...}`` if no
            active pipeline matches the given key.
    """
    states = list_active_states()
    match = next((s for s in states if s.get("issueKey") == issue_key), None)
    if not match:
        return {"error": "Pipeline not found", "issueKey": issue_key}
    return match
