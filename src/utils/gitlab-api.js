/**
 * @module utils/gitlab-api
 * @description Thin wrapper around the GitLab REST API v4.
 *
 * Used by the webhook routes and optionally by agent utilities when
 * direct API access is needed outside the MCP server context.
 *
 * All methods return the raw GitLab API response `data` object.
 * Errors propagate as Axios errors — callers should handle them.
 *
 * @example
 *   const { GitLabAPI } = require('./utils/gitlab-api');
 *   const gl = new GitLabAPI('https://gitlab.com', 'glpat-xxx', '12345');
 *   const branch = await gl.createBranch('feature/PROJ-1-new-feature');
 */
const axios = require('axios');

class GitLabAPI {
  /**
   * @param {string} baseUrl - GitLab instance URL (e.g. https://gitlab.com)
   * @param {string} token - Personal access token with `api` scope
   * @param {string} projectId - Numeric GitLab project ID
   */
  constructor(baseUrl, token, projectId) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.projectId = projectId;
    this.client = axios.create({
      baseURL: `${this.baseUrl}/api/v4`,
      headers: {
        'PRIVATE-TOKEN': token,
        'Content-Type': 'application/json',
      },
    });
  }

  /**
   * Create a new branch from an existing ref.
   * @param {string} branchName - Name of the new branch
   * @param {string} [ref='main'] - Source branch or commit SHA
   * @returns {Promise<object>} GitLab branch object
   */
  async createBranch(branchName, ref = 'main') {
    const { data } = await this.client.post(
      `/projects/${this.projectId}/repository/branches`,
      { branch: branchName, ref }
    );
    return data;
  }

  /**
   * Commit one or more file changes to a branch in a single commit.
   * @param {string} branch - Target branch name
   * @param {string} commitMessage - Commit message text
   * @param {Array<{action: 'create'|'update'|'delete', file_path: string, content?: string}>} actions
   * @returns {Promise<object>} GitLab commit object
   */
  async commitFiles(branch, commitMessage, actions) {
    const { data } = await this.client.post(
      `/projects/${this.projectId}/repository/commits`,
      {
        branch,
        commit_message: commitMessage,
        actions,
      }
    );
    return data;
  }

  /**
   * Create a merge request.
   * @param {string} sourceBranch - Feature branch
   * @param {string} targetBranch - Target branch (e.g. main)
   * @param {string} title - MR title
   * @param {string} description - MR description (markdown)
   * @returns {Promise<object>} GitLab MR object with `iid`, `web_url`, etc.
   */
  async createMergeRequest(sourceBranch, targetBranch, title, description) {
    const { data } = await this.client.post(
      `/projects/${this.projectId}/merge_requests`,
      {
        source_branch: sourceBranch,
        target_branch: targetBranch,
        title,
        description,
      }
    );
    return data;
  }

  /**
   * Get merge request details by IID.
   * @param {number|string} mrIid - Merge request internal ID
   * @returns {Promise<object>} Full MR object
   */
  async getMergeRequest(mrIid) {
    const { data } = await this.client.get(
      `/projects/${this.projectId}/merge_requests/${mrIid}`
    );
    return data;
  }

  /**
   * Update a merge request (title, description, assignee, etc.).
   * @param {number|string} mrIid - Merge request internal ID
   * @param {object} updates - Fields to update
   * @returns {Promise<object>} Updated MR object
   */
  async updateMergeRequest(mrIid, updates) {
    const { data } = await this.client.put(
      `/projects/${this.projectId}/merge_requests/${mrIid}`,
      updates
    );
    return data;
  }

  /**
   * List all notes/comments on a merge request, oldest first.
   * @param {number|string} mrIid - Merge request internal ID
   * @returns {Promise<Array<object>>} Array of note objects
   */
  async listMRComments(mrIid) {
    const { data } = await this.client.get(
      `/projects/${this.projectId}/merge_requests/${mrIid}/notes`,
      { params: { sort: 'asc', order_by: 'created_at' } }
    );
    return data;
  }

  /**
   * Post a comment on a merge request.
   * @param {number|string} mrIid - Merge request internal ID
   * @param {string} body - Comment body (supports markdown)
   * @returns {Promise<object>} Created note object
   */
  async postMRComment(mrIid, body) {
    const { data } = await this.client.post(
      `/projects/${this.projectId}/merge_requests/${mrIid}/notes`,
      { body }
    );
    return data;
  }

  /**
   * Read a file from the repository at a given ref.
   * Returns the standard GitLab file object plus a `decodedContent` field.
   * @param {string} filePath - Path to the file in the repo
   * @param {string} [ref='main'] - Branch name or commit SHA
   * @returns {Promise<object>} File object with `decodedContent` (utf-8 string)
   */
  async getFile(filePath, ref = 'main') {
    const encodedPath = encodeURIComponent(filePath);
    const { data } = await this.client.get(
      `/projects/${this.projectId}/repository/files/${encodedPath}`,
      { params: { ref } }
    );
    return {
      ...data,
      decodedContent: Buffer.from(data.content, 'base64').toString('utf-8'),
    };
  }
}

module.exports = { GitLabAPI };
