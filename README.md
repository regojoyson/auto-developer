# Auto Developer

**Ticket  ->  AI Agents  ->  Pull Request  ->  Review Loop**

An open-source pipeline that automates the full development lifecycle. When a ticket is marked ready, AI agents take over — they brainstorm approaches, write an implementation plan, code the solution, and open a pull request. The human reviewer stays in control: approve, edit, or leave feedback that triggers an automatic rework cycle.

No manual handoffs. No copy-pasting tickets into prompts. Just move a ticket to "Ready for Development" and the code shows up as a PR.

---

## How It Works

<p align="center">
  <img src="docs/architecture.svg" alt="Auto Developer Architecture" width="800"/>
</p>

**The pipeline in 30 seconds:**
- A ticket arrives (via webhook or manual API call)
- **Orchestrator** checks out the latest base branch, creates a feature branch
- **Brainstorm agent** explores the codebase, writes `PLAN.md` with the best approach
- **Developer agent** implements from the plan, commits code
- A **PR/MR is created** automatically with description and file change summary
- **Human reviews** — approve to merge, or comment to trigger a rework cycle
- **Feedback parser** structures the review comments, developer agent applies fixes
- Loop until approved or rework limit hit (then escalate)

---

## Review Loop

<p align="center">
  <img src="docs/review-loop.svg" alt="Review Loop" width="700"/>
</p>

After the PR is created, the pipeline pauses and waits for the human reviewer. Three outcomes:

| Action | What happens |
|--------|-------------|
| **Approve** | PR merged, ticket closed, team notified |
| **Push edits** | Pipeline detects human commits, waits for approval |
| **Comment feedback** | Feedback parser + developer rework cycle (max 3 rounds) |

---

## Pluggable Providers

<p align="center">
  <img src="docs/providers.svg" alt="Pluggable Providers" width="750"/>
</p>

Everything is swappable via a single `config.yaml`. Add your own providers by extending a base class — see [Custom Providers Guide](docs/custom-providers.md).

---

## Quick Start

```bash
git clone https://github.com/regojoyson/auto-developer.git
cd auto-developer

./setup.sh     # interactive wizard — generates config
# fill in tokens in .env
./start.sh     # validates, starts server + ngrok
```

```bash
./stop.sh      # stops everything, cleans up
```

Trigger manually without a webhook:
```bash
curl -X POST http://localhost:3000/api/trigger \
  -H 'Content-Type: application/json' \
  -d '{"issueKey": "PROJ-42", "summary": "Add login page"}'
```

Check pipeline status:
```bash
curl http://localhost:3000/api/status/PROJ-42
```

---

## Documentation

| Doc | What it covers |
|-----|---------------|
| **[Setup Guide](docs/setup.md)** | Step-by-step from zero to running |
| **[How It Works](docs/how-it-works.md)** | Full pipeline flow, agents, review loop |
| **[Configuration](docs/configuration.md)** | All `config.yaml` options with examples |
| **[API Spec](docs/api-spec.md)** | Every HTTP endpoint, request/response formats |
| **[OpenAPI Spec](docs/openapi.yaml)** | Import into Postman, Swagger UI, or any API tool |
| **[Custom Providers](docs/custom-providers.md)** | Add your own issue tracker, git provider, CLI, or notification |
| **[Spec Document](docs/spec.md)** | Architecture, agent contracts, risks |

---

## Project Structure

```
auto-developer/
├── .claude/agents/              # Agent prompts (orchestrator, brainstorm, developer, feedback-parser)
├── src/
│   ├── config.js                # Unified config loader (reads config.yaml)
│   ├── webhook/routes/          # issue-tracker, git-provider, trigger, status
│   ├── providers/               # Pluggable adapters
│   │   ├── base/                # Abstract base classes (4 types)
│   │   ├── trackers/            # Jira, GitHub Issues
│   │   ├── git/                 # GitLab, GitHub
│   │   ├── cli/                 # Claude Code, Codex, Gemini
│   │   └── notifications/       # Slack
│   ├── state/manager.js         # Pipeline state machine
│   └── agents/runner.js         # CLI process spawner
├── mcp-servers/                 # GitLab + GitHub MCP servers (8 tools each)
├── docs/                        # All documentation + diagrams
├── config.yaml                  # Single config file
├── .env                         # Secrets only (tokens)
└── setup.sh / start.sh / stop.sh
```

---

## License

ISC
