/**
 * @module config
 * @description Unified configuration loader.
 *
 * Reads `config.yaml` once and exports all config sections.
 * Every module in the pipeline imports from here — no more
 * scattered JSON files.
 *
 * Secrets (tokens, keys) stay in `.env` and are accessed
 * via `process.env` directly by the modules that need them.
 *
 * @example
 *   const config = require('./config');
 *   console.log(config.repo.mode);          // 'dir'
 *   console.log(config.gitProvider.type);    // 'gitlab'
 *   console.log(config.notification);        // null if not configured
 */

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

const CONFIG_PATH = path.resolve(__dirname, '../config.yaml');

let cached = null;

function load() {
  if (cached) return cached;

  if (!fs.existsSync(CONFIG_PATH)) {
    throw new Error(
      `config.yaml not found at ${CONFIG_PATH}.\n` +
      'Run ./setup.sh to generate it, or create it manually (see docs/configuration.md).'
    );
  }

  const raw = yaml.load(fs.readFileSync(CONFIG_PATH, 'utf-8'));

  cached = {
    repo: {
      mode: raw.repo?.mode || 'dir',
      path: raw.repo?.path || null,
      urls: raw.repo?.urls || [],
      cloneDir: raw.repo?.cloneDir || '/tmp/auto-pilot-repos',
      baseBranch: raw.repo?.baseBranch || 'main',
    },

    issueTracker: {
      type: raw.issueTracker?.type || 'jira',
      triggerStatus: raw.issueTracker?.triggerStatus || 'Ready for Development',
      doneStatus: raw.issueTracker?.doneStatus || 'Done',
      botUsers: raw.issueTracker?.botUsers || [],
    },

    gitProvider: {
      type: raw.gitProvider?.type || 'gitlab',
      botUsers: raw.gitProvider?.botUsers || [],
    },

    cliAdapter: {
      type: raw.cliAdapter?.type || 'claude-code',
      model: raw.cliAdapter?.model || null,
      maxTurnsPerRun: raw.cliAdapter?.maxTurnsPerRun || null,
      timeout: raw.cliAdapter?.timeout || 300000,
      command: raw.cliAdapter?.command || null,
      extraArgs: raw.cliAdapter?.extraArgs || [],
      env: raw.cliAdapter?.env || {},
    },

    notification: raw.notification ? {
      type: raw.notification.type,
      channel: raw.notification.channel || null,
    } : null,

    pipeline: {
      maxReworkIterations: raw.pipeline?.maxReworkIterations ?? 3,
      agentTimeout: raw.pipeline?.agentTimeout ?? 300000,
      port: raw.pipeline?.port ?? 3000,
    },
  };

  return cached;
}

/** Clear cache — for tests or config reload. */
function reload() {
  cached = null;
  return load();
}

// Load on first require
const config = load();

module.exports = config;
module.exports.reload = reload;
