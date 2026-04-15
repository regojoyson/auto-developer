/**
 * @module mcp-servers/gitlab
 * @description Custom MCP (Model Context Protocol) server that exposes GitLab
 * REST API operations as tools available to Claude Code agents.
 *
 * This is the **critical integration piece** — GitLab has no official MCP
 * server, so this custom server enables agents to create branches, commit
 * files, create/update merge requests, and read/post MR comments.
 *
 * Runs as a stdio MCP server — Claude Code communicates with it over
 * stdin/stdout. Configured in `.claude/settings.json`.
 *
 * Tools provided:
 *   - `create_branch`        — Create a new Git branch
 *   - `commit_files`         — Commit file changes (create/update/delete)
 *   - `create_merge_request` — Open a new MR
 *   - `get_merge_request`    — Read MR details
 *   - `update_merge_request` — Update MR title/description
 *   - `list_mr_comments`     — List all notes on an MR
 *   - `post_mr_comment`      — Post a comment on an MR
 *   - `get_file`             — Read a file from the repo at a given ref
 *
 * Required environment variables:
 *   - `GITLAB_BASE_URL`  — GitLab instance URL (e.g. https://gitlab.com)
 *   - `GITLAB_TOKEN`     — Personal access token with `api` scope
 *   - `GITLAB_PROJECT_ID` — Numeric project ID
 */

const { McpServer } = require('@modelcontextprotocol/sdk/server/mcp.js');
const { StdioServerTransport } = require('@modelcontextprotocol/sdk/server/stdio.js');
const axios = require('axios');

const GITLAB_BASE_URL = (process.env.GITLAB_BASE_URL || 'https://gitlab.com').replace(/\/$/, '');
const GITLAB_TOKEN = process.env.GITLAB_TOKEN;
const GITLAB_PROJECT_ID = process.env.GITLAB_PROJECT_ID;

if (!GITLAB_TOKEN || !GITLAB_PROJECT_ID) {
  console.error('GITLAB_TOKEN and GITLAB_PROJECT_ID environment variables are required');
  process.exit(1);
}

const client = axios.create({
  baseURL: `${GITLAB_BASE_URL}/api/v4`,
  headers: {
    'PRIVATE-TOKEN': GITLAB_TOKEN,
    'Content-Type': 'application/json',
  },
});

const server = new McpServer({
  name: 'gitlab-mcp',
  version: '1.0.0',
});

// --- Tool: create_branch ---
server.tool(
  'create_branch',
  'Create a new branch in the GitLab project',
  {
    branch_name: { type: 'string', description: 'Name of the new branch' },
    ref: { type: 'string', description: 'Source branch or commit SHA to branch from (default: main)' },
  },
  async ({ branch_name, ref = 'main' }) => {
    try {
      const { data } = await client.post(
        `/projects/${GITLAB_PROJECT_ID}/repository/branches`,
        { branch: branch_name, ref }
      );
      return { content: [{ type: 'text', text: JSON.stringify({ name: data.name, commit_id: data.commit?.id }, null, 2) }] };
    } catch (err) {
      const msg = err.response?.data?.message || err.message;
      return { content: [{ type: 'text', text: `Error creating branch: ${msg}` }], isError: true };
    }
  }
);

// --- Tool: commit_files ---
server.tool(
  'commit_files',
  'Commit one or more file changes to a branch',
  {
    branch: { type: 'string', description: 'Target branch name' },
    commit_message: { type: 'string', description: 'Commit message' },
    actions: {
      type: 'string',
      description: 'JSON array of actions: [{"action":"create"|"update"|"delete","file_path":"...","content":"..."}]',
    },
  },
  async ({ branch, commit_message, actions }) => {
    try {
      const parsedActions = JSON.parse(actions);
      const { data } = await client.post(
        `/projects/${GITLAB_PROJECT_ID}/repository/commits`,
        { branch, commit_message, actions: parsedActions }
      );
      return { content: [{ type: 'text', text: JSON.stringify({ id: data.id, short_id: data.short_id, title: data.title }, null, 2) }] };
    } catch (err) {
      const msg = err.response?.data?.message || err.message;
      return { content: [{ type: 'text', text: `Error committing files: ${msg}` }], isError: true };
    }
  }
);

// --- Tool: create_merge_request ---
server.tool(
  'create_merge_request',
  'Create a merge request in the GitLab project',
  {
    source_branch: { type: 'string', description: 'Source branch' },
    target_branch: { type: 'string', description: 'Target branch (e.g., main)' },
    title: { type: 'string', description: 'MR title' },
    description: { type: 'string', description: 'MR description (markdown)' },
  },
  async ({ source_branch, target_branch, title, description }) => {
    try {
      const { data } = await client.post(
        `/projects/${GITLAB_PROJECT_ID}/merge_requests`,
        { source_branch, target_branch, title, description }
      );
      return {
        content: [{
          type: 'text',
          text: JSON.stringify({ iid: data.iid, web_url: data.web_url, title: data.title, state: data.state }, null, 2),
        }],
      };
    } catch (err) {
      const msg = err.response?.data?.message || err.message;
      return { content: [{ type: 'text', text: `Error creating MR: ${msg}` }], isError: true };
    }
  }
);

// --- Tool: get_merge_request ---
server.tool(
  'get_merge_request',
  'Get details of a merge request by IID',
  {
    mr_iid: { type: 'string', description: 'Merge request IID (integer)' },
  },
  async ({ mr_iid }) => {
    try {
      const { data } = await client.get(
        `/projects/${GITLAB_PROJECT_ID}/merge_requests/${mr_iid}`
      );
      return {
        content: [{
          type: 'text',
          text: JSON.stringify({
            iid: data.iid, title: data.title, state: data.state,
            source_branch: data.source_branch, target_branch: data.target_branch,
            web_url: data.web_url, description: data.description,
          }, null, 2),
        }],
      };
    } catch (err) {
      const msg = err.response?.data?.message || err.message;
      return { content: [{ type: 'text', text: `Error getting MR: ${msg}` }], isError: true };
    }
  }
);

// --- Tool: update_merge_request ---
server.tool(
  'update_merge_request',
  'Update a merge request (title, description, etc.)',
  {
    mr_iid: { type: 'string', description: 'Merge request IID' },
    title: { type: 'string', description: 'New title (optional)' },
    description: { type: 'string', description: 'New description (optional)' },
  },
  async ({ mr_iid, title, description }) => {
    try {
      const updates = {};
      if (title) updates.title = title;
      if (description) updates.description = description;
      const { data } = await client.put(
        `/projects/${GITLAB_PROJECT_ID}/merge_requests/${mr_iid}`,
        updates
      );
      return { content: [{ type: 'text', text: JSON.stringify({ iid: data.iid, title: data.title, state: data.state }, null, 2) }] };
    } catch (err) {
      const msg = err.response?.data?.message || err.message;
      return { content: [{ type: 'text', text: `Error updating MR: ${msg}` }], isError: true };
    }
  }
);

// --- Tool: list_mr_comments ---
server.tool(
  'list_mr_comments',
  'List all comments/notes on a merge request',
  {
    mr_iid: { type: 'string', description: 'Merge request IID' },
  },
  async ({ mr_iid }) => {
    try {
      const { data } = await client.get(
        `/projects/${GITLAB_PROJECT_ID}/merge_requests/${mr_iid}/notes`,
        { params: { sort: 'asc', order_by: 'created_at' } }
      );
      const comments = data.map((note) => ({
        id: note.id,
        author: note.author?.username,
        body: note.body,
        created_at: note.created_at,
        system: note.system,
        resolvable: note.resolvable,
        resolved: note.resolved,
      }));
      return { content: [{ type: 'text', text: JSON.stringify(comments, null, 2) }] };
    } catch (err) {
      const msg = err.response?.data?.message || err.message;
      return { content: [{ type: 'text', text: `Error listing MR comments: ${msg}` }], isError: true };
    }
  }
);

// --- Tool: post_mr_comment ---
server.tool(
  'post_mr_comment',
  'Post a comment on a merge request',
  {
    mr_iid: { type: 'string', description: 'Merge request IID' },
    body: { type: 'string', description: 'Comment body (markdown)' },
  },
  async ({ mr_iid, body }) => {
    try {
      const { data } = await client.post(
        `/projects/${GITLAB_PROJECT_ID}/merge_requests/${mr_iid}/notes`,
        { body }
      );
      return { content: [{ type: 'text', text: JSON.stringify({ id: data.id, body: data.body }, null, 2) }] };
    } catch (err) {
      const msg = err.response?.data?.message || err.message;
      return { content: [{ type: 'text', text: `Error posting comment: ${msg}` }], isError: true };
    }
  }
);

// --- Tool: get_file ---
server.tool(
  'get_file',
  'Read a file from the repository at a specific branch/ref',
  {
    file_path: { type: 'string', description: 'Path to the file in the repo' },
    ref: { type: 'string', description: 'Branch name or commit SHA (default: main)' },
  },
  async ({ file_path, ref = 'main' }) => {
    try {
      const encodedPath = encodeURIComponent(file_path);
      const { data } = await client.get(
        `/projects/${GITLAB_PROJECT_ID}/repository/files/${encodedPath}`,
        { params: { ref } }
      );
      const content = Buffer.from(data.content, 'base64').toString('utf-8');
      return { content: [{ type: 'text', text: content }] };
    } catch (err) {
      const msg = err.response?.data?.message || err.message;
      return { content: [{ type: 'text', text: `Error reading file: ${msg}` }], isError: true };
    }
  }
);

// --- Start server ---
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error('GitLab MCP server failed to start:', err);
  process.exit(1);
});
