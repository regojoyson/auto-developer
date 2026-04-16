"""GitLab git provider adapter."""

from urllib.parse import quote
from base64 import b64decode
import httpx
from src.providers.base import GitProviderBase


class GitLabAdapter(GitProviderBase):
    name = "gitlab"
    pr_label = "merge request"

    def parse_webhook(self, headers, payload, config):
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
            }

        return None

    def create_api(self, env):
        base_url = env.get("GITLAB_BASE_URL", "https://gitlab.com").rstrip("/")
        project_id = env["GITLAB_PROJECT_ID"]
        client = httpx.Client(
            base_url=f"{base_url}/api/v4",
            headers={"PRIVATE-TOKEN": env["GITLAB_TOKEN"], "Content-Type": "application/json"},
        )
        p = f"/projects/{project_id}"

        class Api:
            def create_branch(self, name, ref="main"):
                return client.post(f"{p}/repository/branches", json={"branch": name, "ref": ref}).json()

            def commit_files(self, branch, message, actions):
                return client.post(f"{p}/repository/commits", json={"branch": branch, "commit_message": message, "actions": actions}).json()

            def create_pr(self, source, target, title, description):
                r = client.post(f"{p}/merge_requests", json={"source_branch": source, "target_branch": target, "title": title, "description": description}).json()
                return {"id": r.get("iid"), "url": r.get("web_url"), "title": r.get("title"), "state": r.get("state")}

            def get_pr(self, pr_id):
                r = client.get(f"{p}/merge_requests/{pr_id}").json()
                return {"id": r.get("iid"), "url": r.get("web_url"), "title": r.get("title"), "state": r.get("state"), "source_branch": r.get("source_branch"), "description": r.get("description")}

            def update_pr(self, pr_id, updates):
                return client.put(f"{p}/merge_requests/{pr_id}", json=updates).json()

            def list_pr_comments(self, pr_id):
                data = client.get(f"{p}/merge_requests/{pr_id}/notes", params={"sort": "asc", "order_by": "created_at"}).json()
                return [{"id": n["id"], "author": n.get("author", {}).get("username"), "body": n.get("body"), "created_at": n.get("created_at"), "system": n.get("system")} for n in data]

            def post_pr_comment(self, pr_id, body):
                return client.post(f"{p}/merge_requests/{pr_id}/notes", json={"body": body}).json()

            def get_file(self, file_path, ref="main"):
                encoded = quote(file_path, safe="")
                r = client.get(f"{p}/repository/files/{encoded}", params={"ref": ref}).json()
                r["content"] = b64decode(r.get("content", "")).decode("utf-8")
                return r

        api = Api()
        self.validate_api(api)
        return api


adapter = GitLabAdapter()
