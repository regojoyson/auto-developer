/**
 * @module providers/base/cli-adapter-base
 * @description Base class for AI coding CLI adapters.
 *
 * Every CLI adapter (Claude Code, Codex, Gemini, etc.) must extend this
 * and implement the abstract methods.
 *
 * The adapter pattern separates *what CLI to run* from *how to run it*.
 * The agent runner calls buildArgs() + buildEnv() to construct the
 * command, then parseOutput() to normalize the result.
 *
 * @example
 *   const { CliAdapterBase } = require('./base/cli-adapter-base');
 *
 *   class AiderAdapter extends CliAdapterBase {
 *     get name() { return 'aider'; }
 *     get label() { return 'Aider CLI'; }
 *     get defaultCommand() { return 'aider'; }
 *     buildArgs(agentName, input, config) { return ['--message', input]; }
 *     parseOutput(stdout, stderr, exitCode) { ... }
 *   }
 */

class CliAdapterBase {
  constructor() {
    const className = this.constructor.name;

    if (!this.name) {
      throw new Error(`${className}: must define "name" (e.g. 'claude-code', 'codex')`);
    }
    if (!this.label) {
      throw new Error(`${className}: must define "label" (e.g. 'Claude Code CLI')`);
    }
    if (!this.defaultCommand) {
      throw new Error(`${className}: must define "defaultCommand" (e.g. 'claude')`);
    }
  }

  /** @type {string} Adapter identifier. @abstract */
  get name() { return ''; }

  /** @type {string} Human-readable display name. @abstract */
  get label() { return ''; }

  /** @type {string} Default CLI command if not overridden in config. @abstract */
  get defaultCommand() { return ''; }

  /**
   * Build CLI arguments for invoking the agent.
   *
   * @param {string} agentName - Agent name (e.g. 'orchestrator', 'brainstorm')
   * @param {string} input - JSON string input to pass to the agent
   * @param {object} config - cliAdapter section from providers.json
   * @returns {string[]} Array of CLI arguments
   * @abstract
   */
  buildArgs(agentName, input, config) {
    throw new Error(`${this.constructor.name}: must implement buildArgs()`);
  }

  /**
   * Build environment variables for the agent process.
   * Default implementation: merge base env with config.env overrides.
   *
   * @param {object} baseEnv - Current process.env
   * @param {object} config - cliAdapter section from providers.json
   * @returns {object} Environment variables for the child process
   */
  buildEnv(baseEnv, config) {
    return { ...baseEnv, ...(config.env || {}) };
  }

  /**
   * Parse and normalize the agent's output.
   *
   * @param {string} stdout - Standard output from the CLI
   * @param {string} stderr - Standard error from the CLI
   * @param {number} exitCode - Process exit code
   * @returns {{ success: boolean, output: string, error: string|null }}
   * @abstract
   */
  parseOutput(stdout, stderr, exitCode) {
    throw new Error(`${this.constructor.name}: must implement parseOutput()`);
  }
}

module.exports = { CliAdapterBase };
