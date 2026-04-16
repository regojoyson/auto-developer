"""FastAPI webhook server — entry point."""

import logging
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(name)s — %(message)s")

from src.config import config
from src.routes import issue_tracker, git_provider, trigger, status

app = FastAPI(title="Auto Developer", version="1.0.0")

app.include_router(issue_tracker.router, prefix="/webhooks/issue-tracker")
app.include_router(git_provider.router, prefix="/webhooks/git")
app.include_router(trigger.router, prefix="/api/trigger")
app.include_router(status.router, prefix="/api/status")


@app.get("/health")
def health():
    from datetime import datetime, timezone
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
