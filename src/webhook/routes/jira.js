/**
 * @module webhook/routes/jira
 * @description Handles incoming Jira webhooks (POST /webhooks/jira).
 *
 * Filters for `issue_updated` events where the status transitions to
 * "Ready for Development". On a valid event it:
 *   1. Derives a feature branch name from the issue key + summary
 *   2. Creates an initial pipeline state (`brainstorming`)
 *   3. Responds 202 immediately (non-blocking)
 *   4. Asynchronously invokes the orchestrator agent via Claude Code CLI
 *
 * Duplicate events for the same branch are silently ignored (idempotent).
 */

const { Router } = require('express');
const logger = require('../../utils/logger');
const { getState, createState } = require('../../state/manager');
const { runAgent } = require('../../agents/runner');
const { getRepoDir, getMode } = require('../../repos/resolver');

const router = Router();

/**
 * POST / — Jira webhook entry point.
 * Expected payload: Jira `issue_updated` webhook with `changelog.items`.
 */
router.post('/', async (req, res) => {
  try {
    const payload = req.body;

    // Validate this is a status transition event
    const changelog = payload.changelog;
    if (!changelog || !changelog.items) {
      logger.debug('Ignoring Jira event: no changelog items');
      return res.status(200).json({ ignored: true, reason: 'no changelog' });
    }

    // Find the status change item
    const statusChange = changelog.items.find(
      (item) => item.field === 'status'
    );
    if (!statusChange) {
      logger.debug('Ignoring Jira event: no status change');
      return res.status(200).json({ ignored: true, reason: 'no status change' });
    }

    // Only process transitions to "Ready for Development"
    const newStatus = statusChange.toString || '';
    if (newStatus !== 'Ready for Development') {
      logger.debug(`Ignoring Jira status change to: ${newStatus}`);
      return res.status(200).json({ ignored: true, reason: `status: ${newStatus}` });
    }

    const issueKey = payload.issue?.key;
    if (!issueKey) {
      logger.warn('Jira webhook missing issue key');
      return res.status(400).json({ error: 'Missing issue key' });
    }

    // Derive branch name
    const summary = payload.issue?.fields?.summary || '';
    const slug = summary
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .slice(0, 40)
      .replace(/-$/, '');
    const branch = `feature/${issueKey}-${slug}`;

    // Check for duplicate processing
    const existingState = getState(branch);
    if (existingState) {
      logger.warn(`Pipeline already active for ${branch}, ignoring duplicate`);
      return res.status(200).json({ ignored: true, reason: 'already active' });
    }

    // Resolve repo directory from repos.json
    // Single mode: always the configured repoDir
    // Multi mode: Jira ticket component/label can specify the repo name,
    //             otherwise falls back to the parent directory
    const repoComponent = payload.issue?.fields?.components?.[0]?.name || null;
    const repoDir = getRepoDir(repoComponent);

    logger.info(`Processing Jira ticket: ${issueKey}`, { branch, summary, repoDir });

    // Create pipeline state (includes repo path for later lookups)
    createState(branch, issueKey, { repoPath: repoDir });

    // Respond immediately, run agent async
    res.status(202).json({ accepted: true, issueKey, branch, repoDir });

    // Invoke orchestrator agent in the target repo directory
    const input = JSON.stringify({
      issueKey,
      branch,
      summary,
      projectKey: issueKey.split('-')[0],
    });

    runAgent('orchestrator', input, { cwd: repoDir }).catch((err) => {
      logger.error(`Orchestrator agent failed for ${issueKey}: ${err.message}`);
    });
  } catch (err) {
    logger.error(`Jira webhook handler error: ${err.message}`);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
