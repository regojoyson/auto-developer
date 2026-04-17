"""GitLab git provider adapter.

Implements the :class:`~src.providers.base.GitProviderBase` interface for
GitLab. Handles three webhook event types:

- **Merge Request Hook** -- detects MR approvals.
- **Push Hook** -- detects pushes to branches (filters out bot users).
- **Note Hook** -- detects comments on merge requests (filters out bots).

Also provides a full API client (via :meth:`GitLabAdapter.create_api`) that
wraps the GitLab REST API v4 for branch management, commits, merge requests,
comments, and file retrieval.

The module exposes a singleton ``adapter`` instance at module level for
use by the git provider factory.
"""

from urllib.parse import quote
from base64 import b64decode
import httpx
from src.providers.base import GitProviderBase


class GitLabAdapter(GitProviderBase):
    """Adapter for GitLab webhook parsing and REST API access.

    Parses incoming GitLab webhook events (merge request approvals, pushes,
    and MR comments) and provides a REST API client for interacting with
    the GitLab project (branches, commits, merge requests, file reads).
    """

    name = "gitlab"
    pr_label = "merge request"

    def parse_webhook(self, headers, payload, config):
        """Parse a GitLab webhook payload into a normalized event dict.

        Handles three GitLab event types: Merge Request Hook (approval),
        Push Hook (code push), and Note Hook (MR comment). Bot users
        listed in ``config["bot_users"]`` are filtered out for push and
        comment events.

        Args:
            headers: HTTP request headers. Must contain ``x-gitlab-event``
                to identify the event type.
            payload: The JSON body of the GitLab webhook event.
            config: The ``git_provider`` section from config.yaml. May
                contain ``bot_users`` (list of usernames to ignore).

        Returns:
            dict or None: A dict with keys ``event`` (``"approved"``,
                ``"push"``, or ``"comment"``), ``branch`` (str), ``pr_id``
                (int or None), and ``author`` (str). Returns None if the
                event does not match any recognized type or is from a bot.
        """
        event_type = headers.get("x-gitlab-event")
        bot_users = config.get("bot_users", [])

        if event_type == "Merge Request Hook":
            if payload.get("object_attributes", {}).get("action") != "approved":
                return None
            return {
                "event": "approved",
                "branch": payload.get("object_attributes", {}).get("source_branch"),
                "pr_id": payload.get("object_attributes", {}).get("iid"),
                "author": payload.get("user", {}).get("username", ""),
                "project_id": payload.get("project", {}).get("id"),
            }

        if event_type == "Push Hook":
            author = payload.get("user_username", "")
            if author in bot_users:
                return None
            ref = payload.get("ref", "")
            return {
                "event": "push",
                "branch": ref.replace("refs/heads/", ""),
                "pr_id": None,
                "author": author,
                "project_id": payload.get("project", {}).get("id"),
            }

        if event_type == "Note Hook":
            attrs = payload.get("object_attributes", {})
            if attrs.get("noteable_type") != "MergeRequest":
                return None
            author = attrs.get("author", {}).get("username", "")
            if author in bot_users:
                return None
            return {
                "event": "comment",
                "branch": payload.get("merge_request", {}).get("source_branch"),
                "pr_id": payload.get("merge_request", {}).get("iid"),
                "author": author,
                "project_id": payload.get("project", {}).get("id"),
            }

        return None

    def create_api(self, env, repo_dir: str | None = None):
        """Create a GitLab REST API client.

        If GITLAB_PROJECT_ID is set in env, uses it directly. Otherwise
        derives the project ID from the repo's git remote URL via the
        GitLab API.

        Args:
            env: Environment variables dict. Required: ``GITLAB_TOKEN``.
                Optional: ``GITLAB_BASE_URL``, ``GITLAB_PROJECT_ID``.
            repo_dir: Path to the repo (used to derive project ID from
                git remote if GITLAB_PROJECT_ID is not set).

        Returns:
            Api: An object implementing all required git provider methods.
        """
        base_url = env.get("GITLAB_BASE_URL", "https://gitlab.com").rstrip("/")

        # Derive project ID from git remote if not set
        project_id = env.get("GITLAB_PROJECT_ID")
        if not project_id and repo_dir:
            from src.repos.git_remote import get_remote_info
            info = get_remote_info(repo_dir, "gitlab")
            project_id = info.get("project_id")
        if not project_id:
            raise ValueError("GITLAB_PROJECT_ID not set and could not be derived from git remote")
        client = httpx.Client(
            base_url=f"{base_url}/api/v4",
            headers={"PRIVATE-TOKEN": env["GITLAB_TOKEN"], "Content-Type": "application/json"},
        )
        p = f"/projects/{project_id}"

        class Api:
            """Inner API client wrapping GitLab REST v4 endpoints."""

            def create_branch(self, name, ref="main"):
                """Create a new branch from a reference.

                Args:
                    name: Name for the new branch.
                    ref: Source branch or commit SHA to branch from.

                Returns:
                    dict: GitLab branch creation response.
                """
                return client.post(f"{p}/repository/branches", json={"branch": name, "ref": ref}).json()

            def commit_files(self, branch, message, actions):
                """Commit one or more file changes to a branch.

                Args:
                    branch: Target branch name.
                    message: Commit message.
                    actions: List of action dicts, each with keys
                        ``action`` (create/update/delete), ``file_path``,
                        and ``content``.

                Returns:
                    dict: GitLab commit response.
                """
                return client.post(f"{p}/repository/commits", json={"branch": branch, "commit_message": message, "actions": actions}).json()

            def create_pr(self, source, target, title, description):
                """Create a merge request.

                Args:
                    source: Source branch name.
                    target: Target branch name.
                    title: Merge request title.
                    description: Merge request description body.

                Returns:
                    dict: Normalized MR dict with keys ``id``, ``url``,
                        ``title``, and ``state``.
                """
                r = client.post(f"{p}/merge_requests", json={"source_branch": source, "target_branch": target, "title": title, "description": description}).json()
                return {"id": r.get("iid"), "url": r.get("web_url"), "title": r.get("title"), "state": r.get("state")}

            def get_pr(self, pr_id):
                """Retrieve merge request details by IID.

                Args:
                    pr_id: The merge request internal ID (IID).

                Returns:
                    dict: Normalized MR dict with keys ``id``, ``url``,
                        ``title``, ``state``, ``source_branch``, and
                        ``description``.
                """
                r = client.get(f"{p}/merge_requests/{pr_id}").json()
                return {"id": r.get("iid"), "url": r.get("web_url"), "title": r.get("title"), "state": r.get("state"), "source_branch": r.get("source_branch"), "description": r.get("description")}

            def update_pr(self, pr_id, updates):
                """Update a merge request's fields.

                Args:
                    pr_id: The merge request internal ID (IID).
                    updates: Dict of fields to update (e.g. ``title``,
                        ``description``).

                Returns:
                    dict: Updated merge request response.
                """
                return client.put(f"{p}/merge_requests/{pr_id}", json=updates).json()

            def list_pr_comments(self, pr_id):
                """List all comments (notes) on a merge request.

                Args:
                    pr_id: The merge request internal ID (IID).

                Returns:
                    list[dict]: Comments sorted by creation date, each with
                        keys ``id``, ``author``, ``body``, ``created_at``,
                        and ``system``.
                """
                data = client.get(f"{p}/merge_requests/{pr_id}/notes", params={"sort": "asc", "order_by": "created_at"}).json()
                return [{"id": n["id"], "author": n.get("author", {}).get("username"), "body": n.get("body"), "created_at": n.get("created_at"), "system": n.get("system")} for n in data]

            def post_pr_comment(self, pr_id, body):
                """Post a comment on a merge request.

                Args:
                    pr_id: The merge request internal ID (IID).
                    body: Comment text.

                Returns:
                    dict: Created note response.
                """
                return client.post(f"{p}/merge_requests/{pr_id}/notes", json={"body": body}).json()

            def get_file(self, file_path, ref="main"):
                """Read a file's content from the repository.

                Args:
                    file_path: Path to the file within the repository.
                    ref: Branch name, tag, or commit SHA to read from.

                Returns:
                    dict: File metadata dict with decoded ``content`` field.
                """
                encoded = quote(file_path, safe="")
                r = client.get(f"{p}/repository/files/{encoded}", params={"ref": ref}).json()
                r["content"] = b64decode(r.get("content", "")).decode("utf-8")
                return r

        api = Api()
        self.validate_api(api)
        return api


adapter = GitLabAdapter()
