/**
 * @module providers/cli/gemini
 * @description Gemini CLI adapter.
 *
 * Invokes agents via: `gemini --prompt <input>`
 * Agent name is prepended to the input as context.
 */

const { CliAdapterBase } = require('../base/cli-adapter-base');

class GeminiAdapter extends CliAdapterBase {
  get name() { return 'gemini'; }
  get label() { return 'Gemini CLI'; }
  get defaultCommand() { return 'gemini'; }
  get agentDir() { return '.gemini/agents'; }
  get configDir() { return '.gemini'; }
  get rulesFileName() { return 'GEMINI.md'; }

  buildArgs(agentName, input, config) {
    const prompt = `[Agent: ${agentName}]\n${input}`;
    const args = ['--prompt', prompt];

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

module.exports = new GeminiAdapter();
