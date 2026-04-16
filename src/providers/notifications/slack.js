/**
 * @module providers/notifications/slack
 * @description Slack notification adapter.
 *
 * Sends notifications to a Slack channel via the Slack MCP or
 * by logging the message (when MCP is not available).
 */

const { NotificationBase } = require('../base/notification-base');
const logger = require('../../utils/logger');

class SlackAdapter extends NotificationBase {
  get name() { return 'slack'; }
  get label() { return 'Slack'; }

  async send(message, config) {
    const channel = config.channel || 'general';
    // In the agent context, Slack MCP handles delivery.
    // From the webhook server context, we log for now.
    // A full implementation would call the Slack API directly.
    logger.info(`[Slack -> #${channel}] ${message}`);
  }
}

module.exports = new SlackAdapter();
