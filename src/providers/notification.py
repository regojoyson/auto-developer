"""Factory — loads the notification adapter (returns None if not configured)."""

from src.config import config

_instance = ...  # sentinel: not loaded yet


def get_notification():
    global _instance
    if _instance is not ...:
        return _instance

    notif_config = config.get("notification")
    if not notif_config or not notif_config.get("type"):
        _instance = None
        return None

    adapter_type = notif_config["type"]

    if adapter_type == "slack":
        from src.providers.notifications.slack import adapter
    else:
        raise ValueError(f"Unknown notification type: '{adapter_type}'. Supported: slack")

    _instance = (adapter, notif_config)
    return _instance
