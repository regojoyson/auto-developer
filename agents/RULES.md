# AI Dev Pipeline — Global Agent Rules

## Critical: Fully Autonomous Execution

You are running as a non-interactive automated process. There is no human to answer questions.

- **NEVER ask questions or request clarification** — make your best judgment and proceed
- **NEVER pause or wait for input** — complete all steps in one pass
- **If something is ambiguous, pick the most reasonable interpretation** and document your choice in a comment or commit message
- **If an MCP tool fails, retry once** — if it fails again, log the error and continue with remaining steps
- **If you encounter an unexpected situation, handle it gracefully** — skip the problematic step, document what happened, and proceed

## Commit Message Format
- Features: `feat(PROJ-123): <short description>`
- Bug fixes: `fix(PROJ-123): <short description>`
- Always include the issue key in every commit message

## Branch Naming
- Features: `feature/PROJ-123-kebab-slug`
- Bug fixes: `fix/PROJ-123-kebab-slug`
- Slug derived from ticket summary, max 40 chars, lowercase, hyphens only

## Agent Behavior Rules
- Never modify files outside the ticket scope
- Never push directly to `main` or `develop`
- Never modify `TICKET.md` after it is written by the orchestrator
- On rework: only change what `FEEDBACK.md` requests — no speculative refactors
- Always reference the issue key in PR/MR titles and commit messages

## Code Standards
- Follow the existing codebase conventions (language, formatting, patterns)
- Error handling: always catch and log errors with context (issue key, branch name)
- No unused imports or variables
- Keep functions focused — one purpose per function

## MCP Servers Available
- **Issue Tracker MCP**: Read tickets, post comments, transition issues
- **Git Provider MCP**: Create branches, commit files, create/update PRs, read/post PR comments
- **Slack MCP**: Send notifications to team channels

## Pipeline State Machine
States: `brainstorming` → `developing` → `awaiting-review` → `reworking` → `merged`
- Check state before any agent invocation
- Rework capped at 3 iterations — escalate to Slack if exceeded
