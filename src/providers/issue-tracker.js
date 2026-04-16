/**
 * @module providers/issue-tracker
 * @description Factory that loads the configured issue tracker adapter.
 */

const config = require('../config');

let instance = null;

function getIssueTracker() {
  if (instance) return instance;

  const trackerConfig = config.issueTracker;
  let adapter;
  switch (trackerConfig.type) {
    case 'jira':
      adapter = require('./trackers/jira');
      break;
    case 'github-issues':
      adapter = require('./trackers/github-issues');
      break;
    default:
      throw new Error(`Unknown issue tracker: "${trackerConfig.type}". Supported: jira, github-issues`);
  }

  instance = Object.create(adapter);
  instance.config = trackerConfig;
  return instance;
}

function clearCache() { instance = null; }

module.exports = { getIssueTracker, clearCache };
