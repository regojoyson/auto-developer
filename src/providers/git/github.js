/**
 * @module providers/git/github
 * @description GitHub git provider adapter.
 *
 * Parses GitHub webhook events (pull_request, push, issue_comment, pull_request_review)
 * and provides an API client wrapping GitHub REST API.
 */

const axios = require('axios');
const { GitProviderBase } = require('../base/git-provider-base');

class GitHubAdapter extends GitProviderBase {
  get name() { return 'github'; }
  get prLabel() { return 'pull request'; }

  parseWebhook(headers, payload, config) {
    const event = headers['x-github-event'];
    const botUsers = config.botUsers || [];

    if (event === 'pull_request_review') {
      if (payload.review?.state !== 'approved') return null;
      return {
        event: 'approved',
        branch: payload.pull_request?.head?.ref,
        prId: payload.pull_request?.number,
        author: payload.review?.user?.login || '',
      };
    }

    if (event === 'pull_request') {
      if (payload.action === 'closed' && payload.pull_request?.merged) {
        return {
          event: 'approved',
          branch: payload.pull_request?.head?.ref,
          prId: payload.pull_request?.number,
          author: payload.sender?.login || '',
        };
      }
      return null;
    }

    if (event === 'push') {
      const author = payload.sender?.login || '';
      if (botUsers.includes(author)) return null;
      return {
        event: 'push',
        branch: (payload.ref || '').replace('refs/heads/', ''),
        prId: null,
        author,
      };
    }

    if (event === 'issue_comment' || event === 'pull_request_review_comment') {
      if (!payload.issue?.pull_request && event === 'issue_comment') return null;
      const author = payload.comment?.user?.login || '';
      if (botUsers.includes(author)) return null;
      return {
        event: 'comment',
        branch: null,
        prId: payload.issue?.number || payload.pull_request?.number,
        author,
      };
    }

    return null;
  }

  createApi(env) {
    const owner = env.GITHUB_OWNER;
    const repo = env.GITHUB_REPO;
    const client = axios.create({
      baseURL: 'https://api.github.com',
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
    });
    const r = `/repos/${owner}/${repo}`;

    const api = {
      async createBranch(branchName, ref = 'main') {
        const { data: refData } = await client.get(`${r}/git/ref/heads/${ref}`);
        const { data } = await client.post(`${r}/git/refs`, { ref: `refs/heads/${branchName}`, sha: refData.object.sha });
        return data;
      },
      async commitFiles(branch, message, actions) {
        for (const action of actions) {
          if (action.action === 'delete') {
            const { data: existing } = await client.get(`${r}/contents/${action.file_path}?ref=${branch}`);
            await client.delete(`${r}/contents/${action.file_path}`, { data: { message, branch, sha: existing.sha } });
          } else {
            let sha;
            try { const { data: e } = await client.get(`${r}/contents/${action.file_path}?ref=${branch}`); sha = e.sha; } catch (_) {}
            const body = { message, branch, content: Buffer.from(action.content || '').toString('base64') };
            if (sha) body.sha = sha;
            await client.put(`${r}/contents/${action.file_path}`, body);
          }
        }
        return { message };
      },
      async createPR(sourceBranch, targetBranch, title, description) {
        const { data } = await client.post(`${r}/pulls`, { head: sourceBranch, base: targetBranch, title, body: description });
        return { id: data.number, url: data.html_url, title: data.title, state: data.state };
      },
      async getPR(prId) {
        const { data } = await client.get(`${r}/pulls/${prId}`);
        return { id: data.number, url: data.html_url, title: data.title, state: data.state, sourceBranch: data.head?.ref, description: data.body };
      },
      async updatePR(prId, updates) {
        const body = {};
        if (updates.title) body.title = updates.title;
        if (updates.description) body.body = updates.description;
        const { data } = await client.patch(`${r}/pulls/${prId}`, body);
        return data;
      },
      async listPRComments(prId) {
        const [{ data: issue }, { data: review }] = await Promise.all([
          client.get(`${r}/issues/${prId}/comments`),
          client.get(`${r}/pulls/${prId}/comments`),
        ]);
        return [
          ...issue.map(c => ({ id: c.id, author: c.user?.login, body: c.body, createdAt: c.created_at, system: false })),
          ...review.map(c => ({ id: c.id, author: c.user?.login, body: c.body, createdAt: c.created_at, system: false })),
        ].sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));
      },
      async postPRComment(prId, body) {
        const { data } = await client.post(`${r}/issues/${prId}/comments`, { body });
        return data;
      },
      async getFile(filePath, ref = 'main') {
        const { data } = await client.get(`${r}/contents/${filePath}`, { params: { ref } });
        return { ...data, content: Buffer.from(data.content, 'base64').toString('utf-8') };
      },
    };

    this.validateApi(api);
    return api;
  }
}

module.exports = new GitHubAdapter();
