/**
 * @module providers/trackers/github-issues
 * @description GitHub Issues adapter.
 *
 * Parses GitHub `issues` webhooks. Triggers when an issue is labeled
 * with a label matching the configured trigger status.
 */

const { IssueTrackerBase } = require('../base/issue-tracker-base');

class GitHubIssuesAdapter extends IssueTrackerBase {
  get name() { return 'github-issues'; }
  get eventLabel() { return 'issue'; }

  parseWebhook(headers, payload, config) {
    const event = headers['x-github-event'];
    if (event !== 'issues') return null;

    const action = payload.action;
    const issue = payload.issue;
    if (!issue) return null;

    if (action === 'labeled') {
      const label = payload.label?.name;
      if (label !== config.triggerStatus) return null;

      const repo = payload.repository?.name || '';
      return {
        issueKey: `${repo}#${issue.number}`,
        summary: issue.title || '',
        component: null,
      };
    }

    return null;
  }
}

module.exports = new GitHubIssuesAdapter();
