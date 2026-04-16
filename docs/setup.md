[< Back to README](../README.md) | [Prerequisites](prerequisites.md) | [How It Works](how-it-works.md) | [Configuration](configuration.md) | [API Spec](api-spec.md) | [Custom Providers](custom-providers.md)

---

# Setup Guide

Get auto-pilot running from zero.

---

## Prerequisites

Before starting, make sure you have everything installed and configured.
See the full checklist: **[prerequisites.md](prerequisites.md)**

Key items:
- **Node.js** >= 18
- **AI Coding CLI** installed and authenticated (Claude Code / Codex / Gemini)
- **Git** installed
- **Git provider token** (GitLab or GitHub)
- **Jira MCP configured in your CLI** (if using Jira as issue tracker)
- **Slack MCP configured in your CLI** (if using Slack notifications)
- **Server with public IP or domain** (for webhook delivery from issue trackers / git providers)

**Important:** The Jira and Slack MCP servers are configured in your CLI tool (e.g. `~/.claude/settings.json`), not in Auto Developer. See [prerequisites.md](prerequisites.md) for setup instructions.

---

## Step 1: Clone auto-pilot

```bash
git clone https://github.com/regojoyson/auto-developer.git
cd auto-developer
```

---

## Step 2: Run the setup wizard

```bash
./setup.sh
```

The wizard asks:

```
? Where is your code?
  1) Local directory (one repo)
  2) Parent directory (multiple repos)
  3) Clone from git URL(s)

? Git provider: (gitlab / github)
? Issue tracker: (jira / github-issues)
? AI coding CLI: (claude-code / codex / gemini)
? Base branch to create features from: (main)
? Enable notifications? (y/n)
```

This generates:
- **`config.yaml`** — all settings (repo, providers, pipeline)
- **`.env`** — token placeholders

It also symlinks agent files into your target repo(s):
- Creates `.auto-developer/` symlink (reference to our agent configs)
- Symlinks each agent `.md` file into the CLI's agent directory (e.g. `.claude/agents/`)
- Symlinks `CLAUDE.md` into the CLI's config directory

This works even if your repo already has a `.claude/` directory — we only add individual files, never overwrite the whole directory.

If you prefer to write `config.yaml` by hand, see [configuration.md](configuration.md).

If you already have a `config.yaml` and re-run `./setup.sh`, it asks if you want to reconfigure or keep the existing config.

---

## Step 3: Fill in your tokens

Edit `.env` — only secrets go here:

**For GitLab:**
```bash
GITLAB_BASE_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
```

**For GitHub:**
```bash
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

Project IDs and owner/repo are auto-detected from each repo's git remote URL — you don't need to set them.

### How to get tokens

**GitLab:**
1. Go to GitLab > Settings > Access Tokens
2. Create a token with `api` scope
3. Copy the token and your numeric project ID (found on the project's main page)

**GitHub:**
1. Go to GitHub > Settings > Developer Settings > Personal Access Tokens > Fine-grained tokens
2. Select the repo, grant: Contents (read/write), Pull Requests (read/write), Issues (read)
3. Copy the token

---

## Step 4: Start

```bash
./start.sh
```

This will:
1. Check Node.js and CLI are installed
2. Install npm dependencies
3. Validate your config and tokens
4. Generate the MCP server config
5. Start the webhook server
6. Print webhook URLs to configure

You should see:
```
═══════════════════════════════════════════════
  Auto-Pilot running!
  jira + gitlab + claude-code
═══════════════════════════════════════════════

  Health: curl http://localhost:3000/health
  Press Ctrl+C to stop
```

---

## Step 5: Configure webhooks

Use your server's public URL with the paths printed by `start.sh`:

### Jira webhook

1. Go to Jira > Settings > System > Webhooks
2. Add a new webhook:
   - URL: `https://<your-url>/webhooks/issue-tracker`
   - Events: **Issue updated**
3. Save

### GitHub Issues webhook

1. Go to your GitHub repo > Settings > Webhooks > Add webhook
2. Payload URL: `https://<your-url>/webhooks/issue-tracker`
3. Content type: `application/json`
4. Events: **Issues**
5. Save

### GitLab webhook

1. Go to your GitLab project > Settings > Webhooks
2. URL: `https://<your-url>/webhooks/git`
3. Trigger: **Merge request events**, **Push events**, **Comments**
4. Save

### GitHub PR webhook

1. Go to your GitHub repo > Settings > Webhooks > Add webhook
2. URL: `https://<your-url>/webhooks/git`
3. Events: **Pull requests**, **Pull request reviews**, **Issue comments**, **Pushes**
4. Save

---

## Step 6: Test it

### Option A: Manual trigger

```bash
curl -X POST http://localhost:3000/api/trigger \
  -H 'Content-Type: application/json' \
  -d '{"issueKey": "PROJ-1", "summary": "Test ticket"}'
```

### Option B: Move a Jira ticket

Move a ticket to "Ready for Development" in Jira. The webhook fires and the pipeline starts.

### Check status

```bash
# All pipelines
curl http://localhost:3000/api/status

# Specific ticket
curl http://localhost:3000/api/status/PROJ-1
```

---

## Stopping

```bash
./stop.sh
```

This kills the server and removes agent symlinks from your repos.

---

## Troubleshooting

**"config.yaml not found"**
Run `./setup.sh` first.

**"GITLAB_TOKEN not set"**
Edit `.env` and add your token. See Step 3.

**"Webhook not received"**
- Is the server reachable from the internet? Check with `curl http://<your-host>:3000/health`
- Does the URL in Jira/GitHub match your server's public address?
- Test locally: `curl -X POST http://localhost:3000/webhooks/issue-tracker -H 'Content-Type: application/json' -d '{}'`

**"Agent timed out"**
Increase `pipeline.agentTimeout` in `config.yaml` (default 300000ms = 5 min).

**"Pipeline already active"**
Delete the state file: `rm .pipeline-state/feature__PROJ-42*.json`

**"Claude Code CLI not found"**
Install it: https://docs.anthropic.com/en/docs/claude-code

---

## Next steps

- [How It Works](how-it-works.md) — understand the full pipeline flow
- [Configuration Reference](configuration.md) — all config.yaml options
- [API Specification](api-spec.md) — all HTTP endpoints
