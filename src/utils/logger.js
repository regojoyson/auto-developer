/**
 * @module utils/logger
 * @description Structured logging utility for the pipeline.
 *
 * Outputs timestamped, level-tagged messages to stdout/stderr.
 * Supports an optional metadata object that is JSON-serialized inline.
 *
 * Log level is controlled by the `LOG_LEVEL` environment variable
 * (debug | info | warn | error). Defaults to `info`.
 *
 * @example
 *   const logger = require('./utils/logger');
 *   logger.info('Processing ticket', { issueKey: 'PROJ-42' });
 *   // => [2026-04-15T12:00:00.000Z] [INFO] Processing ticket {"issueKey":"PROJ-42"}
 */

/** @type {Record<string, number>} Numeric priority for each log level */
const LOG_LEVELS = { debug: 0, info: 1, warn: 2, error: 3 };

/** Resolved minimum level from env — messages below this are suppressed */
const CURRENT_LEVEL = LOG_LEVELS[process.env.LOG_LEVEL || 'info'];

/**
 * Build a formatted log line.
 * @param {string} level - Log level name
 * @param {string} message - Human-readable message
 * @param {object} [meta] - Optional structured metadata
 * @returns {string} Formatted log line
 */
function formatMessage(level, message, meta) {
  const timestamp = new Date().toISOString();
  const metaStr = meta ? ` ${JSON.stringify(meta)}` : '';
  return `[${timestamp}] [${level.toUpperCase()}] ${message}${metaStr}`;
}

/**
 * Internal log dispatcher — writes to the appropriate console stream.
 * @param {string} level - Log level name
 * @param {string} message - Human-readable message
 * @param {object} [meta] - Optional structured metadata
 */
function log(level, message, meta) {
  if (LOG_LEVELS[level] >= CURRENT_LEVEL) {
    const formatted = formatMessage(level, message, meta);
    if (level === 'error') {
      console.error(formatted);
    } else if (level === 'warn') {
      console.warn(formatted);
    } else {
      console.log(formatted);
    }
  }
}

module.exports = {
  /** @param {string} msg @param {object} [meta] */
  debug: (msg, meta) => log('debug', msg, meta),
  /** @param {string} msg @param {object} [meta] */
  info: (msg, meta) => log('info', msg, meta),
  /** @param {string} msg @param {object} [meta] */
  warn: (msg, meta) => log('warn', msg, meta),
  /** @param {string} msg @param {object} [meta] */
  error: (msg, meta) => log('error', msg, meta),
};
