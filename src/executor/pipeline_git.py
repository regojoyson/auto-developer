"""Python-driven remote git operations used by the pipeline.

All functions that previously lived inside the orchestrator agent's
prompt (create remote branch, commit a file via the git-provider API,
git push, create a PR/MR) are collected here. Pipeline phases are thin
Python coordinators around these helpers — the LLM never executes them.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def create_remote_branch(api, *, branch: str, base: str) -> None:
    """Create a feature branch on the remote from ``base``.

    No-op if the branch already exists (idempotent — useful for retries).
    """
    try:
        api.create_branch(branch, ref=base)
        logger.info(f"Created remote branch {branch} from {base}")
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "branch already exists" in msg:
            logger.info(f"Remote branch {branch} already exists — reusing")
            return
        raise


def commit_local_file_via_api(api, *, repo_dir: str, branch: str, file_path: str, message: str) -> None:
    """Read a file from ``repo_dir`` and commit it to the remote branch via API.

    Used for TICKET.md and PLAN.md, where the agent wrote the file locally
    but Python owns the commit/push so the agent doesn't need git tools.
    """
    full_path = Path(repo_dir) / file_path
    if not full_path.exists():
        raise FileNotFoundError(f"Expected {file_path} at {full_path} — agent did not write it")
    content = full_path.read_text(encoding="utf-8")
    api.commit_files(
        branch,
        message,
        [{"file_path": file_path, "action": "create", "content": content}],
    )
    logger.info(f"Committed {file_path} to {branch} via API")


def push_local_branch(repo_dir: str, branch: str) -> None:
    """Run ``git push origin <branch>`` in ``repo_dir``.

    Raises ``RuntimeError`` with stderr on non-zero exit.
    """
    result = subprocess.run(
        ["git", "push", "origin", branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git push failed: {result.stderr.strip()}")
    logger.info(f"Pushed {branch} to origin")


def create_merge_request(
    api, *, source: str, target: str, title: str, description: str
) -> dict:
    """Create a PR / MR via the git-provider API. Returns the provider's response dict."""
    mr = api.create_pr(source, target, title, description)
    url = mr.get("web_url") or mr.get("html_url") or mr.get("url") or "(no URL)"
    logger.info(f"Created MR/PR: {url}")
    return mr
