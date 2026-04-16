/**
 * @module providers/trackers/jira
 * @description Jira issue tracker adapter.
 *
 * Parses Jira `issue_updated` webhooks and extracts issue context
 * when the status transitions to the configured trigger status.
 */

const { IssueTrackerBase } = require('../base/issue-tracker-base');

class JiraAdapter extends IssueTrackerBase {
  get name() { return 'jira'; }
  get eventLabel() { return 'ticket'; }

  parseWebhook(headers, payload, config) {
    const changelog = payload.changelog;
    if (!changelog || !changelog.items) return null;

    const statusChange = changelog.items.find((item) => item.field === 'status');
    if (!statusChange) return null;

    const newStatus = statusChange.toString || '';
    if (newStatus !== config.triggerStatus) return null;

    const issueKey = payload.issue?.key;
    if (!issueKey) return null;

    return {
      issueKey,
      summary: payload.issue?.fields?.summary || '',
      component: payload.issue?.fields?.components?.[0]?.name || null,
    };
  }
}

module.exports = new JiraAdapter();
