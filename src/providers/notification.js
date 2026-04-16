/**
 * @module providers/notification
 * @description Factory for the notification adapter. Returns null if not configured.
 *
 * @example
 *   const { getNotification } = require('./providers/notification');
 *   const notifier = getNotification();
 *   if (notifier) await notifier.send('PR created', notifier.config);
 */

const config = require('../config');

let instance = undefined; // undefined = not yet loaded, null = disabled

function getNotification() {
  if (instance !== undefined) return instance;

  const notifConfig = config.notification;
  if (!notifConfig || !notifConfig.type) {
    instance = null;
    return null;
  }

  let adapter;
  switch (notifConfig.type) {
    case 'slack':
      adapter = require('./notifications/slack');
      break;
    default:
      throw new Error(`Unknown notification type: "${notifConfig.type}". Supported: slack`);
  }

  instance = Object.create(adapter);
  instance.config = notifConfig;
  return instance;
}

function clearCache() {
  instance = undefined;
}

module.exports = { getNotification, clearCache };
