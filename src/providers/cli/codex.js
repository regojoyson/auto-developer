/**
 * @module providers/cli/codex
 * @description OpenAI Codex CLI adapter.
 *
 * Invokes agents via: `codex --prompt <input> --full-auto`
 * Agent name is prepended to the input as context.
 */

const { CliAdapterBase } = require('../base/cli-adapter-base');

class CodexAdapter extends CliAdapterBase {
  get name() { return 'codex'; }
  get label() { return 'Codex CLI'; }
  get defaultCommand() { return 'codex'; }

  buildArgs(agentName, input, config) {
    // Codex doesn't have an --agent flag, so we prepend the agent role to the prompt
    const prompt = `[Agent: ${agentName}]\n${input}`;
    const args = ['--prompt', prompt, '--full-auto'];

    if (config.model) {
      args.push('--model', config.model);
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

module.exports = new CodexAdapter();
