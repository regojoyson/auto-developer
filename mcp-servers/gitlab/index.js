/**
 * @module mcp-servers/gitlab
 * @description MCP server wrapping GitLab REST API v4.
 *
 * Tools: create_branch, commit_files, create_merge_request, get_merge_request,
 *        update_merge_request, list_mr_comments, post_mr_comment, get_file
 *
 * Env: GITLAB_BASE_URL, GITLAB_TOKEN, GITLAB_PROJECT_ID
 */

const { McpServer } = require('@modelcontextprotocol/sdk/server/mcp.js');
const { StdioServerTransport } = require('@modelcontextprotocol/sdk/server/stdio.js');
const { z } = require('zod');
const axios = require('axios');

const GITLAB_BASE_URL = (process.env.GITLAB_BASE_URL || 'https://gitlab.com').replace(/\/$/, '');
const GITLAB_TOKEN = process.env.GITLAB_TOKEN;
const GITLAB_PROJECT_ID = process.env.GITLAB_PROJECT_ID;

if (!GITLAB_TOKEN || !GITLAB_PROJECT_ID) {
  console.error('GITLAB_TOKEN and GITLAB_PROJECT_ID are required');
  process.exit(1);
}

const client = axios.create({
  baseURL: `${GITLAB_BASE_URL}/api/v4`,
  headers: { 'PRIVATE-TOKEN': GITLAB_TOKEN, 'Content-Type': 'application/json' },
});

const P = `/projects/${GITLAB_PROJECT_ID}`;
const server = new McpServer({ name: 'gitlab-mcp', version: '1.0.0' });

server.tool('create_branch', 'Create a new branch in the GitLab project', {
  branch_name: z.string().describe('Name of the new branch'),
  ref: z.string().optional().describe('Source branch or commit SHA (default: main)'),
}, async ({ branch_name, ref = 'main' }) => {
  try {
    const { data } = await client.post(`${P}/repository/branches`, { branch: branch_name, ref });
    return { content: [{ type: 'text', text: JSON.stringify({ name: data.name, commit_id: data.commit?.id }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('commit_files', 'Commit one or more file changes to a branch', {
  branch: z.string().describe('Target branch name'),
  commit_message: z.string().describe('Commit message'),
  actions: z.string().describe('JSON array: [{"action":"create"|"update"|"delete","file_path":"...","content":"..."}]'),
}, async ({ branch, commit_message, actions }) => {
  try {
    const { data } = await client.post(`${P}/repository/commits`, { branch, commit_message, actions: JSON.parse(actions) });
    return { content: [{ type: 'text', text: JSON.stringify({ id: data.id, short_id: data.short_id, title: data.title }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('create_merge_request', 'Create a merge request', {
  source_branch: z.string().describe('Source branch'),
  target_branch: z.string().describe('Target branch (e.g., main)'),
  title: z.string().describe('MR title'),
  description: z.string().describe('MR description (markdown)'),
}, async ({ source_branch, target_branch, title, description }) => {
  try {
    const { data } = await client.post(`${P}/merge_requests`, { source_branch, target_branch, title, description });
    return { content: [{ type: 'text', text: JSON.stringify({ iid: data.iid, web_url: data.web_url, title: data.title, state: data.state }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('get_merge_request', 'Get merge request details by IID', {
  mr_iid: z.string().describe('Merge request IID'),
}, async ({ mr_iid }) => {
  try {
    const { data } = await client.get(`${P}/merge_requests/${mr_iid}`);
    return { content: [{ type: 'text', text: JSON.stringify({ iid: data.iid, title: data.title, state: data.state, source_branch: data.source_branch, web_url: data.web_url, description: data.description }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('update_merge_request', 'Update a merge request', {
  mr_iid: z.string().describe('Merge request IID'),
  title: z.string().optional().describe('New title'),
  description: z.string().optional().describe('New description'),
}, async ({ mr_iid, title, description }) => {
  try {
    const updates = {};
    if (title) updates.title = title;
    if (description) updates.description = description;
    const { data } = await client.put(`${P}/merge_requests/${mr_iid}`, updates);
    return { content: [{ type: 'text', text: JSON.stringify({ iid: data.iid, title: data.title, state: data.state }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('list_mr_comments', 'List all comments on a merge request', {
  mr_iid: z.string().describe('Merge request IID'),
}, async ({ mr_iid }) => {
  try {
    const { data } = await client.get(`${P}/merge_requests/${mr_iid}/notes`, { params: { sort: 'asc', order_by: 'created_at' } });
    const comments = data.map(n => ({ id: n.id, author: n.author?.username, body: n.body, created_at: n.created_at, system: n.system, resolvable: n.resolvable, resolved: n.resolved }));
    return { content: [{ type: 'text', text: JSON.stringify(comments, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('post_mr_comment', 'Post a comment on a merge request', {
  mr_iid: z.string().describe('Merge request IID'),
  body: z.string().describe('Comment body (markdown)'),
}, async ({ mr_iid, body }) => {
  try {
    const { data } = await client.post(`${P}/merge_requests/${mr_iid}/notes`, { body });
    return { content: [{ type: 'text', text: JSON.stringify({ id: data.id, body: data.body }, null, 2) }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

server.tool('get_file', 'Read a file from the repository', {
  file_path: z.string().describe('Path to the file in the repo'),
  ref: z.string().optional().describe('Branch or commit SHA (default: main)'),
}, async ({ file_path, ref = 'main' }) => {
  try {
    const { data } = await client.get(`${P}/repository/files/${encodeURIComponent(file_path)}`, { params: { ref } });
    return { content: [{ type: 'text', text: Buffer.from(data.content, 'base64').toString('utf-8') }] };
  } catch (err) {
    return { content: [{ type: 'text', text: `Error: ${err.response?.data?.message || err.message}` }], isError: true };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
main().catch((err) => { console.error('GitLab MCP failed:', err); process.exit(1); });
