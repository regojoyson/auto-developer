/**
 * @module repos/resolver
 * @description Resolves repo directories from config.yaml.
 *
 * Three modes:
 *   - **dir**: one local repo directory
 *   - **parentDir**: parent directory where each subdirectory is a repo
 *   - **clone**: one or more git URLs, cloned on first use
 *
 * Also handles `baseBranch` and `prepareRepo()` to ensure the local
 * repo is on the latest base branch before agents start working.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const config = require('../config');
const logger = require('../utils/logger');

/**
 * Get the repo directory for a given component name.
 *
 * - **dir**: always returns config.repo.path (component ignored)
 * - **parentDir**: returns `<path>/<component>` or `<path>` if no component
 * - **clone**: clones URLs into cloneDir, returns the matching repo dir
 *
 * @param {string} [component] - Subdirectory or repo name (for parentDir/clone modes)
 * @returns {string} Absolute path to the repo directory
 */
function getRepoDir(component) {
  const { mode } = config.repo;

  if (mode === 'dir') {
    return config.repo.path;
  }

  if (mode === 'parentDir') {
    if (!component) return config.repo.path;
    return path.join(config.repo.path, component);
  }

  if (mode === 'clone') {
    const cloneDir = config.repo.cloneDir;
    if (!fs.existsSync(cloneDir)) {
      fs.mkdirSync(cloneDir, { recursive: true });
    }

    // Clone all URLs that haven't been cloned yet
    for (const url of config.repo.urls) {
      const repoName = path.basename(url, '.git');
      const targetDir = path.join(cloneDir, repoName);
      if (!fs.existsSync(targetDir)) {
        logger.info(`Cloning ${url} into ${targetDir}`);
        execSync(`git clone ${url} ${targetDir}`, { stdio: 'inherit' });
      }
    }

    // If one URL, return it directly
    if (config.repo.urls.length === 1) {
      const repoName = path.basename(config.repo.urls[0], '.git');
      return path.join(cloneDir, repoName);
    }

    // Multiple URLs — pick by component or return cloneDir
    if (component) {
      return path.join(cloneDir, component);
    }
    return cloneDir;
  }

  throw new Error(`Unknown repo mode: "${mode}". Supported: dir, parentDir, clone`);
}

/**
 * Get the configured base branch.
 * @returns {string} Base branch name (e.g. 'main', 'master', 'develop')
 */
function getBaseBranch() {
  return config.repo.baseBranch;
}

/**
 * Prepare a repo for a new ticket — stash any uncommitted changes,
 * checkout baseBranch, reset to origin, and pull latest.
 *
 * This ensures a clean state before creating a feature branch, even if
 * a previous agent run left uncommitted changes or the local branch
 * diverged from origin.
 *
 * @param {string} repoDir - Absolute path to the repo directory
 */
function prepareRepo(repoDir) {
  const baseBranch = getBaseBranch();
  logger.info(`Preparing repo: stash, checkout ${baseBranch}, reset to origin`, { repoDir });

  const run = (cmd) => {
    try {
      return execSync(cmd, { cwd: repoDir, stdio: 'pipe' }).toString().trim();
    } catch (err) {
      return null;
    }
  };

  // 1. Stash any uncommitted changes (so checkout doesn't fail)
  const stashResult = run('git stash --include-untracked');
  if (stashResult && !stashResult.includes('No local changes')) {
    logger.info('Stashed uncommitted changes');
  }

  // 2. Checkout baseBranch
  if (run(`git checkout ${baseBranch}`) === null) {
    logger.warn(`Failed to checkout ${baseBranch} — branch may not exist`);
    return;
  }

  // 3. Fetch latest from origin
  run('git fetch origin');

  // 4. Reset local branch to match origin (discard local-only commits)
  if (run(`git reset --hard origin/${baseBranch}`) === null) {
    // Fallback: just pull if reset fails (e.g. no remote tracking)
    run('git pull');
  }

  logger.info(`Repo ready on ${baseBranch} (synced with origin)`);
}

/**
 * List all repo directories.
 * @returns {string[]}
 */
function listRepos() {
  const { mode } = config.repo;

  if (mode === 'dir') {
    return [config.repo.path];
  }

  if (mode === 'parentDir') {
    const parentDir = config.repo.path;
    if (!parentDir || !fs.existsSync(parentDir)) return [];
    return fs.readdirSync(parentDir, { withFileTypes: true })
      .filter(d => d.isDirectory() && !d.name.startsWith('.'))
      .map(d => path.join(parentDir, d.name));
  }

  if (mode === 'clone') {
    const cloneDir = config.repo.cloneDir;
    return config.repo.urls.map(url => {
      const repoName = path.basename(url, '.git');
      return path.join(cloneDir, repoName);
    });
  }

  return [];
}

/**
 * Get the mode from config.
 * @returns {'dir'|'parentDir'|'clone'}
 */
function getMode() {
  return config.repo.mode;
}

module.exports = { getRepoDir, getBaseBranch, prepareRepo, listRepos, getMode };
