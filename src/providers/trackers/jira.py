"""Jira issue tracker adapter.

Handles incoming Jira webhooks by detecting status transitions on issues.
Also provides methods for transitioning issues and adding comments via
the Jira REST API, used by the pipeline runner for status updates.

The module exposes a singleton ``adapter`` instance at module level for
use by the issue tracker factory.
"""

import logging
import os

import requests

from src.providers.base import IssueTrackerBase

logger = logging.getLogger(__name__)


class JiraAdapter(IssueTrackerBase):
    """Adapter that parses Jira webhook payloads and calls Jira REST API.

    Webhook parsing looks for changelog entries where the ``status`` field
    changed to the configured trigger status. API methods use JIRA_BASE_URL
    and JIRA_TOKEN from environment variables.
    """

    name = "jira"
    event_label = "ticket"

    def _api_headers(self):
        """Build authorization headers for Jira REST API calls."""
        token = os.environ.get("JIRA_TOKEN", "")
        email = os.environ.get("JIRA_EMAIL", "")
        if email:
            import base64
            creds = base64.b64encode(f"{email}:{token}".encode()).decode()
            return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _base_url(self):
        """Get the Jira base URL from environment."""
        return os.environ.get("JIRA_BASE_URL", "https://jira.atlassian.com").rstrip("/")

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

    def _check_response(self, resp, action, issue_key):
        """Check API response and raise with details on failure."""
        if resp.status_code >= 400:
            body_preview = resp.text[:300] if resp.text else "(empty)"
            raise RuntimeError(
                f"Jira API {action} failed for {issue_key}: "
                f"HTTP {resp.status_code} — {body_preview}"
            )

    def transition_issue(self, issue_key, status_name):
        """Transition a Jira issue to a new status.

        Fetches available transitions, finds the one matching status_name,
        and applies it via POST. Tries API v3 first, falls back to v2.

        Args:
            issue_key: Jira issue key (e.g. "EV-14942").
            status_name: Target status name (e.g. "Development").
        """
        base = self._base_url()
        headers = self._api_headers()

        # Try v3 first, fall back to v2 (some Jira instances only support v2)
        for api_ver in ["3", "2"]:
            url = f"{base}/rest/api/{api_ver}/issue/{issue_key}/transitions"
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                break
        else:
            self._check_response(resp, "get transitions", issue_key)

        try:
            transitions = resp.json().get("transitions", [])
        except Exception:
            raise RuntimeError(
                f"Jira API returned non-JSON for {issue_key} transitions: "
                f"HTTP {resp.status_code} — {resp.text[:200]}"
            )

        match = next((t for t in transitions if t["name"] == status_name), None)
        if not match:
            # Also try matching by "to" status name (some Jira configs use this)
            match = next((t for t in transitions if t.get("to", {}).get("name") == status_name), None)
        if not match:
            available = [f"{t['name']} (→ {t.get('to', {}).get('name', '?')})" for t in transitions]
            raise ValueError(
                f"No transition to '{status_name}' for {issue_key}. "
                f"Available transitions: {available}"
            )

        resp = requests.post(
            f"{base}/rest/api/{api_ver}/issue/{issue_key}/transitions",
            headers=headers,
            json={"transition": {"id": match["id"]}},
        )
        self._check_response(resp, "apply transition", issue_key)
        logger.info(f"Transitioned {issue_key} to '{status_name}' (via {match['name']})")

    def add_comment(self, issue_key, body):
        """Add a comment to a Jira issue.

        Tries API v3 (ADF format) first, falls back to v2 (plain text).

        Args:
            issue_key: Jira issue key (e.g. "EV-14942").
            body: Comment text.
        """
        base = self._base_url()
        headers = self._api_headers()

        # Try v3 with ADF format
        resp = requests.post(
            f"{base}/rest/api/3/issue/{issue_key}/comment",
            headers=headers,
            json={"body": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": body}]}
            ]}},
        )

        # Fall back to v2 with plain text if v3 fails
        if resp.status_code >= 400:
            logger.info(f"Jira API v3 comment failed ({resp.status_code}), trying v2...")
            resp = requests.post(
                f"{base}/rest/api/2/issue/{issue_key}/comment",
                headers=headers,
                json={"body": body},
            )

        self._check_response(resp, "add comment", issue_key)
        logger.info(f"Posted comment on {issue_key}")


adapter = JiraAdapter()
