/**
 * @module providers/git/gitlab
 * @description GitLab git provider adapter.
 *
 * Parses GitLab webhook events (Merge Request Hook, Push Hook, Note Hook)
 * and provides an API client wrapping GitLab REST API v4.
 */

const axios = require('axios');
const { GitProviderBase } = require('../base/git-provider-base');

class GitLabAdapter extends GitProviderBase {
  get name() { return 'gitlab'; }
  get prLabel() { return 'merge request'; }

  parseWebhook(headers, payload, config) {
    const eventType = headers['x-gitlab-event'];
    const botUsers = config.botUsers || [];

    if (eventType === 'Merge Request Hook') {
      if (payload.object_attributes?.action !== 'approved') return null;
      return {
        event: 'approved',
        branch: payload.object_attributes?.source_branch,
        prId: payload.object_attributes?.iid,
        author: payload.user?.username || '',
      };
    }

    if (eventType === 'Push Hook') {
      const author = payload.user_username || '';
      if (botUsers.includes(author)) return null;
      return {
        event: 'push',
        branch: (payload.ref || '').replace('refs/heads/', ''),
        prId: null,
        author,
      };
    }

    if (eventType === 'Note Hook') {
      if (payload.object_attributes?.noteable_type !== 'MergeRequest') return null;
      const author = payload.object_attributes?.author?.username || '';
      if (botUsers.includes(author)) return null;
      return {
        event: 'comment',
        branch: payload.merge_request?.source_branch,
        prId: payload.merge_request?.iid,
        author,
      };
    }

    return null;
  }

  createApi(env) {
    const baseUrl = (env.GITLAB_BASE_URL || 'https://gitlab.com').replace(/\/$/, '');
    const projectId = env.GITLAB_PROJECT_ID;
    const client = axios.create({
      baseURL: `${baseUrl}/api/v4`,
      headers: { 'PRIVATE-TOKEN': env.GITLAB_TOKEN, 'Content-Type': 'application/json' },
    });
    const p = `/projects/${projectId}`;

    const api = {
      async createBranch(branchName, ref = 'main') {
        const { data } = await client.post(`${p}/repository/branches`, { branch: branchName, ref });
        return data;
      },
      async commitFiles(branch, message, actions) {
        const { data } = await client.post(`${p}/repository/commits`, { branch, commit_message: message, actions });
        return data;
      },
      async createPR(sourceBranch, targetBranch, title, description) {
        const { data } = await client.post(`${p}/merge_requests`, { source_branch: sourceBranch, target_branch: targetBranch, title, description });
        return { id: data.iid, url: data.web_url, title: data.title, state: data.state };
      },
      async getPR(prId) {
        const { data } = await client.get(`${p}/merge_requests/${prId}`);
        return { id: data.iid, url: data.web_url, title: data.title, state: data.state, sourceBranch: data.source_branch, description: data.description };
      },
      async updatePR(prId, updates) {
        const { data } = await client.put(`${p}/merge_requests/${prId}`, updates);
        return data;
      },
      async listPRComments(prId) {
        const { data } = await client.get(`${p}/merge_requests/${prId}/notes`, { params: { sort: 'asc', order_by: 'created_at' } });
        return data.map(n => ({ id: n.id, author: n.author?.username, body: n.body, createdAt: n.created_at, system: n.system }));
      },
      async postPRComment(prId, body) {
        const { data } = await client.post(`${p}/merge_requests/${prId}/notes`, { body });
        return data;
      },
      async getFile(filePath, ref = 'main') {
        const encoded = encodeURIComponent(filePath);
        const { data } = await client.get(`${p}/repository/files/${encoded}`, { params: { ref } });
        return { ...data, content: Buffer.from(data.content, 'base64').toString('utf-8') };
      },
    };

    this.validateApi(api);
    return api;
  }
}

module.exports = new GitLabAdapter();
