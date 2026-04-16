/**
 * @module state/manager
 * @description Pipeline state machine — tracks each ticket's lifecycle as a
 * JSON file per branch inside `.pipeline-state/`.
 *
 * State flow:
 * ```
 *   (new) --> brainstorming --> developing --> awaiting-review --> merged
 *                                                  |       ^
 *                                               reworking -+
 * ```
 *
 * Every agent invocation checks state before starting to prevent duplicates.
 * The rework counter is incremented on each `reworking` transition and used
 * to enforce the configurable rework cap (default 3).
 *
 * @example
 *   const { createState, transitionState, getState } = require('./state/manager');
 *   createState('feature/PROJ-1-login', 'PROJ-1');
 *   transitionState('feature/PROJ-1-login', 'developing');
 *   console.log(getState('feature/PROJ-1-login').state); // 'developing'
 */

const fs = require('fs');
const path = require('path');

/** @type {string} Directory for per-branch state JSON files */
const STATE_DIR = path.resolve(__dirname, '../../.pipeline-state');

/**
 * Allowed state transitions. Each key maps to an array of states it can move to.
 * @type {Record<string, string[]>}
 */
const VALID_TRANSITIONS = {
  brainstorming: ['developing'],
  developing: ['awaiting-review'],
  'awaiting-review': ['reworking', 'merged'],
  reworking: ['awaiting-review'],
};

/**
 * Convert a branch name to a safe filename by replacing slashes.
 * @param {string} branch - Git branch name (e.g. `feature/PROJ-1-slug`)
 * @returns {string} Filesystem-safe path
 */
function stateFilePath(branch) {
  const safeName = branch.replace(/\//g, '__');
  return path.join(STATE_DIR, `${safeName}.json`);
}

/** Create the state directory if it does not exist. */
function ensureStateDir() {
  if (!fs.existsSync(STATE_DIR)) {
    fs.mkdirSync(STATE_DIR, { recursive: true });
  }
}

/**
 * Read the current pipeline state for a branch.
 * @param {string} branch - Git branch name
 * @returns {PipelineState|null} State object or null if no state exists
 */
function getState(branch) {
  const filePath = stateFilePath(branch);
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

/**
 * Create an initial pipeline state for a new ticket/branch.
 * @param {string} branch - Git branch name
 * @param {string} issueKey - Issue key (e.g. `PROJ-123`)
 * @param {object} [repoInfo] - Optional repo context
 * @param {string} [repoInfo.repoPath] - Absolute path to the target repo directory
 * @returns {PipelineState} The newly created state (starts at `brainstorming`)
 */
function createState(branch, issueKey, repoInfo = {}) {
  ensureStateDir();
  const state = {
    branch,
    issueKey,
    state: 'brainstorming',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    reworkCount: 0,
    repoPath: repoInfo.repoPath || null,
  };
  fs.writeFileSync(stateFilePath(branch), JSON.stringify(state, null, 2));
  return state;
}

/**
 * Transition a branch's pipeline to a new state.
 * Throws if the transition is invalid per {@link VALID_TRANSITIONS}.
 * Increments `reworkCount` when transitioning to `reworking`.
 *
 * @param {string} branch - Git branch name
 * @param {string} newState - Target state
 * @returns {PipelineState} Updated state object
 * @throws {Error} If no state exists or transition is invalid
 */
function transitionState(branch, newState) {
  const current = getState(branch);
  if (!current) {
    throw new Error(`No pipeline state found for branch: ${branch}`);
  }

  const allowed = VALID_TRANSITIONS[current.state];
  if (!allowed || !allowed.includes(newState)) {
    throw new Error(
      `Invalid transition: ${current.state} → ${newState} (branch: ${branch})`
    );
  }

  current.state = newState;
  current.updatedAt = new Date().toISOString();

  if (newState === 'reworking') {
    current.reworkCount += 1;
  }

  fs.writeFileSync(stateFilePath(branch), JSON.stringify(current, null, 2));
  return current;
}

/**
 * Check whether the rework iteration cap has been reached.
 * @param {string} branch - Git branch name
 * @param {number} [maxRework=3] - Maximum allowed rework iterations
 * @returns {boolean} `true` if the limit is reached or exceeded
 */
function isReworkLimitExceeded(branch, maxRework = 3) {
  const current = getState(branch);
  if (!current) return false;
  return current.reworkCount >= maxRework;
}

/**
 * List all pipeline states across all branches.
 * Useful for dashboards or debugging.
 * @returns {PipelineState[]} Array of all state objects
 */
function listActiveStates() {
  ensureStateDir();
  const files = fs.readdirSync(STATE_DIR).filter(f => f.endsWith('.json'));
  return files.map(f => {
    const content = fs.readFileSync(path.join(STATE_DIR, f), 'utf-8');
    return JSON.parse(content);
  });
}

module.exports = {
  getState,
  createState,
  transitionState,
  isReworkLimitExceeded,
  listActiveStates,
  VALID_TRANSITIONS,
};
