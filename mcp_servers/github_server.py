"""GitHub MCP server -- exposes GitHub REST API operations as MCP tools.

Provides an MCP (Model Context Protocol) server that allows AI coding agents
to interact with a GitHub repository via tool calls. Supports branch creation,
file commits, pull request management, commenting, and file reads.

Requires the following environment variables:

- ``GITHUB_TOKEN`` -- GitHub personal access token or fine-grained token.
- ``GITHUB_OWNER`` -- Repository owner (organization or username).
- ``GITHUB_REPO`` -- Repository name.

Usage::

    GITHUB_TOKEN=xxx GITHUB_OWNER=myorg GITHUB_REPO=myrepo python mcp_servers/github_server.py
"""

import json
import os
from base64 import b64decode, b64encode

import httpx
from mcp.server.fastmcp import FastMCP

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = os.environ["GITHUB_OWNER"]
GITHUB_REPO = os.environ["GITHUB_REPO"]

client = httpx.Client(
    base_url="https://api.github.com",
    headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
)
R = f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

mcp = FastMCP("github-mcp")


@mcp.tool()
def create_branch(branch_name: str, ref: str = "main") -> str:
    """Create a new branch from a reference.

    Args:
        branch_name: Name for the new branch.
        ref: Source branch to create the branch from.

    Returns:
        JSON string with the git ref and SHA.
    """
    ref_data = client.get(f"{R}/git/ref/heads/{ref}").json()
    sha = ref_data["object"]["sha"]
    data = client.post(f"{R}/git/refs", json={"ref": f"refs/heads/{branch_name}", "sha": sha}).json()
    return json.dumps({"ref": data.get("ref"), "sha": data.get("object", {}).get("sha")}, indent=2)


@mcp.tool()
def commit_files(branch: str, commit_message: str, actions: str) -> str:
    """Commit one or more file changes to a branch.

    Processes each action sequentially via the GitHub Contents API.
    Supports create, update, and delete operations.

    Args:
        branch: Target branch name.
        commit_message: Message for the commit(s).
        actions: JSON-encoded array of action objects. Each object must
            have keys ``action`` (``"create"``, ``"update"``, or
            ``"delete"``), ``file_path``, and ``content``.

    Returns:
        JSON string with ``committed`` (bool) and ``files`` (count).
    """
    parsed = json.loads(actions)
    for action in parsed:
        path = action["file_path"]
        if action["action"] == "delete":
            existing = client.get(f"{R}/contents/{path}", params={"ref": branch}).json()
            client.request("DELETE", f"{R}/contents/{path}", json={"message": commit_message, "branch": branch, "sha": existing["sha"]})
        else:
            sha = None
            try:
                existing = client.get(f"{R}/contents/{path}", params={"ref": branch}).json()
                sha = existing.get("sha")
            except Exception:
                pass
            body = {"message": commit_message, "branch": branch, "content": b64encode((action.get("content") or "").encode()).decode()}
            if sha:
                body["sha"] = sha
            client.put(f"{R}/contents/{path}", json=body)
    return json.dumps({"committed": True, "files": len(parsed)}, indent=2)


@mcp.tool()
def create_pull_request(source_branch: str, target_branch: str, title: str, description: str) -> str:
    """Create a pull request from source to target branch.

    Args:
        source_branch: Head branch containing the changes.
        target_branch: Base branch to merge into.
        title: Pull request title.
        description: Pull request body text.

    Returns:
        JSON string with the PR number, HTML URL, title, and state.
    """
    data = client.post(f"{R}/pulls", json={"head": source_branch, "base": target_branch, "title": title, "body": description}).json()
    return json.dumps({"number": data.get("number"), "html_url": data.get("html_url"), "title": data.get("title"), "state": data.get("state")}, indent=2)


@mcp.tool()
def get_pull_request(pr_number: str) -> str:
    """Get pull request details by number.

    Args:
        pr_number: The pull request number.

    Returns:
        JSON string with the PR number, title, state, head/base refs,
        HTML URL, and body.
    """
    data = client.get(f"{R}/pulls/{pr_number}").json()
    return json.dumps({"number": data.get("number"), "title": data.get("title"), "state": data.get("state"), "head": data.get("head", {}).get("ref"), "base": data.get("base", {}).get("ref"), "html_url": data.get("html_url"), "body": data.get("body")}, indent=2)


@mcp.tool()
def update_pull_request(pr_number: str, title: str = "", description: str = "") -> str:
    """Update a pull request's title or description.

    Args:
        pr_number: The pull request number.
        title: New title (empty string to leave unchanged).
        description: New description (empty string to leave unchanged).

    Returns:
        JSON string with the updated PR number, title, and state.
    """
    updates = {}
    if title:
        updates["title"] = title
    if description:
        updates["body"] = description
    data = client.patch(f"{R}/pulls/{pr_number}", json=updates).json()
    return json.dumps({"number": data.get("number"), "title": data.get("title"), "state": data.get("state")}, indent=2)


@mcp.tool()
def list_pr_comments(pr_number: str) -> str:
    """List all comments on a pull request, sorted by creation date.

    Merges both issue comments and review comments into a single list.

    Args:
        pr_number: The pull request number.

    Returns:
        JSON string with an array of comment objects, each containing
        ``id``, ``author``, ``body``, ``created_at``, and optionally
        ``path`` and ``line`` for review comments.
    """
    issue = client.get(f"{R}/issues/{pr_number}/comments").json()
    review = client.get(f"{R}/pulls/{pr_number}/comments").json()
    all_comments = [
        *[{"id": c["id"], "author": c.get("user", {}).get("login"), "body": c.get("body"), "created_at": c.get("created_at")} for c in issue],
        *[{"id": c["id"], "author": c.get("user", {}).get("login"), "body": c.get("body"), "created_at": c.get("created_at"), "path": c.get("path"), "line": c.get("line")} for c in review],
    ]
    all_comments.sort(key=lambda x: x.get("created_at", ""))
    return json.dumps(all_comments, indent=2)


@mcp.tool()
def post_pr_comment(pr_number: str, body: str) -> str:
    """Post a comment on a pull request.

    Args:
        pr_number: The pull request number.
        body: Comment text to post.

    Returns:
        JSON string with the created comment ``id`` and ``body``.
    """
    data = client.post(f"{R}/issues/{pr_number}/comments", json={"body": body}).json()
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
    data = client.get(f"{R}/contents/{file_path}", params={"ref": ref}).json()
    return b64decode(data.get("content", "")).decode("utf-8")


if __name__ == "__main__":
    mcp.run()
