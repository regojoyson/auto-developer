"""GET /api/status — pipeline status queries."""

from fastapi import APIRouter
from src.state.manager import list_active_states

router = APIRouter()


@router.get("/")
async def list_pipelines():
    states = list_active_states()
    return {"count": len(states), "pipelines": states}


@router.get("/{issue_key}")
async def get_pipeline(issue_key: str):
    states = list_active_states()
    match = next((s for s in states if s.get("issueKey") == issue_key), None)
    if not match:
        return {"error": "Pipeline not found", "issueKey": issue_key}
    return match
