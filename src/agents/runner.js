/**
 * @module agents/runner
 * @description Spawns Claude Code CLI agent processes.
 *
 * Each agent is defined as a Markdown file in `.claude/agents/<name>.md`.
 * This module spawns `claude --agent <name> --print --input <json>` as a
 * child process, captures stdout/stderr, and enforces a configurable timeout.
 *
 * The timeout defaults to 5 minutes (`AGENT_TIMEOUT_MS` env var).
 * On timeout the child is SIGTERM-killed and the promise rejects.
 *
 * In multi-repo setups, pass `options.cwd` to the target repo directory
 * so the agent reads that repo's codebase for context. The repo path is
 * resolved by the `repos/resolver` module from `repos.json`.
 *
 * Environment variables (`GITLAB_PROJECT_ID`, `GITLAB_BASE_URL`, etc.) can
 * be overridden per-invocation via `options.env` — the resolver provides
 * these from the repo config.
 *
 * @example
 *   const { runAgent } = require('./agents/runner');
 *
 *   // Single repo (uses process.cwd)
 *   await runAgent('orchestrator', '{"issueKey":"PROJ-1"}');
 *
 *   // Multi repo (explicit cwd + env overrides)
 *   await runAgent('orchestrator', '{"issueKey":"FRONT-1"}', {
 *     cwd: '/projects/frontend-app',
 *     env: { GITLAB_PROJECT_ID: '67890' },
 *   });
 */

const { spawn } = require('child_process');
const logger = require('../utils/logger');

const DEFAULT_TIMEOUT_MS = parseInt(process.env.AGENT_TIMEOUT_MS || '300000', 10);

/**
 * Invoke a Claude Code agent via the CLI.
 *
 * @param {string} agentName - Name of the agent (matches .claude/agents/<name>.md)
 * @param {string} input - Text input/prompt to send to the agent
 * @param {object} [options]
 * @param {string} [options.cwd] - Working directory for the agent process (repo root)
 * @param {number} [options.timeoutMs] - Timeout in milliseconds
 * @param {object} [options.env] - Additional env vars to merge (e.g. GITLAB_PROJECT_ID override)
 * @returns {Promise<{exitCode: number, stdout: string, stderr: string}>}
 */
function runAgent(agentName, input, options = {}) {
  const { cwd = process.cwd(), timeoutMs = DEFAULT_TIMEOUT_MS, env = {} } = options;

  return new Promise((resolve, reject) => {
    const args = ['--agent', agentName, '--print', '--input', input];

    logger.info(`Invoking agent: ${agentName}`, { cwd, timeoutMs });

    const child = spawn('claude', args, {
      cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, ...env },
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (data) => {
      stdout += data.toString();
    });

    child.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    const timer = setTimeout(() => {
      child.kill('SIGTERM');
      reject(new Error(`Agent ${agentName} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.on('close', (exitCode) => {
      clearTimeout(timer);
      logger.info(`Agent ${agentName} exited with code ${exitCode}`);
      if (stderr) {
        logger.warn(`Agent ${agentName} stderr: ${stderr.slice(0, 500)}`);
      }
      resolve({ exitCode, stdout, stderr });
    });

    child.on('error', (err) => {
      clearTimeout(timer);
      reject(new Error(`Failed to spawn agent ${agentName}: ${err.message}`));
    });
  });
}

module.exports = { runAgent };
