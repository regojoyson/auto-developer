/**
 * @module webhook/routes/git-provider
 * @description Unified webhook handler for any git provider (GitLab, GitHub, etc.).
 *
 * Delegates payload parsing to the configured adapter from config.yaml.
 * Routes three event types:
 *   - approved → transition to merged, notify
 *   - push    → log human edit, wait
 *   - comment → invoke feedback parser, rework cycle
 */

const { Router } = require('express');
const logger = require('../../utils/logger');
const { getState, transitionState, isReworkLimitExceeded } = require('../../state/manager');
const { runAgent } = require('../../agents/runner');
const { getGitProvider } = require('../../providers/git-provider');
const config = require('../../config');

const router = Router();

router.post('/', async (req, res) => {
  try {
    const git = getGitProvider();
    const parsed = git.parseWebhook(req.headers, req.body, git.config);

    if (!parsed) {
      logger.debug('Git provider webhook ignored (no matching event)');
      return res.status(200).json({ ignored: true });
    }

    const { event, branch, prId, author } = parsed;

    switch (event) {
      case 'approved':
        await handleApproved(branch, prId);
        break;
      case 'push':
        handlePush(branch, author);
        break;
      case 'comment':
        await handleComment(branch, prId);
        break;
    }

    res.status(200).json({ received: true });
  } catch (err) {
    logger.error(`Git provider webhook error: ${err.message}`);
    res.status(500).json({ error: 'Internal server error' });
  }
});

/** Branch A — PR/MR approved. */
async function handleApproved(branch, prId) {
  const state = getState(branch);
  if (!state) return;

  logger.info(`PR approved for ${state.issueKey} (${branch})`);
  transitionState(branch, 'merged');

  const input = JSON.stringify({
    action: 'merge-approved',
    issueKey: state.issueKey,
    branch,
    prId,
  });
  runAgent('orchestrator', input, { cwd: state.repoPath || process.cwd() }).catch((err) => {
    logger.error(`Post-merge orchestrator failed: ${err.message}`);
  });
}

/** Branch B — Human push detected. */
function handlePush(branch, author) {
  const state = getState(branch);
  if (!state) return;
  logger.info(`Human push detected on ${branch} by ${author}`);
}

/** Branch C — Review comment received. */
async function handleComment(branch, prId) {
  // For providers where branch is null in comments (GitHub), look up from state by prId
  let resolvedBranch = branch;
  if (!resolvedBranch) {
    const allStates = require('../../state/manager').listActiveStates();
    const match = allStates.find(s => s.prId === prId);
    if (match) resolvedBranch = match.branch;
  }
  if (!resolvedBranch) return;

  const state = getState(resolvedBranch);
  if (!state || state.state !== 'awaiting-review') {
    logger.debug(`Ignoring comment: pipeline not in awaiting-review for ${resolvedBranch}`);
    return;
  }

  const maxRework = config.pipeline.maxReworkIterations;
  if (isReworkLimitExceeded(resolvedBranch, maxRework)) {
    logger.warn(`Rework limit exceeded for ${state.issueKey} — escalating`);
    const input = JSON.stringify({
      action: 'rework-limit-exceeded',
      issueKey: state.issueKey,
      branch: resolvedBranch,
      reworkCount: state.reworkCount,
    });
    runAgent('orchestrator', input, { cwd: state.repoPath || process.cwd() }).catch((err) => {
      logger.error(`Rework escalation failed: ${err.message}`);
    });
    return;
  }

  logger.info(`Review comment received for ${state.issueKey}, invoking feedback parser`);
  const input = JSON.stringify({
    issueKey: state.issueKey,
    branch: resolvedBranch,
    prId,
  });
  runAgent('feedback-parser', input, { cwd: state.repoPath || process.cwd() }).catch((err) => {
    logger.error(`Feedback parser agent failed: ${err.message}`);
  });
}

module.exports = router;
