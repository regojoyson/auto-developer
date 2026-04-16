"""GitHub git provider adapter."""

from base64 import b64decode, b64encode
import httpx
from src.providers.base import GitProviderBase


class GitHubAdapter(GitProviderBase):
    name = "github"
    pr_label = "pull request"

    def parse_webhook(self, headers, payload, config):
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
        owner = env["GITHUB_OWNER"]
        repo = env["GITHUB_REPO"]
        client = httpx.Client(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {env['GITHUB_TOKEN']}", "Accept": "application/vnd.github.v3+json"},
        )
        r = f"/repos/{owner}/{repo}"

        class Api:
            def create_branch(self, name, ref="main"):
                ref_data = client.get(f"{r}/git/ref/heads/{ref}").json()
                sha = ref_data["object"]["sha"]
                return client.post(f"{r}/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha}).json()

            def commit_files(self, branch, message, actions):
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
                data = client.post(f"{r}/pulls", json={"head": source, "base": target, "title": title, "body": description}).json()
                return {"id": data.get("number"), "url": data.get("html_url"), "title": data.get("title"), "state": data.get("state")}

            def get_pr(self, pr_id):
                data = client.get(f"{r}/pulls/{pr_id}").json()
                return {"id": data.get("number"), "url": data.get("html_url"), "title": data.get("title"), "state": data.get("state"), "source_branch": data.get("head", {}).get("ref"), "description": data.get("body")}

            def update_pr(self, pr_id, updates):
                body = {}
                if "title" in updates:
                    body["title"] = updates["title"]
                if "description" in updates:
                    body["body"] = updates["description"]
                return client.patch(f"{r}/pulls/{pr_id}", json=body).json()

            def list_pr_comments(self, pr_id):
                issue = client.get(f"{r}/issues/{pr_id}/comments").json()
                review = client.get(f"{r}/pulls/{pr_id}/comments").json()
                all_comments = [
                    *[{"id": c["id"], "author": c.get("user", {}).get("login"), "body": c.get("body"), "created_at": c.get("created_at"), "system": False} for c in issue],
                    *[{"id": c["id"], "author": c.get("user", {}).get("login"), "body": c.get("body"), "created_at": c.get("created_at"), "system": False} for c in review],
                ]
                return sorted(all_comments, key=lambda x: x.get("created_at", ""))

            def post_pr_comment(self, pr_id, body):
                return client.post(f"{r}/issues/{pr_id}/comments", json={"body": body}).json()

            def get_file(self, file_path, ref="main"):
                data = client.get(f"{r}/contents/{file_path}", params={"ref": ref}).json()
                data["content"] = b64decode(data.get("content", "")).decode("utf-8")
                return data

        api = Api()
        self.validate_api(api)
        return api


adapter = GitHubAdapter()
