"""Unit tests for PhaseScope dataclass and per-phase constants."""

from src.executor.phase_scope import (
    PhaseScope,
    ANALYZE_SCOPE,
    PLAN_SCOPE,
    IMPLEMENT_SCOPE,
    REWORK_SCOPE,
    FEEDBACK_PARSER_SCOPE,
)


def test_phase_scope_defaults_to_none():
    """An empty PhaseScope means 'no override' on every dimension."""
    scope = PhaseScope()
    assert scope.allowed_tools is None
    assert scope.disallowed_tools is None
    assert scope.allowed_mcp_servers is None
    assert scope.allowed_subagents is None
    assert scope.max_turns is None


def test_phase_scope_is_frozen():
    """PhaseScope is immutable so it can be safely reused as a module constant."""
    import dataclasses
    scope = PhaseScope(allowed_tools=("Read",))
    try:
        scope.allowed_tools = ("Write",)  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("PhaseScope should be frozen")


def test_analyze_scope_has_no_bash_or_task():
    """Analyze phase must not be able to run shell commands or invoke subagents."""
    assert "Bash" in ANALYZE_SCOPE.disallowed_tools
    assert "Task" in ANALYZE_SCOPE.disallowed_tools
    assert ANALYZE_SCOPE.allowed_mcp_servers == ()


def test_plan_scope_allows_code_exploration_only():
    """Plan can read/search code (Glob/Grep) but not execute anything."""
    assert "Glob" in PLAN_SCOPE.allowed_tools
    assert "Grep" in PLAN_SCOPE.allowed_tools
    assert "Bash" in PLAN_SCOPE.disallowed_tools


def test_implement_scope_allows_bash_but_blocks_push_and_mr():
    """Implement can run tests + local git but cannot push or create MRs."""
    assert "Bash" in IMPLEMENT_SCOPE.allowed_tools
    denied = IMPLEMENT_SCOPE.disallowed_tools
    assert any("git push" in d for d in denied)
    assert any("gh pr" in d for d in denied)
    assert any("glab mr" in d for d in denied)


def test_rework_scope_matches_implement():
    """Rework has the same tool envelope as implement."""
    assert REWORK_SCOPE.allowed_tools == IMPLEMENT_SCOPE.allowed_tools
    assert REWORK_SCOPE.disallowed_tools == IMPLEMENT_SCOPE.disallowed_tools


def test_feedback_parser_scope_allows_git_provider_mcp():
    """Feedback parser needs the git-provider MCP to read MR comments."""
    assert "git-provider" in FEEDBACK_PARSER_SCOPE.allowed_mcp_servers
