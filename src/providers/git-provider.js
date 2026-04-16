/**
 * @module providers/git-provider
 * @description Factory that loads the configured git provider adapter.
 */

const config = require('../config');

let instance = null;

function getGitProvider() {
  if (instance) return instance;

  const gitConfig = config.gitProvider;
  let adapter;
  switch (gitConfig.type) {
    case 'gitlab':
      adapter = require('./git/gitlab');
      break;
    case 'github':
      adapter = require('./git/github');
      break;
    default:
      throw new Error(`Unknown git provider: "${gitConfig.type}". Supported: gitlab, github`);
  }

  instance = Object.create(adapter);
  instance.config = gitConfig;
  return instance;
}

function clearCache() { instance = null; }

module.exports = { getGitProvider, clearCache };
