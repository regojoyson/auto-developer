"""Factory — loads the configured issue tracker adapter."""

from src.config import config

_instance = None


def get_issue_tracker():
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
