"""Per-phase tool sandbox for agent invocations.

A PhaseScope describes the tool / subagent / MCP-server envelope an agent
runs inside for a single pipeline phase. CLI adapters translate it into
native flags (e.g. Claude Code `--allowed-tools`).

Fields set to None mean "no override" — the adapter's default applies.
An empty tuple () means "explicitly empty" (e.g. no MCP servers at all).

Usage::

    from src.executor.phase_scope import ANALYZE_SCOPE
    result = run_agent("analyze", input_json, phase_scope=ANALYZE_SCOPE)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseScope:
    """CLI-agnostic tool restrictions for a single agent invocation."""

    allowed_tools: tuple[str, ...] | None = None
    disallowed_tools: tuple[str, ...] | None = None
    allowed_mcp_servers: tuple[str, ...] | None = None
    allowed_subagents: tuple[str, ...] | None = None
    max_turns: int | None = None


# Analyze: write TICKET.md only. No bash, no MCP, no subagents.
ANALYZE_SCOPE = PhaseScope(
    allowed_tools=("Read", "Write", "Edit"),
    disallowed_tools=("Task", "Bash", "WebFetch"),
    allowed_mcp_servers=(),
    allowed_subagents=(),
    max_turns=15,
)

# Plan: read/search the codebase, write PLAN.md. No execution.
PLAN_SCOPE = PhaseScope(
    allowed_tools=("Read", "Write", "Edit", "Glob", "Grep"),
    disallowed_tools=("Task", "Bash", "WebFetch"),
    allowed_mcp_servers=(),
    allowed_subagents=(),
    max_turns=25,
)

# Implement: full toolkit minus push / PR creation. Python handles those.
IMPLEMENT_SCOPE = PhaseScope(
    allowed_tools=("Read", "Write", "Edit", "Glob", "Grep", "Bash"),
    disallowed_tools=(
        "Task",
        "Bash(git push:*)",
        "Bash(gh pr create:*)",
        "Bash(gh pr:*)",
        "Bash(glab mr:*)",
        "Bash(git remote:*)",
    ),
    allowed_mcp_servers=(),
    allowed_subagents=(),
    max_turns=40,
)

# Rework: same envelope as implement — applies review feedback to code.
REWORK_SCOPE = PhaseScope(
    allowed_tools=IMPLEMENT_SCOPE.allowed_tools,
    disallowed_tools=IMPLEMENT_SCOPE.disallowed_tools,
    allowed_mcp_servers=(),
    allowed_subagents=(),
    max_turns=30,
)

# Feedback parser: needs git-provider MCP to read MR comments.
FEEDBACK_PARSER_SCOPE = PhaseScope(
    allowed_tools=("Read", "Write", "Edit"),
    disallowed_tools=("Task", "Bash"),
    allowed_mcp_servers=("git-provider",),
    allowed_subagents=(),
    max_turns=10,
)
