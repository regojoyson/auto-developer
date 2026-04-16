#!/usr/bin/env node
/**
 * @module providers/cli-dirs
 * @description Tiny helper called by shell scripts to get CLI adapter directory paths.
 *
 * Usage from bash:
 *   AGENT_DIR=$(node src/providers/cli-dirs.js agentDir)
 *   CONFIG_DIR=$(node src/providers/cli-dirs.js configDir)
 */

const { getCliAdapter } = require('./cli-adapter');

const field = process.argv[2];
const adapter = getCliAdapter();

if (field === 'agentDir') {
  console.log(adapter.agentDir);
} else if (field === 'configDir') {
  console.log(adapter.configDir);
} else if (field === 'rulesFileName') {
  console.log(adapter.rulesFileName);
} else {
  console.error('Usage: node cli-dirs.js agentDir|configDir|rulesFileName');
  process.exit(1);
}
