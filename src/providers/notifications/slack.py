"""Slack notification adapter."""

import logging
from src.providers.base import NotificationBase

logger = logging.getLogger(__name__)


class SlackAdapter(NotificationBase):
    name = "slack"
    label = "Slack"

    async def send(self, message, config):
        channel = config.get("channel", "general")
        logger.info(f"[Slack -> #{channel}] {message}")


adapter = SlackAdapter()
