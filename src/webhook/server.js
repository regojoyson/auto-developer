/**
 * @module webhook/server
 * @description Express HTTP server that receives webhooks from Jira and GitLab
 * and routes them to the appropriate pipeline handlers.
 *
 * Endpoints:
 *   GET  /health           — Health-check (returns `{ status: 'ok' }`)
 *   POST /webhooks/jira    — Jira issue-updated events
 *   POST /webhooks/gitlab  — GitLab MR, push, and note events
 *
 * Start with `npm start` or `node src/webhook/server.js`.
 * For development with auto-reload use `npm run dev`.
 *
 * Requires a `.env` file (see `.env.example`).
 */

require('dotenv').config();
const express = require('express');
const jiraRoutes = require('./routes/jira');
const gitlabRoutes = require('./routes/gitlab');
const logger = require('../utils/logger');

const app = express();
const PORT = process.env.PORT || 3000;

// Parse JSON payloads up to 1 MB (GitLab webhooks can be large)
app.use(express.json({ limit: '1mb' }));

// Health check — useful for monitoring and ngrok tunnel verification
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Webhook routes
app.use('/webhooks/jira', jiraRoutes);
app.use('/webhooks/gitlab', gitlabRoutes);

app.listen(PORT, () => {
  logger.info(`Webhook receiver listening on port ${PORT}`);
});

module.exports = app;
