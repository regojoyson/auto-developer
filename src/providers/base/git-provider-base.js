/**
 * @module providers/base/git-provider-base
 * @description Base class for git provider adapters.
 *
 * Every git provider (GitLab, GitHub, Bitbucket, etc.) must extend this
 * and implement all abstract methods.
 *
 * `createApi()` must return an object implementing the GitApiClient interface:
 *   createBranch(name, ref) → object
 *   commitFiles(branch, message, actions) → object
 *   createPR(source, target, title, desc) → { id, url, title, state }
 *   getPR(prId) → { id, url, title, state, sourceBranch, description }
 *   updatePR(prId, updates) → object
 *   listPRComments(prId) → [{ id, author, body, createdAt, system }]
 *   postPRComment(prId, body) → object
 *   getFile(path, ref) → { content, ... }
 *
 * @example
 *   const { GitProviderBase } = require('./base/git-provider-base');
 *
 *   class BitbucketAdapter extends GitProviderBase {
 *     get name() { return 'bitbucket'; }
 *     get prLabel() { return 'pull request'; }
 *     parseWebhook(headers, payload, config) { ... }
 *     createApi(env) { ... }
 *   }
 */

const REQUIRED_API_METHODS = [
  'createBranch',
  'commitFiles',
  'createPR',
  'getPR',
  'updatePR',
  'listPRComments',
  'postPRComment',
  'getFile',
];

class GitProviderBase {
  constructor() {
    const className = this.constructor.name;

    if (!this.name) {
      throw new Error(`${className}: must define "name" (e.g. 'gitlab', 'github')`);
    }
    if (!this.prLabel) {
      throw new Error(`${className}: must define "prLabel" (e.g. 'merge request', 'pull request')`);
    }
  }

  /** @type {string} @abstract */
  get name() { return ''; }

  /** @type {string} Human-readable label for a PR/MR. @abstract */
  get prLabel() { return ''; }

  /**
   * Parse an incoming webhook payload from this git provider.
   *
   * @param {object} headers - HTTP request headers
   * @param {object} payload - Webhook JSON body
   * @param {object} config - gitProvider section from config.yaml
   * @returns {{ event: 'approved'|'push'|'comment', branch: string|null, prId: string|number|null, author: string }|null}
   * @abstract
   */
  parseWebhook(headers, payload, config) {
    throw new Error(`${this.constructor.name}: must implement parseWebhook()`);
  }

  /**
   * Create an API client for this git provider.
   *
   * The returned object must implement all methods in REQUIRED_API_METHODS.
   *
   * @param {object} env - Environment variables
   * @returns {object} API client
   * @abstract
   */
  createApi(env) {
    throw new Error(`${this.constructor.name}: must implement createApi()`);
  }

  /**
   * Validate that an API client implements all required methods.
   * Call this in your createApi() to catch mistakes early.
   *
   * @param {object} api - API client to validate
   * @throws {Error} If any required method is missing
   */
  validateApi(api) {
    for (const method of REQUIRED_API_METHODS) {
      if (typeof api[method] !== 'function') {
        throw new Error(
          `${this.constructor.name}.createApi(): returned object missing required method "${method}"`
        );
      }
    }
  }
}

module.exports = { GitProviderBase, REQUIRED_API_METHODS };
