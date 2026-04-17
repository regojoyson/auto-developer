[< Back to README](../README.md) | [Setup](setup.md) | [How It Works](how-it-works.md) | [Configuration](configuration.md) | [API Spec](api-spec.md) | [Custom Providers](custom-providers.md)

---

# Prerequisites

Everything you need before running Auto Developer.

---

## Required

### 1. Python >= 3.10

```bash
python3 --version   # must be 3.10 or higher
```

Install: https://python.org/downloads/ or `brew install python@3.12`

### 2. AI Coding CLI

Install the CLI for your chosen adapter:

| Adapter | Install | Verify |
|---------|---------|--------|
| Claude Code | https://docs.anthropic.com/en/docs/claude-code | `claude --version` |
| Codex | `npm install -g @openai/codex` | `codex --version` |
| Gemini | https://github.com/google-gemini/gemini-cli | `gemini --version` |

The CLI must be **authenticated** — run it once manually to log in before using Auto Developer.

### 3. Git

```bash
git --version
```

Required for the repo checkout/pull operations.

### 4. Tokens / API Keys

**Issue tracker (always required — server calls REST API):**

| Tracker | Credentials | Where |
|---------|-------------|-------|
| Jira | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` | `.env` |
| GitHub Issues | `GITHUB_TOKEN` (Issues scope), `GITHUB_OWNER` | `.env` |

Jira tokens: https://id.atlassian.com/manage-profile/security/api-tokens

**Git provider:**

| Provider | Token scope |
|----------|------------|
| GitLab | Personal access token with `api` scope |
| GitHub | Fine-grained token: Contents (R/W), Pull Requests (R/W), Issues (R) |

Project IDs / owner-repo pairs are auto-detected from each repo's git remote URL.

---

## MCP Servers

Auto Developer agents use **MCP servers** only for git-provider operations (creating branches, reading MR/PR comments during rework). The issue tracker is NOT accessed via MCP — the Python server calls its REST API directly.

### Built-in — GitLab/GitHub git MCP

Included in `mcp_servers/` and wired up automatically by `start.sh`. No manual setup needed.

### Optional — Slack MCP (only if notifications enabled)

If you enabled Slack notifications in `config.yaml`, configure Slack MCP in your CLI separately:

```json
{
  "mcpServers": {
    "slack": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-slack"],
      "env": { "SLACK_BOT_TOKEN": "xoxb-your-slack-bot-token" }
    }
  }
}
```

For other CLIs (Codex, Gemini), refer to their documentation.

### What happens if something isn't configured

| Missing | Impact |
|---------|--------|
| Jira/GitHub REST credentials in `.env` | Pipeline can't read tickets → repo-picker fails, no analyze/plan comments posted. |
| Slack MCP (when notifications enabled) | No Slack messages; pipeline still runs. |
| Git MCP (built-in) | Agents can't create branches or read MR comments. Pipeline fails. Auto-configured by `start.sh`. |

---

## Checklist

Before running `./setup.sh`:

- [ ] Python >= 3.10 installed
- [ ] AI coding CLI installed and authenticated (e.g. `claude --version` works)
- [ ] Git installed
- [ ] Git provider token ready (GitLab or GitHub)
- [ ] **Issue tracker credentials ready** (Jira: URL + email + token, or GitHub Issues: token + owner)
- [ ] Slack MCP configured in your CLI (only if you plan to enable notifications)
- [ ] Server with public IP or domain (for webhook delivery — see the "Webhooks" section of [setup.md](setup.md))
