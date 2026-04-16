/**
 * @module providers/cli-adapter
 * @description Factory that loads the configured CLI adapter.
 */

const config = require('../config');

let instance = null;

function getCliAdapter() {
  if (instance) return instance;

  const cliConfig = config.cliAdapter;
  let adapter;
  switch (cliConfig.type) {
    case 'claude-code':
      adapter = require('./cli/claude-code');
      break;
    case 'codex':
      adapter = require('./cli/codex');
      break;
    case 'gemini':
      adapter = require('./cli/gemini');
      break;
    default:
      throw new Error(`Unknown CLI adapter: "${cliConfig.type}". Supported: claude-code, codex, gemini`);
  }

  instance = Object.create(adapter);
  instance.config = cliConfig;
  return instance;
}

function clearCache() { instance = null; }

module.exports = { getCliAdapter, clearCache };
