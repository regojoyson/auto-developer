/**
 * @module webhook/routes/status
 * @description Pipeline status API — query running and completed pipelines.
 *
 * GET /api/status            — list all pipelines
 * GET /api/status/:issueKey  — get a specific pipeline by issue key
 */

const { Router } = require('express');
const { listActiveStates } = require('../../state/manager');

const router = Router();

/** List all pipelines. */
router.get('/', (req, res) => {
  const all = listActiveStates();
  res.json({ count: all.length, pipelines: all });
});

/** Get a specific pipeline by issue key (e.g. PROJ-42). */
router.get('/:issueKey', (req, res) => {
  const all = listActiveStates();
  const match = all.find(s => s.issueKey === req.params.issueKey);
  if (!match) {
    return res.status(404).json({ error: 'Pipeline not found', issueKey: req.params.issueKey });
  }
  res.json(match);
});

module.exports = router;
