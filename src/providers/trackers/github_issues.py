"""GitHub Issues issue tracker adapter.

Handles incoming GitHub webhook events by detecting when a specific label is
applied to an issue. When the label matches the configured trigger status
(e.g. "ready-for-dev"), the adapter extracts the issue number, title, and
repository name to kick off the automated pipeline.

The module exposes a singleton ``adapter`` instance at module level for
use by the issue tracker factory.
"""

from src.providers.base import IssueTrackerBase


class GitHubIssuesAdapter(IssueTrackerBase):
    """Adapter that parses GitHub Issues webhook payloads for label events.

    Listens for the ``issues`` event type with an ``action`` of ``labeled``,
    and checks whether the applied label matches the configured trigger
    status. Ignores all other GitHub event types and actions.
    """

    name = "github-issues"
    event_label = "issue"

    def parse_webhook(self, headers, payload, config):
        """Parse a GitHub Issues webhook payload for a matching label event.

        Args:
            headers: HTTP request headers. Must contain ``x-github-event``
                to identify the event type.
            payload: The JSON body of the GitHub webhook event.
            config: The ``issue_tracker`` section from config.yaml, must
                contain a ``trigger_status`` key with the target label name.

        Returns:
            dict or None: A dict with keys ``issue_key`` (str, formatted as
                ``repo#number``), ``summary`` (str), and ``component``
                (always None for GitHub Issues) if the webhook represents
                the trigger label being applied. Returns None otherwise.
        """
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
