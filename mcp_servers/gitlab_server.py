"""GitLab MCP server -- exposes GitLab REST API v4 operations as MCP tools.

Provides an MCP (Model Context Protocol) server that allows AI coding agents
to interact with a GitLab project via tool calls. Supports branch creation,
file commits, merge request management, commenting, and file reads.

Requires the following environment variables:

- ``GITLAB_TOKEN`` -- GitLab personal access token with ``api`` scope.
- ``GITLAB_PROJECT_ID`` -- Numeric ID of the target GitLab project.
- ``GITLAB_BASE_URL`` (optional) -- GitLab instance URL, defaults to
  ``https://gitlab.com``.

Usage::

    GITLAB_TOKEN=xxx GITLAB_PROJECT_ID=123 python mcp_servers/gitlab_server.py
"""

import json
import os
from base64 import b64decode
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

GITLAB_BASE_URL = os.environ.get("GITLAB_BASE_URL", "https://gitlab.com").rstrip("/")
GITLAB_TOKEN = os.environ["GITLAB_TOKEN"]
GITLAB_PROJECT_ID = os.environ["GITLAB_PROJECT_ID"]

client = httpx.Client(
    base_url=f"{GITLAB_BASE_URL}/api/v4",
    headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Content-Type": "application/json"},
)
P = f"/projects/{GITLAB_PROJECT_ID}"

mcp = FastMCP("gitlab-mcp")


@mcp.tool()
def create_branch(branch_name: str, ref: str = "main") -> str:
    """Create a new branch in the GitLab project.

    Args:
        branch_name: Name for the new branch.
        ref: Source branch or commit SHA to create the branch from.

    Returns:
        JSON string with the branch name and commit ID.
    """
    r = client.post(f"{P}/repository/branches", json={"branch": branch_name, "ref": ref})
    data = r.json()
    return json.dumps({"name": data.get("name"), "commit_id": data.get("commit", {}).get("id")}, indent=2)


@mcp.tool()
def commit_files(branch: str, commit_message: str, actions: str) -> str:
    """Commit one or more file changes to a branch.

    Args:
        branch: Target branch name.
        commit_message: Message for the commit.
        actions: JSON-encoded array of action objects. Each object must
            have keys ``action`` (``"create"``, ``"update"``, or
            ``"delete"``), ``file_path``, and ``content``.

    Returns:
        JSON string with the commit ID, short ID, and title.
    """
    r = client.post(f"{P}/repository/commits", json={"branch": branch, "commit_message": commit_message, "actions": json.loads(actions)})
    data = r.json()
    return json.dumps({"id": data.get("id"), "short_id": data.get("short_id"), "title": data.get("title")}, indent=2)


@mcp.tool()
def create_merge_request(source_branch: str, target_branch: str, title: str, description: str) -> str:
    """Create a merge request from source to target branch.

    Args:
        source_branch: Branch containing the changes.
        target_branch: Branch to merge into.
        title: Merge request title.
        description: Merge request description body.

    Returns:
        JSON string with the MR IID, web URL, title, and state.
    """
    r = client.post(f"{P}/merge_requests", json={"source_branch": source_branch, "target_branch": target_branch, "title": title, "description": description})
    data = r.json()
    return json.dumps({"iid": data.get("iid"), "web_url": data.get("web_url"), "title": data.get("title"), "state": data.get("state")}, indent=2)


@mcp.tool()
def get_merge_request(mr_iid: str) -> str:
    """Get merge request details by IID.

    Args:
        mr_iid: The merge request internal ID.

    Returns:
        JSON string with the MR IID, title, state, source branch,
        web URL, and description.
    """
    data = client.get(f"{P}/merge_requests/{mr_iid}").json()
    return json.dumps({"iid": data.get("iid"), "title": data.get("title"), "state": data.get("state"), "source_branch": data.get("source_branch"), "web_url": data.get("web_url"), "description": data.get("description")}, indent=2)


@mcp.tool()
def update_merge_request(mr_iid: str, title: str = "", description: str = "") -> str:
    """Update a merge request's title or description.

    Args:
        mr_iid: The merge request internal ID.
        title: New title (empty string to leave unchanged).
        description: New description (empty string to leave unchanged).

    Returns:
        JSON string with the updated MR IID, title, and state.
    """
    updates = {}
    if title:
        updates["title"] = title
    if description:
        updates["description"] = description
    data = client.put(f"{P}/merge_requests/{mr_iid}", json=updates).json()
    return json.dumps({"iid": data.get("iid"), "title": data.get("title"), "state": data.get("state")}, indent=2)


@mcp.tool()
def list_mr_comments(mr_iid: str) -> str:
    """List all comments (notes) on a merge request, sorted by creation date.

    Args:
        mr_iid: The merge request internal ID.

    Returns:
        JSON string with an array of comment objects, each containing
        ``id``, ``author``, ``body``, ``created_at``, and ``system``.
    """
    data = client.get(f"{P}/merge_requests/{mr_iid}/notes", params={"sort": "asc", "order_by": "created_at"}).json()
    comments = [{"id": n["id"], "author": n.get("author", {}).get("username"), "body": n.get("body"), "created_at": n.get("created_at"), "system": n.get("system")} for n in data]
    return json.dumps(comments, indent=2)


@mcp.tool()
def post_mr_comment(mr_iid: str, body: str) -> str:
    """Post a comment on a merge request.

    Args:
        mr_iid: The merge request internal ID.
        body: Comment text to post.

    Returns:
        JSON string with the created note ``id`` and ``body``.
    """
    data = client.post(f"{P}/merge_requests/{mr_iid}/notes", json={"body": body}).json()
    return json.dumps({"id": data.get("id"), "body": data.get("body")}, indent=2)


@mcp.tool()
def get_file(file_path: str, ref: str = "main") -> str:
    """Read a file's content from the repository.

    Args:
        file_path: Path to the file within the repository.
        ref: Branch name, tag, or commit SHA to read from.

    Returns:
        The decoded UTF-8 file content as a string.
    """
    encoded = quote(file_path, safe="")
    data = client.get(f"{P}/repository/files/{encoded}", params={"ref": ref}).json()
    return b64decode(data.get("content", "")).decode("utf-8")


if __name__ == "__main__":
    mcp.run()
