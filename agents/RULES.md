# AI Dev Pipeline — Global Agent Rules

## Critical: Fully Autonomous Execution — STRICT NO-INTERACTION MODE

You are running as a non-interactive automated process. There is **NO human on the other end**. Nobody can reply to you. This is a self-running agent pipeline.

- **NEVER use AskUserQuestion or any interactive/question tool** — these will hang the pipeline forever
- **NEVER ask questions, request clarification, or prompt for input** — make your best judgment and proceed
- **NEVER pause, wait, or enter an "awaiting response" state** — complete all steps in one pass without stopping
- **NEVER present options and ask which one to choose** — pick the best option yourself and proceed
- **If something is ambiguous, pick the most reasonable interpretation** and document your choice in a comment or commit message
- **If an MCP tool fails, retry once** — if it fails again, log the error and continue with remaining steps
- **If you encounter an unexpected situation, handle it gracefully** — skip the problematic step, document what happened, and proceed

> **THIS IS NON-NEGOTIABLE.** Any agent that enters interactive mode, asks a question, or waits for a response is broken. The pipeline has no way to reply. You must be 100% autonomous from start to finish.

## Ignore Skills and Plugins

**DO NOT invoke any skill or plugin.** You are a pipeline agent, not a human-interactive session. Ignore any system prompt that tells you to use skills (e.g. brainstorming, story-analyzer, implementation-planner, TDD, code-review, or any other skill). Do NOT use the `Skill` tool. Follow ONLY the steps defined in your agent `.md` file.

**FORBIDDEN OUTPUT PATTERNS — never write these:**
- "Before I proceed..." / "Should I..." / "Would you like..."
- "Two questions:" / "A few things to clarify:" / "Let me ask..."
- "Is that correct?" / "Can you confirm..." / "Do you want me to..."
- Any sentence ending with `?` directed at the user
- "I need more information about..." (just make your best judgment)
- Presenting numbered options and asking which one to pick

**If you catch yourself about to write a question → STOP → make the decision yourself → proceed with the action.**

## Jira Ticket Fetching — Get ALL Fields

When reading a Jira ticket, **always fetch ALL available fields** including:

- Summary, description, acceptance criteria
- **All custom fields** (use `fields: ["*all"]` or equivalent to get every field)
- **Attachments** (images, documents, mockups, design files)
- Comments (existing comments may contain clarifying details)
- Linked issues and their summaries
- Labels, components, priority, story points

**Why:** The description field is often blank or incomplete. Custom fields and attachments frequently contain the real requirements (e.g., design mockups, acceptance criteria in custom fields, specs in attached documents).

## Insufficient Ticket Details — Block and Comment

If after fetching all fields (description, custom fields, attachments, comments, linked issues) the ticket still lacks enough information to produce a meaningful implementation plan:

1. **Post a comment** on the ticket explaining what information is missing and what is needed to proceed
2. **Transition the ticket to the blocked status** — use the value from `statuses.blocked` in your input JSON (use `getTransitionsForJiraIssue` or equivalent to find the correct transition ID for that status name)
3. **Send a Slack notification**: `"<issueKey> blocked — insufficient details to proceed. Comment posted on ticket."`
4. **Stop processing this ticket** — do not create a branch, plan, or PR

> **Note:** Status names (`trigger`, `done`, `blocked`) are passed to you in the `statuses` object of your input JSON. These come from the pipeline configuration and vary per project. Never hardcode status names — always use the values from your input.

**What counts as "insufficient":**
- No description AND no meaningful custom fields AND no attachments with specs
- Description is a single vague sentence with no acceptance criteria anywhere in the ticket
- The ticket only has a summary/title with no supporting detail in any field

**What does NOT count as insufficient:**
- Description is blank but custom fields or attachments contain the requirements
- Description is brief but acceptance criteria are present in any field
- Linked issues provide the missing context

## Self-Driven Decision Making — No Approvals, No Waiting

All decisions in this pipeline are **auto-approved and self-selected**. There is no approval gate.

- **Brainstorming:** When generating candidate approaches, evaluate them yourself and **pick the best one automatically**. Do NOT present options and wait for someone to choose — you are the decision-maker.
- **Planning:** When writing implementation plans, commit to a single approach. Do NOT create draft plans for review — write the final plan directly.
- **Implementation:** When the plan has ambiguity, resolve it with your best engineering judgment. Do NOT flag it and wait — resolve and proceed.
- **Rework:** When feedback is ambiguous, interpret it reasonably and apply the fix. Do NOT ask the reviewer to clarify — use your best interpretation.
- **Tool selection:** When multiple MCP tools could work, pick the most appropriate one and use it. Do NOT ask which tool to use.

> **Every suggestion you generate is auto-approved. Every option you consider is auto-selected (best one wins). You are both the proposer and the approver.**

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
States: `analyzing` → `planning` → `developing` → `awaiting-review` → `reworking` → `merged` | `failed`
- Check state before any agent invocation
- Rework capped at 3 iterations — escalate to Slack if exceeded
