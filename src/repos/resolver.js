/**
 * @module repos/resolver
 * @description Resolves which repo directory to run agents in.
 *
 * Two modes configured in `repos.json`:
 *
 * **"multi"** — A parent directory where every subdirectory is a repo.
 *   The agent runs in whichever subdirectory name matches the Jira ticket
 *   context, or the caller specifies the repo name explicitly.
 *
 * **"single"** — One repo directory. All tickets use it.
 *
 * @example repos.json (multi-repo)
 *   { "mode": "multi", "multi": { "parentDir": "/projects" } }
 *   // /projects/frontend-app/, /projects/backend-api/, etc.
 *
 * @example repos.json (single repo / mono-repo)
 *   { "mode": "single", "single": { "repoDir": "/projects/my-app" } }
 */

const fs = require('fs');
const path = require('path');

const REPOS_CONFIG_PATH = path.resolve(__dirname, '../../repos.json');

/** @type {object|null} Cached parsed config */
let configCache = null;

/**
 * Load and cache repos.json.
 * @returns {object} Parsed config
 */
function loadConfig() {
  if (configCache) return configCache;

  if (!fs.existsSync(REPOS_CONFIG_PATH)) {
    throw new Error(
      `repos.json not found at ${REPOS_CONFIG_PATH}. Create it — see README for format.`
    );
  }

  configCache = JSON.parse(fs.readFileSync(REPOS_CONFIG_PATH, 'utf-8'));
  return configCache;
}

/** Clear the cached config (for tests). */
function clearCache() {
  configCache = null;
}

/**
 * Get the repo directory for a given repo name.
 *
 * - In **single** mode: always returns the configured `repoDir`, `repoName` is ignored.
 * - In **multi** mode: returns `<parentDir>/<repoName>`.
 *
 * @param {string} [repoName] - Subdirectory name (only used in multi mode)
 * @returns {string} Absolute path to the repo directory
 */
function getRepoDir(repoName) {
  const config = loadConfig();

  if (config.mode === 'single') {
    const dir = config.single?.repoDir;
    if (!dir) throw new Error('repos.json: "single.repoDir" is required in single mode');
    return dir;
  }

  // multi mode
  const parentDir = config.multi?.parentDir;
  if (!parentDir) throw new Error('repos.json: "multi.parentDir" is required in multi mode');

  if (!repoName) {
    // No specific repo requested — return parentDir itself
    // (caller can list subdirectories to pick one)
    return parentDir;
  }

  return path.join(parentDir, repoName);
}

/**
 * Get the parent directory (multi mode) or the single repo dir.
 * @returns {string} The base directory path
 */
function getBaseDir() {
  const config = loadConfig();
  if (config.mode === 'single') {
    return config.single?.repoDir;
  }
  return config.multi?.parentDir;
}

/**
 * List all repo directories.
 * - Single mode: returns the one configured directory.
 * - Multi mode: lists subdirectories of parentDir.
 * @returns {string[]} Array of absolute repo paths
 */
function listRepos() {
  const config = loadConfig();

  if (config.mode === 'single') {
    return [config.single.repoDir];
  }

  const parentDir = config.multi?.parentDir;
  if (!parentDir || !fs.existsSync(parentDir)) return [];

  return fs.readdirSync(parentDir, { withFileTypes: true })
    .filter(d => d.isDirectory() && !d.name.startsWith('.'))
    .map(d => path.join(parentDir, d.name));
}

/**
 * Check if running in single or multi mode.
 * @returns {'single'|'multi'}
 */
function getMode() {
  return loadConfig().mode || 'single';
}

module.exports = { getRepoDir, getBaseDir, listRepos, getMode, clearCache };
