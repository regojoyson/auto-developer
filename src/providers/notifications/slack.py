"""Slack notification adapter.

Implements the :class:`~src.providers.base.NotificationBase` interface for
Slack. Currently logs messages at INFO level rather than making actual Slack
API calls -- intended as a placeholder for a real Slack integration (e.g.
via Slack Incoming Webhooks or the Slack Web API).

The module exposes a singleton ``adapter`` instance at module level for
use by the notification factory.
"""

import logging
from src.providers.base import NotificationBase

logger = logging.getLogger(__name__)


class SlackAdapter(NotificationBase):
    """Notification adapter that sends messages to a Slack channel.

    Currently a stub implementation that logs the message. Replace the
    ``send`` method body with a real Slack API call for production use.
    """

    name = "slack"
    label = "Slack"

    async def send(self, message, config):
        """Send a notification message to a Slack channel.

        Args:
            message: The notification text to send.
            config: The ``notification`` section from config.yaml. Uses
                the ``channel`` key to determine the target channel
                (defaults to ``"general"``).
        """
        channel = config.get("channel", "general")
        logger.info(f"[Slack -> #{channel}] {message}")


adapter = SlackAdapter()
