/**
 * @module providers/base/notification-base
 * @description Base class for notification adapters.
 *
 * Every notification adapter (Slack, Teams, etc.) must extend this
 * and implement the `send()` method.
 *
 * Notifications are optional — if not configured, the factory returns null.
 */

class NotificationBase {
  constructor() {
    const className = this.constructor.name;
    if (!this.name) throw new Error(`${className}: must define "name"`);
    if (!this.label) throw new Error(`${className}: must define "label"`);
  }

  /** @type {string} @abstract */
  get name() { return ''; }

  /** @type {string} @abstract */
  get label() { return ''; }

  /**
   * Send a notification message.
   * @param {string} message - Message text
   * @param {object} config - notification section from config.yaml
   * @returns {Promise<void>}
   * @abstract
   */
  async send(message, config) {
    throw new Error(`${this.constructor.name}: must implement send()`);
  }
}

module.exports = { NotificationBase };
