/**
 * @module providers/base/issue-tracker-base
 * @description Base class for issue tracker adapters.
 *
 * Every issue tracker adapter (Jira, GitHub Issues, Linear, etc.) must
 * extend this class and implement all methods marked with `throw`.
 *
 * The constructor validates that required properties are set,
 * so missing implementations fail fast at startup — not at runtime.
 *
 * @example
 *   const { IssueTrackerBase } = require('./base/issue-tracker-base');
 *
 *   class LinearAdapter extends IssueTrackerBase {
 *     get name() { return 'linear'; }
 *     get eventLabel() { return 'issue'; }
 *     parseWebhook(headers, payload, config) { ... }
 *   }
 */

class IssueTrackerBase {
  constructor() {
    const className = this.constructor.name;

    if (!this.name) {
      throw new Error(`${className}: must define "name" (e.g. 'jira', 'linear')`);
    }
    if (!this.eventLabel) {
      throw new Error(`${className}: must define "eventLabel" (e.g. 'ticket', 'issue')`);
    }
  }

  /**
   * Provider identifier.
   * @type {string}
   * @abstract
   */
  get name() { return ''; }

  /**
   * Human-readable label for a work item (used in agent prompts and logs).
   * @type {string}
   * @abstract
   */
  get eventLabel() { return ''; }

  /**
   * Parse an incoming webhook payload from this issue tracker.
   *
   * @param {object} headers - HTTP request headers
   * @param {object} payload - Webhook JSON body
   * @param {object} config - issueTracker section from config.yaml
   * @returns {{ issueKey: string, summary: string, component: string|null }|null}
   *   Parsed event data, or null if the event should be ignored.
   * @abstract
   */
  parseWebhook(headers, payload, config) {
    throw new Error(`${this.constructor.name}: must implement parseWebhook()`);
  }
}

module.exports = { IssueTrackerBase };
