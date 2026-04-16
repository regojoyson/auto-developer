/**
 * @module mcp-servers/github
 * @description MCP server wrapping GitHub REST API.
 *
 * Tools: create_branch, commit_files, create_pull_request, get_pull_request,
 *        update_pull_request, list_pr_comments, post_pr_comment, get_file
 *
 * Env: GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO
 */

const { McpServer } = require('@modelcontextprotocol/sdk/server/mcp.js');
const { StdioServerTransport } = require('@modelcontextprotocol/sdk/server/stdio.js');
const { z } = require('zod');
const axios = require('axios');

const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const GITHUB_OWNER = process.env.GITHUB_OWNER;
const GITHUB_REPO = process.env.GITHUB_REPO;

if (!GITHUB_TOKEN || !GITHUB_OWNER || !GITHUB_REPO) {
  console.error('GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_REPO are required');
  process.exit(1);
}

const client = axios.create({
  baseURL: 'https://api.github.com',
  headers: { Authorization: `Bearer ${GITHUB_TOKEN}`, Accept: 'application/vnd.github.v3+json', 'Content-Type': 'application/json' },
});

const R = `/repos/${GITHUB_OWNER}/${GITHUB_REPO}`;
const server = new McpServer({ name: 'github-mcp', version: '1.0.0' });

server.tool('create_branch', 'Create a new branch in the GitHub repo', {
  branch_name: z.string().describe('Name of the new branch'),
  ref: z.string().optional().describe('Source branch (default: main)'),
}, async ({ branch_name, ref = 'main' }) => {
  try {
    const { data: refData } = await client.get(`${R}/git/ref/heads/${ref}`);
    const { data } = await client.post(`${R}/git/refs`, { ref: `refs/heads/${branch_name}`, sha: refData.object.sha });
    return { content: [{ type: 'text', text: JSON.stringify({ ref: data.ref, sha: data.object.sha }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('commit_files', 'Commit file changes to a branch', {
  branch: z.string().describe('Target branch'),
  commit_message: z.string().describe('Commit message'),
  actions: z.string().describe('JSON array: [{"action":"create"|"update"|"delete","file_path":"...","content":"..."}]'),
}, async ({ branch, commit_message, actions }) => {
  try {
    const parsed = JSON.parse(actions);
    for (const action of parsed) {
      if (action.action === 'delete') {
        const { data: existing } = await client.get(`${R}/contents/${action.file_path}?ref=${branch}`);
        await client.delete(`${R}/contents/${action.file_path}`, { data: { message: commit_message, branch, sha: existing.sha } });
      } else {
        let sha;
        try { const { data: e } = await client.get(`${R}/contents/${action.file_path}?ref=${branch}`); sha = e.sha; } catch (_) {}
        const body = { message: commit_message, branch, content: Buffer.from(action.content || '').toString('base64') };
        if (sha) body.sha = sha;
        await client.put(`${R}/contents/${action.file_path}`, body);
      }
    }
    return { content: [{ type: 'text', text: JSON.stringify({ committed: true, files: parsed.length }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('create_pull_request', 'Create a pull request', {
  source_branch: z.string().describe('Head branch'),
  target_branch: z.string().describe('Base branch (e.g., main)'),
  title: z.string().describe('PR title'),
  description: z.string().describe('PR body (markdown)'),
}, async ({ source_branch, target_branch, title, description }) => {
  try {
    const { data } = await client.post(`${R}/pulls`, { head: source_branch, base: target_branch, title, body: description });
    return { content: [{ type: 'text', text: JSON.stringify({ number: data.number, html_url: data.html_url, title: data.title, state: data.state }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('get_pull_request', 'Get pull request details', {
  pr_number: z.string().describe('PR number'),
}, async ({ pr_number }) => {
  try {
    const { data } = await client.get(`${R}/pulls/${pr_number}`);
    return { content: [{ type: 'text', text: JSON.stringify({ number: data.number, title: data.title, state: data.state, head: data.head?.ref, base: data.base?.ref, html_url: data.html_url, body: data.body }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('update_pull_request', 'Update a pull request', {
  pr_number: z.string().describe('PR number'),
  title: z.string().optional().describe('New title'),
  description: z.string().optional().describe('New body'),
}, async ({ pr_number, title, description }) => {
  try {
    const updates = {};
    if (title) updates.title = title;
    if (description) updates.body = description;
    const { data } = await client.patch(`${R}/pulls/${pr_number}`, updates);
    return { content: [{ type: 'text', text: JSON.stringify({ number: data.number, title: data.title, state: data.state }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('list_pr_comments', 'List all comments on a pull request', {
  pr_number: z.string().describe('PR number'),
}, async ({ pr_number }) => {
  try {
    const [{ data: issue }, { data: review }] = await Promise.all([
      client.get(`${R}/issues/${pr_number}/comments`),
      client.get(`${R}/pulls/${pr_number}/comments`),
    ]);
    const all = [
      ...issue.map(c => ({ id: c.id, author: c.user?.login, body: c.body, created_at: c.created_at })),
      ...review.map(c => ({ id: c.id, author: c.user?.login, body: c.body, created_at: c.created_at, path: c.path, line: c.line })),
    ].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    return { content: [{ type: 'text', text: JSON.stringify(all, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('post_pr_comment', 'Post a comment on a pull request', {
  pr_number: z.string().describe('PR number'),
  body: z.string().describe('Comment body (markdown)'),
}, async ({ pr_number, body }) => {
  try {
    const { data } = await client.post(`${R}/issues/${pr_number}/comments`, { body });
    return { content: [{ type: 'text', text: JSON.stringify({ id: data.id, body: data.body }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('get_file', 'Read a file from the repository', {
  file_path: z.string().describe('Path to the file'),
  ref: z.string().optional().describe('Branch or commit SHA (default: main)'),
}, async ({ file_path, ref = 'main' }) => {
  try {
    const { data } = await client.get(`${R}/contents/${file_path}`, { params: { ref } });
    return { content: [{ type: 'text', text: Buffer.from(data.content, 'base64').toString('utf-8') }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
main().catch((err) => { console.error('GitHub MCP failed:', err); process.exit(1); });
