/**
 * @module webhook/server
 * @description Express HTTP server that receives webhooks from issue trackers
 * and git providers, and routes them to the appropriate pipeline handlers.
 *
 * Endpoints:
 *   GET  /health                  — Health-check (returns `{ status: 'ok' }`)
 *   POST /webhooks/issue-tracker  — Issue tracker events (Jira, GitHub Issues, etc.)
 *   POST /webhooks/git            — Git provider events (GitLab, GitHub, etc.)
 *   POST /api/trigger             — Manual trigger (pass issueKey to start pipeline)
 *   GET  /api/status              — List all pipelines
 *   GET  /api/status/:issueKey    — Get pipeline status for a ticket
 *
 * Start with `npm start` or `node src/webhook/server.js`.
 * For development with auto-reload use `npm run dev`.
 *
 * Requires a `.env` file (see `.env.example`).
 */

require('dotenv').config();
const express = require('express');
const issueTrackerRoutes = require('./routes/issue-tracker');
const gitProviderRoutes = require('./routes/git-provider');
const triggerRoutes = require('./routes/trigger');
const statusRoutes = require('./routes/status');
const logger = require('../utils/logger');
const config = require('../config');

const app = express();
const PORT = config.pipeline.port;

// Parse JSON payloads up to 1 MB (webhook payloads can be large)
app.use(express.json({ limit: '1mb' }));

// Health check — useful for monitoring and uptime checks
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Webhook routes (provider-agnostic)
app.use('/webhooks/issue-tracker', issueTrackerRoutes);
app.use('/webhooks/git', gitProviderRoutes);

// Manual trigger API
app.use('/api/trigger', triggerRoutes);

// Pipeline status API
app.use('/api/status', statusRoutes);

app.listen(PORT, () => {
  logger.info(`Webhook receiver listening on port ${PORT}`);
});

module.exports = app;
