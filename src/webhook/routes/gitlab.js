/**
 * @module webhook/routes/gitlab
 * @description Handles incoming GitLab webhooks (POST /webhooks/gitlab).
 *
 * Routes three event types to the corresponding review-loop branch:
 *
 * | Event                   | Filter                        | Action (branch)          |
 * |-------------------------|-------------------------------|--------------------------|
 * | Merge Request Hook      | `action == "approved"`        | A — merge & close ticket |
 * | Push Hook               | MR branch, non-bot author     | B — log human edit, wait |
 * | Note Hook               | Human MR comment              | C — feedback + rework    |
 *
 * Bot-authored comments and non-MR notes are silently ignored.
 * The rework cap (env `MAX_REWORK_ITERATIONS`, default 3) is enforced
 * before invoking the feedback parser — if exceeded, escalation is sent
 * via the orchestrator agent.
 */

const { Router } = require('express');
const logger = require('../../utils/logger');
const { getState, transitionState, isReworkLimitExceeded } = require('../../state/manager');
const { runAgent } = require('../../agents/runner');

const router = Router();

/** @type {string[]} GitLab usernames to treat as bots (comments ignored) */
const BOT_AUTHORS = ['project_bot', 'ghost', 'ci-bot'];

/**
 * POST / — GitLab webhook entry point.
 * Event type is read from the `x-gitlab-event` header.
 */
router.post('/', async (req, res) => {
  try {
    const eventType = req.headers['x-gitlab-event'];
    const payload = req.body;

    logger.info(`GitLab webhook received: ${eventType}`);

    switch (eventType) {
      case 'Merge Request Hook':
        await handleMergeRequest(payload);
        break;
      case 'Push Hook':
        await handlePush(payload);
        break;
      case 'Note Hook':
        await handleNote(payload);
        break;
      default:
        logger.debug(`Ignoring GitLab event: ${eventType}`);
    }

    res.status(200).json({ received: true });
  } catch (err) {
    logger.error(`GitLab webhook handler error: ${err.message}`);
    res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * Branch A — Handle MR approval.
 * Transitions state to `merged`, then invokes the orchestrator to close
 * the Jira ticket and send a Slack notification.
 * @param {object} payload - GitLab Merge Request Hook payload
 */
async function handleMergeRequest(payload) {
  const action = payload.object_attributes?.action;
  const sourceBranch = payload.object_attributes?.source_branch;

  if (action !== 'approved') {
    logger.debug(`Ignoring MR action: ${action}`);
    return;
  }

  const state = getState(sourceBranch);
  if (!state) {
    logger.debug(`No pipeline state for branch: ${sourceBranch}`);
    return;
  }

  logger.info(`MR approved for ${state.issueKey} (${sourceBranch})`);

  // Branch A: Approve
  transitionState(sourceBranch, 'merged');

  // Transition Jira ticket and notify Slack (done by orchestrator)
  const input = JSON.stringify({
    action: 'merge-approved',
    issueKey: state.issueKey,
    branch: sourceBranch,
    mrIid: payload.object_attributes?.iid,
  });

  // Run in the correct repo directory (stored in pipeline state)
  runAgent('orchestrator', input, {
    cwd: state.repoPath || process.cwd(),
  }).catch((err) => {
    logger.error(`Post-merge orchestrator failed: ${err.message}`);
  });
}

/**
 * Branch B — Detect human edits pushed to the MR branch.
 * No agent action is taken; the pipeline simply waits for re-approval.
 * @param {object} payload - GitLab Push Hook payload
 */
async function handlePush(payload) {
  const branch = (payload.ref || '').replace('refs/heads/', '');
  const authorUsername = payload.user_username || '';

  const state = getState(branch);
  if (!state) return;

  // Ignore bot pushes
  if (BOT_AUTHORS.includes(authorUsername)) return;

  // Branch B: Human edit detected
  logger.info(`Human push detected on ${branch} by ${authorUsername}`);

  // No agent action — pipeline waits for reviewer approval
  // Could optionally update MR description
}

/**
 * Branch C — Handle reviewer feedback (MR comment).
 * Checks the rework limit, then invokes the feedback-parser agent to
 * produce FEEDBACK.md. The developer agent is subsequently re-invoked
 * by the orchestrator after the parser finishes.
 * @param {object} payload - GitLab Note Hook payload
 */
async function handleNote(payload) {
  const noteableType = payload.object_attributes?.noteable_type;
  if (noteableType !== 'MergeRequest') return;

  const authorUsername = payload.object_attributes?.author?.username || '';
  if (BOT_AUTHORS.includes(authorUsername)) {
    logger.debug(`Ignoring bot comment from: ${authorUsername}`);
    return;
  }

  const sourceBranch = payload.merge_request?.source_branch;
  const state = getState(sourceBranch);
  if (!state || state.state !== 'awaiting-review') {
    logger.debug(`Ignoring note: pipeline not in awaiting-review for ${sourceBranch}`);
    return;
  }

  // Check rework limit
  const maxRework = parseInt(process.env.MAX_REWORK_ITERATIONS || '3', 10);
  if (isReworkLimitExceeded(sourceBranch, maxRework)) {
    logger.warn(`Rework limit exceeded for ${state.issueKey} — escalating`);
    // Notify via orchestrator to send Slack escalation
    const input = JSON.stringify({
      action: 'rework-limit-exceeded',
      issueKey: state.issueKey,
      branch: sourceBranch,
      reworkCount: state.reworkCount,
    });
    runAgent('orchestrator', input, {
      cwd: state.repoPath || process.cwd(),
    }).catch((err) => {
      logger.error(`Rework escalation failed: ${err.message}`);
    });
    return;
  }

  // Branch C: Feedback / Rework
  logger.info(`Review comment received for ${state.issueKey}, invoking feedback parser`);

  const input = JSON.stringify({
    issueKey: state.issueKey,
    branch: sourceBranch,
    mrIid: payload.merge_request?.iid,
  });

  runAgent('feedback-parser', input, {
    cwd: state.repoPath || process.cwd(),
  }).catch((err) => {
    logger.error(`Feedback parser agent failed: ${err.message}`);
  });
}

module.exports = router;
