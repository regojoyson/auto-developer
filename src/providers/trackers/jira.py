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


def _extract_adf_text(adf_body):
    """Extract plain text from Atlassian Document Format (ADF) JSON."""
    if not adf_body or not isinstance(adf_body, dict):
        return str(adf_body) if adf_body else ""
    texts = []
    for node in adf_body.get("content", []):
        for inline in node.get("content", []):
            if inline.get("type") == "text":
                texts.append(inline.get("text", ""))
    return "\n".join(texts)


def _extract_field_text(field_value):
    """Extract text from a Jira field that might be ADF, string, or None."""
    if field_value is None:
        return ""
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, dict):
        return _extract_adf_text(field_value)
    return str(field_value)


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
        """Parse a Jira webhook payload for a matching event.

        Recognises two event types:
        - ``trigger``: a status transition to the configured trigger status
          (e.g. "Ready for Development"). Starts a fresh pipeline run.
        - ``comment``: a new comment on an existing ticket. The route uses
          this to detect replies on blocked tickets and resume the pipeline.

        Args:
            headers: HTTP request headers from the incoming webhook.
            payload: The JSON body of the Jira webhook event.
            config: The ``issue_tracker`` section from config.yaml; must
                contain a ``trigger_status`` key.

        Returns:
            dict or None:
                ``{"event_type": "trigger", "issue_key", "summary", "component"}``
                or ``{"event_type": "comment", "issue_key", "comment_body",
                "comment_author"}``, or None if the event should be ignored.
        """
        issue = payload.get("issue", {})
        issue_key = issue.get("key")
        if not issue_key:
            return None

        event = payload.get("webhookEvent", "")

        # ── Comment event (used for resume-from-blocked) ────
        if event in ("comment_created", "jira:issue_commented") or "comment" in payload:
            comment = payload.get("comment") or {}
            body = comment.get("body", "")
            if isinstance(body, dict):
                body = _extract_adf_text(body)
            author = comment.get("author", {}).get("displayName", "")
            if body:
                return {
                    "event_type": "comment",
                    "issue_key": issue_key,
                    "comment_body": body,
                    "comment_author": author,
                }

        # ── Status transition (trigger) ─────────────────────
        changelog = payload.get("changelog", {})
        items = changelog.get("items", [])
        status_change = next((i for i in items if i.get("field") == "status"), None)
        if not status_change:
            return None

        new_status = status_change.get("toString", "")
        if new_status != config["trigger_status"]:
            return None

        fields = issue.get("fields", {})
        components = fields.get("components", [])
        return {
            "event_type": "trigger",
            "issue_key": issue_key,
            "summary": fields.get("summary", ""),
            "component": components[0]["name"] if components else None,
        }

    def read_issue(self, issue_key):
        """Read full issue details from Jira via REST API.

        Fetches all fields including custom fields, comments, and linked issues.

        Args:
            issue_key: Jira issue key (e.g. "EV-14942").

        Returns:
            Dict with structured ticket data.
        """
        base = self._base_url()
        headers = self._api_headers()

        # Try v3 first, fall back to v2
        for api_ver in ["3", "2"]:
            resp = requests.get(
                f"{base}/rest/api/{api_ver}/issue/{issue_key}",
                headers=headers,
                params={"expand": "renderedFields"},
            )
            if resp.status_code == 200:
                break

        self._check_response(resp, "read issue", issue_key)

        try:
            data = resp.json()
        except Exception:
            raise RuntimeError(f"Jira returned non-JSON for {issue_key}: HTTP {resp.status_code}")

        fields = data.get("fields", {})

        # Extract linked issues
        linked = []
        for link in fields.get("issuelinks", []):
            if link.get("outwardIssue"):
                linked.append({
                    "key": link["outwardIssue"]["key"],
                    "summary": link["outwardIssue"]["fields"]["summary"],
                    "relation": link.get("type", {}).get("outward", "relates to"),
                })
            if link.get("inwardIssue"):
                linked.append({
                    "key": link["inwardIssue"]["key"],
                    "summary": link["inwardIssue"]["fields"]["summary"],
                    "relation": link.get("type", {}).get("inward", "relates to"),
                })

        # Extract comments
        comments = []
        for c in fields.get("comment", {}).get("comments", []):
            author = c.get("author", {}).get("displayName", "Unknown")
            body = c.get("body", "")
            # ADF body — extract text content
            if isinstance(body, dict):
                body = _extract_adf_text(body)
            comments.append({"author": author, "body": body})

        # Extract attachments
        attachments = []
        for a in fields.get("attachment", []):
            attachments.append({
                "filename": a.get("filename", ""),
                "mimeType": a.get("mimeType", ""),
                "size": a.get("size", 0),
            })

        return {
            "key": issue_key,
            "summary": fields.get("summary", ""),
            "description": _extract_field_text(fields.get("description")),
            "status": fields.get("status", {}).get("name", ""),
            "priority": fields.get("priority", {}).get("name", ""),
            "labels": fields.get("labels", []),
            "components": [c.get("name", "") for c in fields.get("components", [])],
            "linked_issues": linked,
            "comments": comments,
            "attachments": attachments,
            "acceptance_criteria": _extract_field_text(fields.get("customfield_10037")),  # common AC field
            "raw_fields": fields,  # pass all fields for the agent to inspect
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
