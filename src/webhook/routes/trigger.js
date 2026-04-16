/**
 * @module webhook/routes/trigger
 * @description Manual trigger API — start the pipeline for a ticket without
 * waiting for a webhook.
 *
 * POST /api/trigger
 * Body: { "issueKey": "PROJ-42" }
 * Optional: { "issueKey": "PROJ-42", "summary": "Add login page", "component": "frontend-app" }
 *
 * If summary is not provided, it is derived from the issue key.
 * If component is not provided, the default repo is used.
 *
 * @example
 *   curl -X POST http://localhost:3000/api/trigger \
 *     -H 'Content-Type: application/json' \
 *     -d '{"issueKey": "PROJ-42"}'
 */

const { Router } = require('express');
const logger = require('../../utils/logger');
const { getState, createState } = require('../../state/manager');
const { runAgent } = require('../../agents/runner');
const { getRepoDir, prepareRepo, getBaseBranch } = require('../../repos/resolver');

const router = Router();

router.post('/', async (req, res) => {
  try {
    const { issueKey, summary, component } = req.body;

    if (!issueKey) {
      return res.status(400).json({ error: 'issueKey is required' });
    }

    // Derive branch name
    const ticketSummary = summary || issueKey;
    const slug = ticketSummary
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .slice(0, 40)
      .replace(/-$/, '');
    const branch = `feature/${issueKey}-${slug}`;

    // Deduplicate
    if (getState(branch)) {
      return res.status(409).json({ error: 'Pipeline already active for this ticket', branch });
    }

    const repoDir = getRepoDir(component || null);
    logger.info(`Manual trigger: ${issueKey}`, { branch, summary: ticketSummary, repoDir });

    prepareRepo(repoDir);
    createState(branch, issueKey, { repoPath: repoDir });

    res.status(202).json({ accepted: true, issueKey, branch, repoDir });

    const baseBranch = getBaseBranch();
    const input = JSON.stringify({
      issueKey,
      branch,
      summary: ticketSummary,
      projectKey: issueKey.split('-')[0],
      baseBranch,
    });

    runAgent('orchestrator', input, { cwd: repoDir }).catch((err) => {
      logger.error(`Orchestrator agent failed for ${issueKey}: ${err.message}`);
    });
  } catch (err) {
    logger.error(`Manual trigger error: ${err.message}`);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
