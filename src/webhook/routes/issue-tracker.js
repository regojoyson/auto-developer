/**
 * @module webhook/routes/issue-tracker
 * @description Unified webhook handler for any issue tracker (Jira, GitHub Issues, etc.).
 *
 * Delegates payload parsing to the configured adapter.
 * On a valid trigger event:
 *   1. Resolves the target repo directory
 *   2. Prepares the repo (checkout baseBranch, pull latest)
 *   3. Creates pipeline state
 *   4. Invokes the orchestrator agent
 */

const { Router } = require('express');
const logger = require('../../utils/logger');
const { getState, createState } = require('../../state/manager');
const { runAgent } = require('../../agents/runner');
const { getRepoDir, prepareRepo, getBaseBranch } = require('../../repos/resolver');
const { getIssueTracker } = require('../../providers/issue-tracker');

const router = Router();

router.post('/', async (req, res) => {
  try {
    const tracker = getIssueTracker();
    const parsed = tracker.parseWebhook(req.headers, req.body, tracker.config);

    if (!parsed) {
      logger.debug('Issue tracker webhook ignored (no matching event)');
      return res.status(200).json({ ignored: true });
    }

    const { issueKey, summary, component } = parsed;

    // Derive branch name
    const slug = summary
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .slice(0, 40)
      .replace(/-$/, '');
    const branch = `feature/${issueKey}-${slug}`;

    // Deduplicate
    if (getState(branch)) {
      logger.warn(`Pipeline already active for ${branch}, ignoring duplicate`);
      return res.status(200).json({ ignored: true, reason: 'already active' });
    }

    const repoDir = getRepoDir(component);
    logger.info(`Processing ${tracker.eventLabel}: ${issueKey}`, { branch, summary, repoDir });

    // Prepare repo — checkout baseBranch and pull latest before branching
    prepareRepo(repoDir);

    createState(branch, issueKey, { repoPath: repoDir });
    res.status(202).json({ accepted: true, issueKey, branch, repoDir });

    const baseBranch = getBaseBranch();
    const input = JSON.stringify({
      issueKey,
      branch,
      summary,
      projectKey: issueKey.split('-')[0],
      baseBranch,
    });

    runAgent('orchestrator', input, { cwd: repoDir }).catch((err) => {
      logger.error(`Orchestrator agent failed for ${issueKey}: ${err.message}`);
    });
  } catch (err) {
    logger.error(`Issue tracker webhook error: ${err.message}`);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
