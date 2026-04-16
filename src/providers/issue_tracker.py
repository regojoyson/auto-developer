"""Factory for loading the configured issue tracker adapter.

Reads the ``issue_tracker`` section from config and loads the corresponding
adapter based on the ``platform`` field (jira or github-issues). The adapter
provides webhook parsing, and in API mode, also provides read_issue(),
transition_issue(), and add_comment() methods.

Usage::

    adapter, tracker_config = get_issue_tracker()
    parsed = adapter.parse_webhook(headers, payload, tracker_config)

    # In API mode:
    if tracker_config["api_mode"] == "api":
        ticket = adapter.read_issue("EV-14942")
        adapter.transition_issue("EV-14942", "Development")
        adapter.add_comment("EV-14942", "Pipeline started")
"""

from src.config import config

_instance = None


def get_issue_tracker():
    """Return the issue tracker adapter and its configuration.

    On first call, reads ``config["issue_tracker"]["platform"]`` to determine
    which adapter to load, imports the corresponding module, and caches the
    result.

    Returns:
        tuple: A 2-tuple of ``(adapter, tracker_config)`` where *adapter* is
            an :class:`~src.providers.base.IssueTrackerBase` instance and
            *tracker_config* is the ``issue_tracker`` section of config.

    Raises:
        ValueError: If the configured platform is not supported.
    """
    global _instance
    if _instance:
        return _instance

    tracker_config = config["issue_tracker"]
    platform = tracker_config["platform"]

    if platform == "jira":
        from src.providers.trackers.jira import adapter
    elif platform == "github-issues":
        from src.providers.trackers.github_issues import adapter
    else:
        raise ValueError(f"Unknown issue tracker platform: '{platform}'. Supported: jira, github-issues")

    _instance = (adapter, tracker_config)
    return _instance


def is_api_mode():
    """Check if the issue tracker is in API mode (Python REST calls).

    Returns:
        True if api_mode == "api", False if "mcp".
    """
    return config["issue_tracker"]["api_mode"] == "api"
