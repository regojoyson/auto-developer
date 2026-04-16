"""GitHub git provider adapter.

Implements the :class:`~src.providers.base.GitProviderBase` interface for
GitHub. Handles four webhook event types:

- **pull_request_review** -- detects PR approvals.
- **pull_request** -- detects merged PRs (treated as approvals).
- **push** -- detects pushes to branches (filters out bot users).
- **issue_comment / pull_request_review_comment** -- detects PR comments.

Also provides a full API client (via :meth:`GitHubAdapter.create_api`) that
wraps the GitHub REST API v3 for branch management, commits, pull requests,
comments, and file retrieval.

The module exposes a singleton ``adapter`` instance at module level for
use by the git provider factory.
"""

from base64 import b64decode, b64encode
import httpx
from src.providers.base import GitProviderBase


class GitHubAdapter(GitProviderBase):
    """Adapter for GitHub webhook parsing and REST API access.

    Parses incoming GitHub webhook events (PR approvals, merges, pushes,
    and PR comments) and provides a REST API client for interacting with
    the GitHub repository (branches, commits, pull requests, file reads).
    """

    name = "github"
    pr_label = "pull request"

    def parse_webhook(self, headers, payload, config):
        """Parse a GitHub webhook payload into a normalized event dict.

        Handles GitHub event types: pull_request_review (approval),
        pull_request (merge), push, issue_comment, and
        pull_request_review_comment. Bot users listed in
        ``config["bot_users"]`` are filtered out for push and comment events.

        Args:
            headers: HTTP request headers. Must contain ``x-github-event``
                to identify the event type.
            payload: The JSON body of the GitHub webhook event.
            config: The ``git_provider`` section from config.yaml. May
                contain ``bot_users`` (list of usernames to ignore).

        Returns:
            dict or None: A dict with keys ``event`` (``"approved"``,
                ``"push"``, or ``"comment"``), ``branch`` (str or None),
                ``pr_id`` (int or None), and ``author`` (str). Returns
                None if the event does not match or is from a bot.
        """
        event = headers.get("x-github-event")
        bot_users = config.get("bot_users", [])

        if event == "pull_request_review":
            if payload.get("review", {}).get("state") != "approved":
                return None
            return {
                "event": "approved",
                "branch": payload.get("pull_request", {}).get("head", {}).get("ref"),
                "pr_id": payload.get("pull_request", {}).get("number"),
                "author": payload.get("review", {}).get("user", {}).get("login", ""),
            }

        if event == "pull_request":
            pr = payload.get("pull_request", {})
            if payload.get("action") == "closed" and pr.get("merged"):
                return {
                    "event": "approved",
                    "branch": pr.get("head", {}).get("ref"),
                    "pr_id": pr.get("number"),
                    "author": payload.get("sender", {}).get("login", ""),
                }
            return None

        if event == "push":
            author = payload.get("sender", {}).get("login", "")
            if author in bot_users:
                return None
            return {
                "event": "push",
                "branch": payload.get("ref", "").replace("refs/heads/", ""),
                "pr_id": None,
                "author": author,
            }

        if event in ("issue_comment", "pull_request_review_comment"):
            if event == "issue_comment" and not payload.get("issue", {}).get("pull_request"):
                return None
            author = payload.get("comment", {}).get("user", {}).get("login", "")
            if author in bot_users:
                return None
            return {
                "event": "comment",
                "branch": None,
                "pr_id": payload.get("issue", {}).get("number") or payload.get("pull_request", {}).get("number"),
                "author": author,
            }

        return None

    def create_api(self, env):
        """Create a GitHub REST API client.

        Builds an authenticated httpx client targeting the GitHub API v3
        and returns an inner ``Api`` object that implements all required
        git provider methods.

        Args:
            env: Environment variables dict. Required keys:
                ``GITHUB_TOKEN``, ``GITHUB_OWNER``, ``GITHUB_REPO``.

        Returns:
            Api: An object implementing all methods defined in
                :attr:`GitProviderBase.REQUIRED_API_METHODS`.

        Raises:
            NotImplementedError: If the returned Api object is missing
                any required method (checked by ``validate_api``).
            KeyError: If required environment variables are missing.
        """
        owner = env["GITHUB_OWNER"]
        repo = env["GITHUB_REPO"]
        client = httpx.Client(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {env['GITHUB_TOKEN']}", "Accept": "application/vnd.github.v3+json"},
        )
        r = f"/repos/{owner}/{repo}"

        class Api:
            """Inner API client wrapping GitHub REST v3 endpoints."""

            def create_branch(self, name, ref="main"):
                """Create a new branch from a reference.

                Resolves the SHA of the ref branch and creates a new git
                reference pointing to the same commit.

                Args:
                    name: Name for the new branch.
                    ref: Source branch to branch from.

                Returns:
                    dict: GitHub ref creation response.
                """
                ref_data = client.get(f"{r}/git/ref/heads/{ref}").json()
                sha = ref_data["object"]["sha"]
                return client.post(f"{r}/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha}).json()

            def commit_files(self, branch, message, actions):
                """Commit one or more file changes to a branch.

                Processes each action sequentially using the GitHub Contents
                API. Supports create, update, and delete operations.

                Args:
                    branch: Target branch name.
                    message: Commit message.
                    actions: List of action dicts, each with keys
                        ``action`` (create/update/delete), ``file_path``,
                        and ``content``.

                Returns:
                    dict: A dict with the commit ``message``.
                """
                for action in actions:
                    if action["action"] == "delete":
                        existing = client.get(f"{r}/contents/{action['file_path']}", params={"ref": branch}).json()
                        client.request("DELETE", f"{r}/contents/{action['file_path']}", json={"message": message, "branch": branch, "sha": existing["sha"]})
                    else:
                        sha = None
                        try:
                            existing = client.get(f"{r}/contents/{action['file_path']}", params={"ref": branch}).json()
                            sha = existing.get("sha")
                        except Exception:
                            pass
                        body = {"message": message, "branch": branch, "content": b64encode((action.get("content") or "").encode()).decode()}
                        if sha:
                            body["sha"] = sha
                        client.put(f"{r}/contents/{action['file_path']}", json=body)
                return {"message": message}

            def create_pr(self, source, target, title, description):
                """Create a pull request.

                Args:
                    source: Head branch name.
                    target: Base branch name.
                    title: Pull request title.
                    description: Pull request body text.

                Returns:
                    dict: Normalized PR dict with keys ``id``, ``url``,
                        ``title``, and ``state``.
                """
                data = client.post(f"{r}/pulls", json={"head": source, "base": target, "title": title, "body": description}).json()
                return {"id": data.get("number"), "url": data.get("html_url"), "title": data.get("title"), "state": data.get("state")}

            def get_pr(self, pr_id):
                """Retrieve pull request details by number.

                Args:
                    pr_id: The pull request number.

                Returns:
                    dict: Normalized PR dict with keys ``id``, ``url``,
                        ``title``, ``state``, ``source_branch``, and
                        ``description``.
                """
                data = client.get(f"{r}/pulls/{pr_id}").json()
                return {"id": data.get("number"), "url": data.get("html_url"), "title": data.get("title"), "state": data.get("state"), "source_branch": data.get("head", {}).get("ref"), "description": data.get("body")}

            def update_pr(self, pr_id, updates):
                """Update a pull request's title or description.

                Args:
                    pr_id: The pull request number.
                    updates: Dict with optional keys ``title`` and/or
                        ``description``.

                Returns:
                    dict: Updated pull request response.
                """
                body = {}
                if "title" in updates:
                    body["title"] = updates["title"]
                if "description" in updates:
                    body["body"] = updates["description"]
                return client.patch(f"{r}/pulls/{pr_id}", json=body).json()

            def list_pr_comments(self, pr_id):
                """List all comments on a pull request.

                Merges both issue comments and review comments into a
                single list sorted by creation date.

                Args:
                    pr_id: The pull request number.

                Returns:
                    list[dict]: Comments sorted by ``created_at``, each
                        with keys ``id``, ``author``, ``body``,
                        ``created_at``, and ``system``.
                """
                issue = client.get(f"{r}/issues/{pr_id}/comments").json()
                review = client.get(f"{r}/pulls/{pr_id}/comments").json()
                all_comments = [
                    *[{"id": c["id"], "author": c.get("user", {}).get("login"), "body": c.get("body"), "created_at": c.get("created_at"), "system": False} for c in issue],
                    *[{"id": c["id"], "author": c.get("user", {}).get("login"), "body": c.get("body"), "created_at": c.get("created_at"), "system": False} for c in review],
                ]
                return sorted(all_comments, key=lambda x: x.get("created_at", ""))

            def post_pr_comment(self, pr_id, body):
                """Post a comment on a pull request.

                Args:
                    pr_id: The pull request number.
                    body: Comment text.

                Returns:
                    dict: Created comment response.
                """
                return client.post(f"{r}/issues/{pr_id}/comments", json={"body": body}).json()

            def get_file(self, file_path, ref="main"):
                """Read a file's content from the repository.

                Args:
                    file_path: Path to the file within the repository.
                    ref: Branch name, tag, or commit SHA to read from.

                Returns:
                    dict: File metadata dict with decoded ``content`` field.
                """
                data = client.get(f"{r}/contents/{file_path}", params={"ref": ref}).json()
                data["content"] = b64decode(data.get("content", "")).decode("utf-8")
                return data

        api = Api()
        self.validate_api(api)
        return api


adapter = GitHubAdapter()
