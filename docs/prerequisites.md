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

You need tokens for your chosen git provider:

**GitLab:**
- Personal access token with `api` scope
- Numeric project ID (from project settings page)

**GitHub:**
- Personal access token (fine-grained) with: Contents (read/write), Pull Requests (read/write), Issues (read)
- Repository owner and name

---

## MCP Servers (Important)

Auto Developer agents use **MCP servers** to interact with external services. Some MCP servers are **built-in** to this project, and some need to be **configured in your CLI tool separately**.

### Built-in MCP servers (we handle this)

These are included in the `mcp-servers/` directory and configured automatically by `start.sh`:

| MCP Server | What it does |
|------------|-------------|
| **GitLab MCP** | Create branches, commit files, create/update MRs, read comments |
| **GitHub MCP** | Create branches, commit files, create/update PRs, read comments |

`start.sh` generates `settings.json` in the correct CLI config directory (e.g. `.claude/settings.json`) so the CLI picks them up automatically.

### External MCP servers (you configure in your CLI)

These MCP servers are **not** included in Auto Developer. You need to configure them in your CLI tool's settings:

| MCP Server | What it does | How to configure |
|------------|-------------|-----------------|
| **Jira MCP** (Atlassian) | Read tickets, post comments, transition issues | Configure in your CLI's MCP settings (e.g. `.claude/settings.json`) |
| **Slack MCP** | Send notifications to channels | Configure in your CLI's MCP settings |

#### Configuring Jira MCP in Claude Code

Add to your **user-level** Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "atlassian": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-atlassian"],
      "env": {
        "JIRA_URL": "https://your-org.atlassian.net",
        "JIRA_EMAIL": "your-email@example.com",
        "JIRA_API_TOKEN": "your-jira-api-token"
      }
    }
  }
}
```

#### Configuring Slack MCP in Claude Code

```json
{
  "mcpServers": {
    "slack": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-slack"],
      "env": {
        "SLACK_BOT_TOKEN": "xoxb-your-slack-bot-token"
      }
    }
  }
}
```

For other CLIs (Codex, Gemini), refer to their documentation for MCP server configuration.

### What happens if MCP servers aren't configured?

| Missing MCP | Impact |
|-------------|--------|
| Jira MCP | Orchestrator can't read ticket details or post comments. Agents still run but with less context. |
| Slack MCP | No notifications sent. Pipeline still works, you just won't get Slack messages. |
| Git MCP (built-in) | Agents can't create branches or commit code. Pipeline fails. This is auto-configured by `start.sh`. |

---

---

## Checklist

Before running `./setup.sh`:

- [ ] Python >= 3.10 installed
- [ ] AI coding CLI installed and authenticated (e.g. `claude --version` works)
- [ ] Git installed
- [ ] Git provider token ready (GitLab or GitHub)
- [ ] Jira MCP configured in your CLI (if using Jira)
- [ ] Slack MCP configured in your CLI (if using notifications)
- [ ] Server with public IP or domain (for webhook delivery)
