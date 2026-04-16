"""GitHub MCP server — wraps GitHub REST API."""

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
    """Create a new branch."""
    ref_data = client.get(f"{R}/git/ref/heads/{ref}").json()
    sha = ref_data["object"]["sha"]
    data = client.post(f"{R}/git/refs", json={"ref": f"refs/heads/{branch_name}", "sha": sha}).json()
    return json.dumps({"ref": data.get("ref"), "sha": data.get("object", {}).get("sha")}, indent=2)


@mcp.tool()
def commit_files(branch: str, commit_message: str, actions: str) -> str:
    """Commit file changes. actions: JSON array [{"action":"create|update|delete","file_path":"...","content":"..."}]"""
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
    """Create a pull request."""
    data = client.post(f"{R}/pulls", json={"head": source_branch, "base": target_branch, "title": title, "body": description}).json()
    return json.dumps({"number": data.get("number"), "html_url": data.get("html_url"), "title": data.get("title"), "state": data.get("state")}, indent=2)


@mcp.tool()
def get_pull_request(pr_number: str) -> str:
    """Get pull request details."""
    data = client.get(f"{R}/pulls/{pr_number}").json()
    return json.dumps({"number": data.get("number"), "title": data.get("title"), "state": data.get("state"), "head": data.get("head", {}).get("ref"), "base": data.get("base", {}).get("ref"), "html_url": data.get("html_url"), "body": data.get("body")}, indent=2)


@mcp.tool()
def update_pull_request(pr_number: str, title: str = "", description: str = "") -> str:
    """Update a pull request."""
    updates = {}
    if title:
        updates["title"] = title
    if description:
        updates["body"] = description
    data = client.patch(f"{R}/pulls/{pr_number}", json=updates).json()
    return json.dumps({"number": data.get("number"), "title": data.get("title"), "state": data.get("state")}, indent=2)


@mcp.tool()
def list_pr_comments(pr_number: str) -> str:
    """List all comments on a pull request."""
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
    """Post a comment on a pull request."""
    data = client.post(f"{R}/issues/{pr_number}/comments", json={"body": body}).json()
    return json.dumps({"id": data.get("id"), "body": data.get("body")}, indent=2)


@mcp.tool()
def get_file(file_path: str, ref: str = "main") -> str:
    """Read a file from the repository."""
    data = client.get(f"{R}/contents/{file_path}", params={"ref": ref}).json()
    return b64decode(data.get("content", "")).decode("utf-8")


if __name__ == "__main__":
    mcp.run()
