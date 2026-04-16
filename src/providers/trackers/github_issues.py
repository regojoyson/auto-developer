"""GitHub Issues adapter."""

from src.providers.base import IssueTrackerBase


class GitHubIssuesAdapter(IssueTrackerBase):
    name = "github-issues"
    event_label = "issue"

    def parse_webhook(self, headers, payload, config):
        event = headers.get("x-github-event")
        if event != "issues":
            return None

        if payload.get("action") != "labeled":
            return None

        label_name = payload.get("label", {}).get("name")
        if label_name != config["trigger_status"]:
            return None

        issue = payload.get("issue", {})
        repo_name = payload.get("repository", {}).get("name", "")
        return {
            "issue_key": f"{repo_name}#{issue.get('number', '')}",
            "summary": issue.get("title", ""),
            "component": None,
        }


adapter = GitHubIssuesAdapter()
