"""Jira issue tracker adapter."""

from src.providers.base import IssueTrackerBase


class JiraAdapter(IssueTrackerBase):
    name = "jira"
    event_label = "ticket"

    def parse_webhook(self, headers, payload, config):
        changelog = payload.get("changelog", {})
        items = changelog.get("items", [])
        if not items:
            return None

        status_change = next((i for i in items if i.get("field") == "status"), None)
        if not status_change:
            return None

        new_status = status_change.get("toString", "")
        if new_status != config["trigger_status"]:
            return None

        issue = payload.get("issue", {})
        issue_key = issue.get("key")
        if not issue_key:
            return None

        fields = issue.get("fields", {})
        components = fields.get("components", [])
        return {
            "issue_key": issue_key,
            "summary": fields.get("summary", ""),
            "component": components[0]["name"] if components else None,
        }


adapter = JiraAdapter()
