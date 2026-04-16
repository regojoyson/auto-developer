"""Factory for loading the notification adapter.

Reads the optional ``notification`` section from the application configuration.
If notifications are not configured (missing or empty ``type``), returns
``None``. Otherwise lazily imports the corresponding adapter module (currently
only Slack) and caches it.

Unlike other factories, this one uses an ellipsis sentinel (``...``) instead
of ``None`` to distinguish "not yet loaded" from "explicitly disabled".

Usage::

    result = get_notification()
    if result:
        adapter, notif_config = result
        await adapter.send("Pipeline complete", notif_config)
"""

from src.config import config

_instance = ...  # sentinel: not loaded yet


def get_notification():
    """Return the notification adapter and config, or None if disabled.

    On first call, checks whether a ``notification`` section with a ``type``
    key exists in the config. If not, caches and returns ``None``. Otherwise
    imports the matching adapter module and caches the result.

    Returns:
        tuple or None: A 2-tuple of ``(adapter, notif_config)`` where
            *adapter* is a :class:`~src.providers.base.NotificationBase`
            instance and *notif_config* is the ``notification`` section of
            config.yaml. Returns ``None`` if notifications are not configured.

    Raises:
        ValueError: If the configured notification type is not one of the
            supported values (``slack``).
    """
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
