/**
 * @module providers/cli/claude-code
 * @description Claude Code CLI adapter.
 *
 * Invokes agents via: `claude --agent <name> --print --input <json>`
 * Supports model selection and max turns configuration.
 */

const { CliAdapterBase } = require('../base/cli-adapter-base');

class ClaudeCodeAdapter extends CliAdapterBase {
  get name() { return 'claude-code'; }
  get label() { return 'Claude Code CLI'; }
  get defaultCommand() { return 'claude'; }
  get agentDir() { return '.claude/agents'; }
  get configDir() { return '.claude'; }

  buildArgs(agentName, input, config) {
    const args = ['--agent', agentName, '--print', '--input', input];

    if (config.model) {
      args.push('--model', config.model);
    }
    if (config.maxTurnsPerRun) {
      args.push('--max-turns', String(config.maxTurnsPerRun));
    }
    if (config.extraArgs && Array.isArray(config.extraArgs)) {
      args.push(...config.extraArgs);
    }

    return args;
  }

  parseOutput(stdout, stderr, exitCode) {
    return {
      success: exitCode === 0,
      output: stdout,
      error: exitCode !== 0 ? (stderr || `Exited with code ${exitCode}`) : null,
    };
  }
}

module.exports = new ClaudeCodeAdapter();
