/**
 * @module agents/runner
 * @description Spawns AI coding CLI agent processes using the configured adapter.
 *
 * The CLI adapter (Claude Code, Codex, Gemini, etc.) is selected via
 * `providers.json` → `cliAdapter.type`. The adapter handles argument
 * construction and output parsing — this module handles process lifecycle.
 *
 * @example
 *   const { runAgent } = require('./agents/runner');
 *   const result = await runAgent('orchestrator', '{"issueKey":"PROJ-1"}');
 *   console.log(result.success, result.output);
 */

const { spawn } = require('child_process');
const logger = require('../utils/logger');
const { getCliAdapter } = require('../providers/cli-adapter');
const appConfig = require('../config');

/**
 * Invoke an agent via the configured CLI adapter.
 *
 * @param {string} agentName - Name of the agent (e.g. 'orchestrator', 'brainstorm')
 * @param {string} input - JSON string input to pass to the agent
 * @param {object} [options]
 * @param {string} [options.cwd] - Working directory for the agent process (repo root)
 * @param {number} [options.timeoutMs] - Timeout in milliseconds
 * @param {object} [options.env] - Additional env vars to merge
 * @returns {Promise<{success: boolean, output: string, error: string|null, exitCode: number}>}
 */
function runAgent(agentName, input, options = {}) {
  const { cwd = process.cwd(), timeoutMs, env = {} } = options;

  const adapter = getCliAdapter();
  const config = adapter.config;
  const timeout = timeoutMs || config.timeout || appConfig.pipeline.agentTimeout;
  const command = config.command || adapter.defaultCommand;
  const args = adapter.buildArgs(agentName, input, config);
  const childEnv = adapter.buildEnv({ ...process.env, ...env }, config);

  return new Promise((resolve, reject) => {
    logger.info(`Invoking agent: ${agentName} via ${adapter.label}`, { command, cwd, timeout });

    const child = spawn(command, args, {
      cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: childEnv,
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
      reject(new Error(`Agent ${agentName} timed out after ${timeout}ms`));
    }, timeout);

    child.on('close', (exitCode) => {
      clearTimeout(timer);
      const result = adapter.parseOutput(stdout, stderr, exitCode);
      logger.info(`Agent ${agentName} exited with code ${exitCode}`, { success: result.success });
      if (stderr) {
        logger.warn(`Agent ${agentName} stderr: ${stderr.slice(0, 500)}`);
      }
      resolve({ ...result, exitCode });
    });

    child.on('error', (err) => {
      clearTimeout(timer);
      reject(new Error(`Failed to spawn agent ${agentName} (${command}): ${err.message}`));
    });
  });
}

module.exports = { runAgent };
