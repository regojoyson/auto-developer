# AI Dev Pipeline — Global Agent Rules

## Commit Message Format
- Features: `feat(PROJ-123): <short description>`
- Bug fixes: `fix(PROJ-123): <short description>`
- Always include the Jira issue key in every commit message

## Branch Naming
- Features: `feature/PROJ-123-kebab-slug`
- Bug fixes: `fix/PROJ-123-kebab-slug`
- Slug derived from Jira summary, max 40 chars, lowercase, hyphens only

## Agent Behavior Rules
- Never modify files outside the ticket scope
- Never push directly to `main` or `develop`
- Never modify `TICKET.md` after it is written by the orchestrator
- On rework: only change what `FEEDBACK.md` requests — no speculative refactors
- Always check pipeline state before starting work to avoid duplicate invocations
- Always reference the Jira issue key in MR titles and commit messages

## Code Standards
- Use CommonJS (`require`) for Node.js modules
- Use `const` by default, `let` only when reassignment is needed
- Error handling: always catch and log errors with context (issue key, branch name)
- No unused imports or variables
- Keep functions focused — one purpose per function

## MCP Servers Available
- **Jira MCP**: Read tickets, post comments, transition issues
- **GitLab MCP** (custom): Create branches, commit files, create/update MRs, read MR comments
- **Slack MCP**: Send notifications to team channels

## Pipeline State Machine
States: `brainstorming` → `developing` → `awaiting-review` → `reworking` → `merged`
- Check state before any agent invocation
- Rework capped at 3 iterations — escalate to Slack if exceeded
