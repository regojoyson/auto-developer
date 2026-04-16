"""GitHub Issues issue tracker adapter.

Handles incoming GitHub webhook events by detecting when a specific label is
applied to an issue. Also provides methods for managing issue labels and
adding comments via the GitHub API, used by the pipeline runner.

The module exposes a singleton ``adapter`` instance at module level for
use by the issue tracker factory.
"""

import logging
import os

import requests

from src.providers.base import IssueTrackerBase

logger = logging.getLogger(__name__)


class GitHubIssuesAdapter(IssueTrackerBase):
    """Adapter that parses GitHub Issues webhook payloads and calls GitHub API.

    Webhook parsing listens for ``issues`` events with ``labeled`` action.
    API methods use GITHUB_TOKEN from environment variables.
    """

    name = "github-issues"
    event_label = "issue"

    def _api_headers(self):
        """Build authorization headers for GitHub API calls."""
        token = os.environ.get("GITHUB_TOKEN", "")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _parse_issue_key(self, issue_key):
        """Parse 'repo#123' into (full_repo, number)."""
        repo, number = issue_key.split("#")
        owner = os.environ.get("GITHUB_OWNER", "")
        return f"{owner}/{repo}", int(number)

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

    def transition_issue(self, issue_key, status_name):
        """Transition a GitHub issue by adding a label.

        For GitHub Issues, "status" is represented by labels. This method
        adds the target label.

        Args:
            issue_key: Issue key in "repo#123" format.
            status_name: Label name to add (e.g. "in-progress", "done").
        """
        repo_full, number = self._parse_issue_key(issue_key)
        headers = self._api_headers()
        resp = requests.post(
            f"https://api.github.com/repos/{repo_full}/issues/{number}/labels",
            headers=headers,
            json={"labels": [status_name]},
        )
        resp.raise_for_status()
        logger.info(f"Added label '{status_name}' to {issue_key}")

    def add_comment(self, issue_key, body):
        """Add a comment to a GitHub issue.

        Args:
            issue_key: Issue key in "repo#123" format.
            body: Comment text (Markdown supported).
        """
        repo_full, number = self._parse_issue_key(issue_key)
        headers = self._api_headers()
        resp = requests.post(
            f"https://api.github.com/repos/{repo_full}/issues/{number}/comments",
            headers=headers,
            json={"body": body},
        )
        resp.raise_for_status()
        logger.info(f"Posted comment on {issue_key}")


adapter = GitHubIssuesAdapter()
