"""Jira issue tracker adapter.

Handles incoming Jira webhooks by detecting status transitions on issues.
When an issue moves to the configured trigger status (e.g. "Ready for
Development"), the adapter extracts the issue key, summary, and first
component to kick off the automated pipeline.

The module exposes a singleton ``adapter`` instance at module level for
use by the issue tracker factory.
"""

from src.providers.base import IssueTrackerBase


class JiraAdapter(IssueTrackerBase):
    """Adapter that parses Jira webhook payloads for status change events.

    Looks for changelog entries where the ``status`` field changed to the
    value specified by ``config["trigger_status"]``. Ignores all other
    webhook events (comments, assignments, field edits, etc.).
    """

    name = "jira"
    event_label = "ticket"

    def parse_webhook(self, headers, payload, config):
        """Parse a Jira webhook payload for a matching status transition.

        Args:
            headers: HTTP request headers from the incoming webhook.
            payload: The JSON body of the Jira webhook event.
            config: The ``issue_tracker`` section from config.yaml, must
                contain a ``trigger_status`` key with the target status name.

        Returns:
            dict or None: A dict with keys ``issue_key`` (str), ``summary``
                (str), and ``component`` (str or None) if the webhook
                represents a status change to the trigger status. Returns
                None if the event should be ignored.
        """
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
