"""
Derive git provider project identifiers from a repo's git remote URL.

Instead of hardcoding project IDs in config, we read the repo's
origin remote at runtime and extract the owner/repo/project info.

Supports:
    - GitHub:  https://github.com/owner/repo.git → (owner, repo)
    - GitHub:  git@github.com:owner/repo.git → (owner, repo)
    - GitLab:  https://gitlab.com/group/repo.git → project ID via API
    - GitLab:  git@gitlab.com:group/repo.git → project ID via API

Usage::

    from src.repos.git_remote import get_remote_info

    info = get_remote_info("/projects/my-app")
    # → {"owner": "acme", "repo": "my-app", "project_id": "12345"}
"""

import logging
import os
import re
import subprocess

import httpx

logger = logging.getLogger(__name__)


def get_remote_url(repo_dir: str) -> str | None:
    """Read the origin remote URL from a git repo.

    Args:
        repo_dir: Absolute path to the repo directory.

    Returns:
        The remote URL string, or None if not a git repo or no origin.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_dir, capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def parse_remote_url(url: str) -> dict | None:
    """Parse a git remote URL into owner and repo name.

    Handles HTTPS and SSH formats for GitHub/GitLab.

    Args:
        url: Git remote URL (e.g. 'https://github.com/owner/repo.git'
            or 'git@gitlab.com:group/subgroup/repo.git')

    Returns:
        Dict with keys 'owner' (str) and 'repo' (str), or None if
        the URL couldn't be parsed. For GitLab, 'owner' may include
        subgroups (e.g. 'group/subgroup').
    """
    # HTTPS: https://github.com/owner/repo.git
    match = re.match(r"https?://[^/]+/(.+?)(?:\.git)?$", url)
    if match:
        parts = match.group(1).split("/")
        if len(parts) >= 2:
            return {"owner": "/".join(parts[:-1]), "repo": parts[-1]}

    # SSH: git@github.com:owner/repo.git
    match = re.match(r"git@[^:]+:(.+?)(?:\.git)?$", url)
    if match:
        parts = match.group(1).split("/")
        if len(parts) >= 2:
            return {"owner": "/".join(parts[:-1]), "repo": parts[-1]}

    return None


def get_gitlab_project_id(base_url: str, token: str, path_with_namespace: str) -> str | None:
    """Look up a GitLab project's numeric ID from its path.

    Args:
        base_url: GitLab instance URL (e.g. 'https://gitlab.com').
        token: GitLab API token.
        path_with_namespace: Full project path (e.g. 'group/subgroup/repo').

    Returns:
        The numeric project ID as a string, or None on failure.
    """
    try:
        encoded = path_with_namespace.replace("/", "%2F")
        resp = httpx.get(
            f"{base_url}/api/v4/projects/{encoded}",
            headers={"PRIVATE-TOKEN": token},
        )
        if resp.status_code == 200:
            project_id = str(resp.json().get("id", ""))
            logger.info(f"Resolved GitLab project ID: {path_with_namespace} → {project_id}")
            return project_id
    except Exception as e:
        logger.warning(f"Failed to resolve GitLab project ID for {path_with_namespace}: {e}")
    return None


def get_remote_info(repo_dir: str, provider_type: str = "github") -> dict:
    """Get git provider project info by reading the repo's remote URL.

    For GitHub: returns owner + repo name (extracted from URL).
    For GitLab: returns owner + repo + project_id (looked up via API).

    Args:
        repo_dir: Absolute path to the repo directory.
        provider_type: 'github' or 'gitlab'.

    Returns:
        Dict with keys:
            - owner (str): Org or group name
            - repo (str): Repository name
            - project_id (str|None): GitLab project ID (None for GitHub)
    """
    url = get_remote_url(repo_dir)
    if not url:
        logger.warning(f"No git remote found in {repo_dir}")
        return {"owner": "", "repo": "", "project_id": None}

    parsed = parse_remote_url(url)
    if not parsed:
        logger.warning(f"Could not parse remote URL: {url}")
        return {"owner": "", "repo": "", "project_id": None}

    result = {
        "owner": parsed["owner"],
        "repo": parsed["repo"],
        "project_id": None,
    }

    if provider_type == "gitlab":
        base_url = os.environ.get("GITLAB_BASE_URL", "https://gitlab.com").rstrip("/")
        token = os.environ.get("GITLAB_TOKEN", "")
        if token:
            path = f"{parsed['owner']}/{parsed['repo']}"
            result["project_id"] = get_gitlab_project_id(base_url, token, path)

    return result
