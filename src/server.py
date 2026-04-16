"""
FastAPI webhook server — the application entry point.

Registers all route handlers and starts with uvicorn:
    python3 -m uvicorn src.server:app --host 0.0.0.0 --port 3000

Endpoints:
    GET  /health                  — Health check
    POST /webhooks/issue-tracker  — Issue tracker webhooks (Jira, GitHub Issues)
    POST /webhooks/git            — Git provider webhooks (GitLab, GitHub)
    POST /api/trigger             — Manual pipeline trigger
    GET  /api/status              — List all pipelines
    GET  /api/status/{issue_key}  — Get pipeline status for a ticket
"""

import logging
from dotenv import load_dotenv
from fastapi import FastAPI

# Load .env before anything else reads os.environ
load_dotenv()

# Configure logging for the entire application
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s — %(message)s",
)

from src.config import config
from src.routes import issue_tracker, git_provider, trigger, status

app = FastAPI(title="Auto Developer", version="1.0.0")

# Register route modules
app.include_router(issue_tracker.router, prefix="/webhooks/issue-tracker")
app.include_router(git_provider.router, prefix="/webhooks/git")
app.include_router(trigger.router, prefix="/api/trigger")
app.include_router(status.router, prefix="/api/status")


@app.get("/health")
def health():
    """Health check — returns server status and timestamp."""
    from datetime import datetime, timezone
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
