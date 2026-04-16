"""Factory for loading the configured issue tracker adapter.

Reads the ``issue_tracker.type`` field from the application configuration and
lazily imports the corresponding adapter module (Jira or GitHub Issues). The
adapter instance is cached as a module-level singleton so subsequent calls
return the same object without re-importing.

Usage::

    adapter, tracker_config = get_issue_tracker()
    parsed = adapter.parse_webhook(headers, payload, tracker_config)
"""

from src.config import config

_instance = None


def get_issue_tracker():
    """Return the issue tracker adapter and its configuration.

    On first call, reads ``config["issue_tracker"]["type"]`` to determine
    which adapter to load, imports the corresponding module, and caches the
    result. Subsequent calls return the cached instance immediately.

    Returns:
        tuple: A 2-tuple of ``(adapter, tracker_config)`` where *adapter* is
            an :class:`~src.providers.base.IssueTrackerBase` instance and
            *tracker_config* is the ``issue_tracker`` section of config.yaml.

    Raises:
        ValueError: If the configured adapter type is not one of the
            supported values (``jira``, ``github-issues``).
    """
    global _instance
    if _instance:
        return _instance

    tracker_config = config["issue_tracker"]
    adapter_type = tracker_config["type"]

    if adapter_type == "jira":
        from src.providers.trackers.jira import adapter
    elif adapter_type == "github-issues":
        from src.providers.trackers.github_issues import adapter
    else:
        raise ValueError(f"Unknown issue tracker: '{adapter_type}'. Supported: jira, github-issues")

    _instance = (adapter, tracker_config)
    return _instance
