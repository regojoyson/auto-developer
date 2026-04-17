# Phase-Boundary Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate cross-phase scope drift in the agent pipeline by (a) making the Python pipeline the sole coordinator of push / MR creation and (b) enforcing a per-phase tool sandbox via a new `PhaseScope` abstraction plugged into the existing CLI adapter pattern.

**Architecture:** Replace the monolithic `orchestrator.md` agent with four single-purpose phase agents (`analyze`, `plan`, `implement`, `rework`). Each phase invocation of the CLI is restricted with a `PhaseScope` dataclass that the CLI adapter translates into native tool-allow/deny flags plus a temp MCP config. Python drives branch creation, commits, pushes, and MR creation via the existing `GitProviderBase.create_api()` client — the LLM never runs `git push` or creates an MR.

**Tech Stack:** Python 3.12, FastAPI, Pytest (bootstrapped here), Claude Code CLI (primary), Codex / Gemini CLIs (degraded support).

**Spec:** [2026-04-17-phase-boundary-redesign-design.md](../specs/2026-04-17-phase-boundary-redesign-design.md)

---

## File Plan

**New:**
- `tests/__init__.py`, `tests/conftest.py`
- `tests/executor/__init__.py`, `tests/executor/test_phase_scope.py`, `tests/executor/test_runner.py`, `tests/executor/test_pipeline_helpers.py`
- `tests/providers/__init__.py`, `tests/providers/cli/__init__.py`, `tests/providers/cli/test_claude_code.py`
- `src/executor/phase_scope.py`
- `src/executor/pipeline_git.py` (remote-git helpers used by pipeline)
- `agents/analyze.md`, `agents/plan.md`, `agents/implement.md`, `agents/rework.md`
- `pytest.ini`

**Modified:**
- `requirements.txt` (add `pytest`)
- `src/providers/base.py` (`CliAdapterBase.build_args` signature)
- `src/providers/cli/claude_code.py` (PhaseScope translation)
- `src/providers/cli/codex.py` (accept phase_scope, log + no-op)
- `src/providers/cli/gemini.py` (accept phase_scope, log + no-op)
- `src/executor/runner.py` (forward phase_scope, manage temp dir)
- `src/executor/pipeline.py` (per-phase agents + Python-driven push / MR)
- `docs/codebase-guide.md`

**Deleted:**
- `agents/orchestrator.md`, `agents/brainstorm.md`, `agents/developer.md`

---

## Task 1: Bootstrap test infrastructure

**Files:**
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add pytest to requirements**

Append to `requirements.txt`:

```
pytest>=8.0.0
```

- [ ] **Step 2: Install pytest**

Run: `./venv/bin/pip install -r requirements.txt`
Expected: `Successfully installed pytest-...`

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -q --tb=short
```

- [ ] **Step 4: Create `tests/__init__.py`**

```python
```

(Empty file — makes `tests` a package.)

- [ ] **Step 5: Create `tests/conftest.py`**

```python
"""Shared pytest configuration.

Adds the project root to sys.path so tests can import `src.*` modules
without installing the project as a package.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

- [ ] **Step 6: Verify pytest can discover and run**

Run: `./venv/bin/pytest --collect-only`
Expected: no tests yet, exits 5 ("no tests ran"). That's fine — infrastructure is in place.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini tests/__init__.py tests/conftest.py
git commit -m "chore: bootstrap pytest test infrastructure"
```

---

## Task 2: Create `PhaseScope` dataclass and per-phase constants

**Files:**
- Create: `src/executor/phase_scope.py`
- Create: `tests/executor/__init__.py`
- Create: `tests/executor/test_phase_scope.py`

- [ ] **Step 1: Create `tests/executor/__init__.py`**

```python
```

- [ ] **Step 2: Write the failing test**

Create `tests/executor/test_phase_scope.py`:

```python
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
```

- [ ] **Step 3: Run the test — expect ImportError**

Run: `./venv/bin/pytest tests/executor/test_phase_scope.py -v`
Expected: `ModuleNotFoundError: No module named 'src.executor.phase_scope'`

- [ ] **Step 4: Implement `PhaseScope`**

Create `src/executor/phase_scope.py`:

```python
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
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `./venv/bin/pytest tests/executor/test_phase_scope.py -v`
Expected: all 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/executor/phase_scope.py tests/executor/__init__.py tests/executor/test_phase_scope.py
git commit -m "feat(executor): add PhaseScope abstraction with per-phase constants"
```

---

## Task 3: Extend `CliAdapterBase.build_args` signature

**Files:**
- Modify: `src/providers/base.py`

- [ ] **Step 1: Update the abstract method signature**

In `src/providers/base.py`, find the `CliAdapterBase.build_args` method (around line 221) and replace with:

```python
    @abstractmethod
    def build_args(
        self,
        agent_name: str,
        input_text: str,
        config: dict,
        phase_scope: "PhaseScope | None" = None,
    ) -> list[str]:
        """Build CLI arguments for invoking an agent.

        Args:
            agent_name: Agent name (e.g. 'orchestrator', 'brainstorm').
            input_text: JSON string input to pass to the agent.
            config: cli_adapter section from config.yaml.
            phase_scope: Optional per-phase tool sandbox. Adapters translate
                this into native flags (e.g. ``--allowed-tools``). When None,
                no phase restrictions apply (adapter default behaviour).

        Returns:
            List of CLI argument strings.
        """
        ...
```

- [ ] **Step 2: Add the TYPE_CHECKING import**

At the top of `src/providers/base.py`, after the existing imports:

```python
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.executor.phase_scope import PhaseScope
```

- [ ] **Step 3: Verify existing adapters still import cleanly**

Run: `./venv/bin/python -c "from src.providers.cli.claude_code import adapter; print(adapter.name)"`
Expected: `claude-code`

Note: the signature change is backward-compatible (new param has a default). Existing `build_args` implementations still satisfy the contract because they ignore the new arg.

- [ ] **Step 4: Commit**

```bash
git add src/providers/base.py
git commit -m "feat(providers): add phase_scope parameter to CliAdapterBase.build_args"
```

---

## Task 4: Claude Code adapter — translate `PhaseScope` to native flags

**Files:**
- Modify: `src/providers/cli/claude_code.py`
- Create: `tests/providers/__init__.py`, `tests/providers/cli/__init__.py`
- Create: `tests/providers/cli/test_claude_code.py`

- [ ] **Step 1: Create test package init files**

Create empty files:
- `tests/providers/__init__.py`
- `tests/providers/cli/__init__.py`

- [ ] **Step 2: Write failing tests**

Create `tests/providers/cli/test_claude_code.py`:

```python
"""Tests for Claude Code adapter's PhaseScope translation."""

import json
from pathlib import Path

from src.executor.phase_scope import (
    ANALYZE_SCOPE,
    IMPLEMENT_SCOPE,
    PhaseScope,
)
from src.providers.cli.claude_code import adapter


def test_build_args_without_scope_matches_legacy_behavior():
    """Omitting phase_scope preserves the pre-existing flag set."""
    args = adapter.build_args("analyze", '{"a":1}', {})
    assert "--agent" in args
    assert "analyze" in args
    assert "--dangerously-skip-permissions" in args
    # Legacy path must NOT inject phase-scope flags
    assert "--allowed-tools" not in args
    assert "--disallowed-tools" not in args


def test_build_args_with_scope_drops_dangerous_skip():
    """A scoped invocation must not bypass permissions."""
    args = adapter.build_args("analyze", '{"a":1}', {}, phase_scope=ANALYZE_SCOPE)
    assert "--dangerously-skip-permissions" not in args


def test_build_args_with_scope_adds_allowed_tools():
    args = adapter.build_args("analyze", '{"a":1}', {}, phase_scope=ANALYZE_SCOPE)
    # --allowed-tools "Read,Write,Edit"
    idx = args.index("--allowed-tools")
    assert args[idx + 1] == "Read,Write,Edit"


def test_build_args_with_scope_adds_disallowed_tools():
    args = adapter.build_args("implement", '{"a":1}', {}, phase_scope=IMPLEMENT_SCOPE)
    idx = args.index("--disallowed-tools")
    denied = args[idx + 1]
    assert "Task" in denied
    assert "Bash(git push:*)" in denied


def test_build_args_max_turns_override(tmp_path):
    args = adapter.build_args("plan", '{"a":1}', {}, phase_scope=PhaseScope(max_turns=7))
    idx = args.index("--max-turns")
    assert args[idx + 1] == "7"


def test_build_args_empty_mcp_servers_writes_temp_config(tmp_path, monkeypatch):
    """When allowed_mcp_servers=(), adapter generates an empty mcp-config.json."""
    # Redirect adapter's temp-dir to a path we can inspect after the call.
    scope = PhaseScope(allowed_mcp_servers=())
    args = adapter.build_args("analyze", '{"a":1}', {}, phase_scope=scope)
    idx = args.index("--mcp-config")
    mcp_path = Path(args[idx + 1])
    assert mcp_path.exists()
    data = json.loads(mcp_path.read_text())
    assert data == {"mcpServers": {}}


def test_build_args_none_mcp_servers_omits_mcp_config():
    """When allowed_mcp_servers is None (no override), no --mcp-config arg."""
    scope = PhaseScope(allowed_tools=("Read",))
    args = adapter.build_args("analyze", '{"a":1}', {}, phase_scope=scope)
    assert "--mcp-config" not in args
```

- [ ] **Step 3: Run tests — expect failures**

Run: `./venv/bin/pytest tests/providers/cli/test_claude_code.py -v`
Expected: first test may pass, the rest fail.

- [ ] **Step 4: Implement PhaseScope translation in `claude_code.py`**

Replace the `build_args` method in `src/providers/cli/claude_code.py` with:

```python
    def build_args(self, agent_name, input_text, config, phase_scope=None):
        """Build command-line arguments for a Claude Code agent invocation.

        When ``phase_scope`` is provided, translates it into Claude Code's
        native flags (``--allowed-tools``, ``--disallowed-tools``,
        ``--mcp-config``, ``--max-turns``) and drops
        ``--dangerously-skip-permissions`` so the allow/deny lists are
        actually enforced.

        Args:
            agent_name: Name of the agent to invoke (e.g. ``"analyze"``).
            input_text: JSON-encoded input string to pass to the agent.
            config: The ``cli_adapter`` section from config.yaml. Supports
                optional keys ``model``, ``fallback_model``, ``max_turns``,
                and ``extra_args``.
            phase_scope: Optional :class:`PhaseScope` to restrict tools.

        Returns:
            list[str]: CLI argument strings suitable for subprocess execution.
        """
        args = [
            "--agent", agent_name,
            "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]

        if phase_scope is None:
            # Legacy path: bypass permissions as before.
            args.append("--dangerously-skip-permissions")
        else:
            # Scoped path: rely on allow/deny for permission control.
            args.extend(self._phase_scope_args(phase_scope))

        if config.get("model"):
            args.extend(["--model", config["model"]])
        if config.get("fallback_model"):
            args.extend(["--fallback-model", config["fallback_model"]])

        max_turns = (
            (phase_scope.max_turns if phase_scope and phase_scope.max_turns else None)
            or config.get("max_turns")
            or DEFAULT_MAX_TURNS
        )
        args.extend(["--max-turns", str(max_turns)])

        args.extend(config.get("extra_args") or [])
        args.append(input_text)
        return args

    def _phase_scope_args(self, scope):
        """Render a PhaseScope into Claude Code CLI flags.

        Writes a temp ``mcp-config.json`` when allowed_mcp_servers is an
        explicit tuple; the file is NOT cleaned up here (the runner's
        TemporaryDirectory scope owns its lifetime).
        """
        import json
        import tempfile
        from pathlib import Path

        args = []

        if scope.allowed_tools is not None:
            args.extend(["--allowed-tools", ",".join(scope.allowed_tools)])

        # Treat disallowed_subagents=() as "also disallow Task".
        disallowed = list(scope.disallowed_tools or ())
        if scope.allowed_subagents == () and "Task" not in disallowed:
            disallowed.append("Task")
        if disallowed:
            args.extend(["--disallowed-tools", ",".join(disallowed)])

        if scope.allowed_mcp_servers is not None:
            # Build a filtered mcp-config pointing only at the allowed servers.
            tmp_dir = Path(tempfile.mkdtemp(prefix="auto-pilot-mcp-"))
            mcp_path = tmp_dir / "mcp-config.json"
            mcp_path.write_text(
                json.dumps({"mcpServers": self._filter_mcp_servers(scope.allowed_mcp_servers)})
            )
            args.extend(["--mcp-config", str(mcp_path)])

        return args

    def _filter_mcp_servers(self, allowed):
        """Return a dict of {name: server-config} for each allowed server.

        Reads the current project's ``.claude/settings.json`` to discover
        declared MCP servers and keeps only those whose name appears in
        ``allowed``. Returns an empty dict if the settings file is missing
        or no servers match.
        """
        import json
        from pathlib import Path

        if not allowed:
            return {}

        settings_path = Path(".claude/settings.json")
        if not settings_path.exists():
            return {}
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

        declared = settings.get("mcpServers", {}) or {}
        return {name: cfg for name, cfg in declared.items() if name in allowed}
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `./venv/bin/pytest tests/providers/cli/test_claude_code.py -v`
Expected: all 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/providers/cli/claude_code.py tests/providers/__init__.py tests/providers/cli/__init__.py tests/providers/cli/test_claude_code.py
git commit -m "feat(cli/claude-code): translate PhaseScope into native CLI flags"
```

---

## Task 5: Codex and Gemini adapters — accept `phase_scope` (no-op)

**Files:**
- Modify: `src/providers/cli/codex.py`
- Modify: `src/providers/cli/gemini.py`

- [ ] **Step 1: Update Codex adapter**

In `src/providers/cli/codex.py`, replace the `build_args` signature and body:

```python
    def build_args(self, agent_name, input_text, config, phase_scope=None):
        """Build command-line arguments for a Codex agent invocation.

        ``phase_scope`` is accepted for interface parity but Codex does not
        yet expose a fine-grained tool-allowlist flag. The only field
        currently honoured is ``max_turns``; other fields are ignored with
        a debug log.

        See :class:`~src.executor.phase_scope.PhaseScope` for semantics.
        """
        import logging
        logger = logging.getLogger(__name__)

        prompt = f"[Agent: {agent_name}]\n{input_text}"
        args = ["--prompt", prompt, "--full-auto"]

        if config.get("model"):
            args.extend(["--model", config["model"]])
        args.extend(config.get("extra_args") or [])

        if phase_scope:
            ignored = [
                name for name, value in (
                    ("allowed_tools", phase_scope.allowed_tools),
                    ("disallowed_tools", phase_scope.disallowed_tools),
                    ("allowed_mcp_servers", phase_scope.allowed_mcp_servers),
                    ("allowed_subagents", phase_scope.allowed_subagents),
                ) if value is not None
            ]
            if ignored:
                logger.debug(f"Codex adapter ignoring unsupported phase_scope fields: {ignored}")

        return args
```

- [ ] **Step 2: Update Gemini adapter**

In `src/providers/cli/gemini.py`, replace the `build_args` method with:

```python
    def build_args(self, agent_name, input_text, config, phase_scope=None):
        """Build command-line arguments for a Gemini agent invocation.

        ``phase_scope`` is accepted for interface parity. Gemini does not
        expose a fine-grained tool allowlist flag; fields are logged at
        debug level and otherwise ignored.
        """
        import logging
        logger = logging.getLogger(__name__)

        prompt = f"[Agent: {agent_name}]\n{input_text}"
        args = ["--prompt", prompt, "--auto-approve"]

        if config.get("model"):
            args.extend(["--model", config["model"]])
        args.extend(config.get("extra_args") or [])

        if phase_scope:
            ignored = [
                name for name, value in (
                    ("allowed_tools", phase_scope.allowed_tools),
                    ("disallowed_tools", phase_scope.disallowed_tools),
                    ("allowed_mcp_servers", phase_scope.allowed_mcp_servers),
                    ("allowed_subagents", phase_scope.allowed_subagents),
                    ("max_turns", phase_scope.max_turns),
                ) if value is not None
            ]
            if ignored:
                logger.debug(f"Gemini adapter ignoring unsupported phase_scope fields: {ignored}")

        return args
```

- [ ] **Step 3: Verify imports still work**

Run: `./venv/bin/python -c "from src.providers.cli.codex import adapter as c; from src.providers.cli.gemini import adapter as g; print(c.name, g.name)"`
Expected: `codex gemini`

- [ ] **Step 4: Commit**

```bash
git add src/providers/cli/codex.py src/providers/cli/gemini.py
git commit -m "feat(cli): accept phase_scope param in Codex and Gemini adapters (no-op)"
```

---

## Task 6: Runner — forward `phase_scope`, manage temp-file lifetime

**Files:**
- Modify: `src/executor/runner.py`
- Create: `tests/executor/test_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/executor/test_runner.py`:

```python
"""Tests for the agent runner's phase_scope forwarding."""

from dataclasses import dataclass

from src.executor.phase_scope import ANALYZE_SCOPE


@dataclass
class FakeAdapter:
    label: str = "fake"
    default_command: str = "fake-cli"
    agent_dir: str = ".fake/agents"
    config_dir: str = ".fake"
    rules_file_name: str = "FAKE.md"
    last_phase_scope = None

    @property
    def name(self): return "fake"

    def build_args(self, agent_name, input_text, config, phase_scope=None):
        FakeAdapter.last_phase_scope = phase_scope
        return ["--echo", input_text]

    def build_env(self, base_env, config):
        return base_env

    def parse_output(self, stdout, stderr, exit_code):
        return {"success": exit_code == 0, "output": stdout, "error": stderr or None}

    def format_stream_line(self, line):
        return line


def test_run_agent_forwards_phase_scope(monkeypatch):
    from src.executor import runner

    fake = FakeAdapter()
    monkeypatch.setattr(runner, "get_cli_adapter", lambda: (fake, {}))

    # Short-circuit the subprocess so the test doesn't actually shell out.
    class _DummyProc:
        def __init__(self, *a, **kw):
            self.stdout = iter([])
            self.stderr = iter([])
            self.returncode = 0
        def wait(self, timeout=None): return 0
        def poll(self): return 0
        def kill(self): pass
        def terminate(self): pass

    monkeypatch.setattr(runner.subprocess, "Popen", _DummyProc)

    runner.run_agent("analyze", '{"issueKey":"X"}', phase_scope=ANALYZE_SCOPE)
    assert FakeAdapter.last_phase_scope is ANALYZE_SCOPE


def test_run_agent_default_phase_scope_is_none(monkeypatch):
    from src.executor import runner

    fake = FakeAdapter()
    FakeAdapter.last_phase_scope = "sentinel"
    monkeypatch.setattr(runner, "get_cli_adapter", lambda: (fake, {}))

    class _DummyProc:
        def __init__(self, *a, **kw):
            self.stdout = iter([]); self.stderr = iter([]); self.returncode = 0
        def wait(self, timeout=None): return 0
        def poll(self): return 0
        def kill(self): pass
        def terminate(self): pass

    monkeypatch.setattr(runner.subprocess, "Popen", _DummyProc)

    runner.run_agent("analyze", '{"issueKey":"X"}')
    assert FakeAdapter.last_phase_scope is None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `./venv/bin/pytest tests/executor/test_runner.py -v`
Expected: TypeError — `run_agent() got an unexpected keyword argument 'phase_scope'`.

- [ ] **Step 3: Update `run_agent` signature and pass-through**

In `src/executor/runner.py`, change the `run_agent` function signature and pass-through. Find the `def run_agent(...)` line (~115) and modify:

```python
def run_agent(
    agent_name: str,
    input_text: str,
    cwd: str | None = None,
    timeout_ms: int | None = None,
    extra_env: dict | None = None,
    issue_key: str | None = None,
    phase_scope: "PhaseScope | None" = None,
) -> dict:
```

And find the `args = adapter.build_args(...)` line (~151) and replace with:

```python
    args = adapter.build_args(agent_name, prompted_input, cli_config, phase_scope=phase_scope)
```

Add the TYPE_CHECKING import at the top of `src/executor/runner.py` if not present:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.executor.phase_scope import PhaseScope
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `./venv/bin/pytest tests/executor/test_runner.py -v`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/executor/runner.py tests/executor/test_runner.py
git commit -m "feat(runner): forward phase_scope parameter to CLI adapter"
```

---

## Task 7: Create `agents/analyze.md`

**Files:**
- Create: `agents/analyze.md`

- [ ] **Step 1: Write the agent file**

Create `agents/analyze.md`:

```markdown
# Analyze Agent

> **CRITICAL — READ THIS FIRST:**
> You are a FULLY AUTOMATED agent. There is NO human reading your output. Never ask questions. Never wait for input. Make every decision yourself.

You perform ONE task: read the ticket details from your input and write `TICKET.md` to the repository root.

You do NOT create branches. You do NOT commit. You do NOT push. You do NOT call any issue-tracker or git-provider API. Python handles all of that after you exit. Your tool envelope contains only `Read`, `Write`, and `Edit` — anything else will fail.

## Input

You receive a JSON input with:
- `issueKey` — ticket identifier
- `summary` — ticket summary (short)
- `ticketData` — full ticket object (description, acceptance criteria, attachments, linked issues, custom fields)

## Steps

1. Evaluate `ticketData` for sufficient detail to proceed. See `RULES.md` "Insufficient Ticket Details" section for the rubric.
2. If insufficient, output `__PIPELINE_RESULT__:{"blocked":true,"reason":"<what is missing>"}` and STOP.
3. Write `TICKET.md` at the repository root with these sections:
   - `# <issueKey>: <summary>`
   - `## Description` — full ticket description
   - `## Acceptance Criteria` — list from ticketData
   - `## Attachments` — filename + one-line description each
   - `## Linked Issues` — key + summary each
   - `## Design Notes` — any custom fields that look like design / scope notes
4. Output exactly one line: `__PIPELINE_RESULT__:{"blocked":false}`

## Hard rules
- Only `Write` `TICKET.md` at the repository root. Do not modify any other file.
- Do NOT output questions, confirmations, or "before I proceed" phrasing.
- Do NOT emit tool calls other than `Read`, `Write`, `Edit` — they will be rejected.
- The final line of your output MUST be a valid `__PIPELINE_RESULT__:...` marker.
```

- [ ] **Step 2: Commit**

```bash
git add agents/analyze.md
git commit -m "feat(agents): add single-purpose analyze agent"
```

---

## Task 8: Create `agents/plan.md`

**Files:**
- Create: `agents/plan.md`

- [ ] **Step 1: Write the agent file**

Create `agents/plan.md`:

```markdown
# Plan Agent

> **CRITICAL — READ THIS FIRST:**
> You are a FULLY AUTOMATED agent. There is NO human reading your output. Never ask questions. Never wait for input. Make every decision yourself.

You perform ONE task: read `TICKET.md` and explore the codebase, then write `PLAN.md` to the repository root.

You do NOT write code. You do NOT commit. You do NOT push. You do NOT invoke any other agent. Your tool envelope contains only `Read`, `Write`, `Edit`, `Glob`, `Grep` — `Bash`, `Task`, `WebFetch` will all be rejected.

## Input

You receive a JSON input with:
- `issueKey` — ticket identifier
- `branch` — feature branch name

## Steps

1. Read `TICKET.md` from the repository root.
2. Use `Glob`/`Grep` to explore the codebase and identify relevant files, patterns, conventions.
3. Generate 2–3 candidate approaches internally and auto-select the best one. Do NOT present options and wait — you are both proposer and approver.
4. Write `PLAN.md` at the repository root with these sections:

```markdown
# Implementation Plan for <issueKey>

## Summary
<one paragraph>

## Chosen Approach: <Name>
<why this over alternatives>

## File Changes
| File | Action | Description |
|------|--------|-------------|
| path | create/modify/delete | what changes and why |

## Implementation Notes
- ordered steps
- edge cases
- dependencies

## Acceptance Criteria Mapping
| AC | How it's satisfied |

## Assumptions
<assumptions made about ambiguous requirements>

## Alternatives Considered
### <Alt 1>
- Pros / Cons / Why not chosen
```

5. Output exactly one line: `__PIPELINE_RESULT__:{"blocked":false}`. If the plan surfaces fundamental blockers, output `__PIPELINE_RESULT__:{"blocked":true,"reason":"<details>"}` instead.

## Hard rules
- Only `Write` `PLAN.md` at the repository root. Do not modify any other file.
- Do NOT output questions, confirmations, or "before I proceed" phrasing.
- Do NOT emit tool calls other than `Read`, `Write`, `Edit`, `Glob`, `Grep` — they will be rejected.
- The final line of your output MUST be a valid `__PIPELINE_RESULT__:...` marker.
```

- [ ] **Step 2: Commit**

```bash
git add agents/plan.md
git commit -m "feat(agents): add single-purpose plan agent"
```

---

## Task 9: Create `agents/implement.md`

**Files:**
- Create: `agents/implement.md`

- [ ] **Step 1: Write the agent file**

Create `agents/implement.md`:

```markdown
# Implement Agent

> **CRITICAL — READ THIS FIRST:**
> You are a FULLY AUTOMATED agent. There is NO human reading your output. Never ask questions. Never wait for input. Make every decision yourself.

You perform ONE task: implement the changes listed in `PLAN.md`, run tests, and commit LOCALLY.

You do NOT push to remote. You do NOT create PRs/MRs. `git push`, `gh pr create`, `glab mr`, and `git remote` are blocked — Python handles the push and MR creation after you exit.

## Input

You receive a JSON input with:
- `issueKey` — ticket identifier
- `branch` — feature branch name (already checked out by Python)

## Steps

1. Read `PLAN.md` from the repository root — this is your source of truth.
2. Read `TICKET.md` for additional context (acceptance criteria).
3. Implement the changes in the order listed in PLAN.md "Implementation Notes".
4. Follow the `File Changes` table exactly — no files outside this list.
5. Run the existing test script if one is present in the repo:
   - `npm test` if `package.json` has a test script
   - `pytest` if `pytest.ini`/`pyproject.toml` configures it
   - `make test` if a Makefile has a `test` target
   - Skip if none of the above.
6. If tests fail, attempt to fix (max 2 tries). If still failing, commit anyway and note `test failure: <short reason>` in the commit body.
7. Stage and commit LOCALLY with message: `feat(<issueKey>): <short description>`.
8. Output exactly one line: `__PIPELINE_RESULT__:{"blocked":false}`.

## Hard rules
- Never modify `TICKET.md` or `PLAN.md`.
- Never modify files outside the PLAN.md "File Changes" table.
- Never run `git push`, `gh pr`, `glab mr`, or `git remote` — they will be blocked. Python handles the push.
- Never invoke sub-agents — `Task` is blocked.
- Do NOT output questions, confirmations, or "before I proceed" phrasing.
- The final line of your output MUST be a valid `__PIPELINE_RESULT__:...` marker.
```

- [ ] **Step 2: Commit**

```bash
git add agents/implement.md
git commit -m "feat(agents): add single-purpose implement agent"
```

---

## Task 10: Create `agents/rework.md`

**Files:**
- Create: `agents/rework.md`

- [ ] **Step 1: Write the agent file**

Create `agents/rework.md`:

```markdown
# Rework Agent

> **CRITICAL — READ THIS FIRST:**
> You are a FULLY AUTOMATED agent. There is NO human reading your output. Never ask questions. Never wait for input. Make every decision yourself.

You perform ONE task: apply the reviewer feedback listed in `FEEDBACK.md` and commit LOCALLY.

You do NOT push to remote. You do NOT re-plan. You do NOT refactor beyond the scope of FEEDBACK.md. `git push`, `gh pr create`, `glab mr`, `git remote` are blocked.

## Input

You receive a JSON input with:
- `issueKey` — ticket identifier
- `branch` — feature branch name (already checked out by Python)

## Steps

1. Read `FEEDBACK.md` from the repository root — this is the only set of changes you are allowed to make.
2. Read `PLAN.md` for background context only.
3. Apply each item in FEEDBACK.md:
   - Follow file/line references when provided.
   - For ambiguous items, use best judgement and note your interpretation in the commit body.
4. Run existing tests (same detection as implement agent). Fix any regressions (max 2 tries).
5. Stage and commit LOCALLY with message: `fix(<issueKey>): address review feedback`.
6. Output exactly one line: `__PIPELINE_RESULT__:{"blocked":false}`.

## Hard rules
- Only touch files that FEEDBACK.md calls out. Do not use rework as an excuse to refactor.
- Never modify `TICKET.md`, `PLAN.md`, or `FEEDBACK.md`.
- Never run `git push`, `gh pr`, `glab mr`, or `git remote` — they will be blocked.
- Never invoke sub-agents — `Task` is blocked.
- Do NOT output questions, confirmations, or "before I proceed" phrasing.
- The final line of your output MUST be a valid `__PIPELINE_RESULT__:...` marker.
```

- [ ] **Step 2: Commit**

```bash
git add agents/rework.md
git commit -m "feat(agents): add single-purpose rework agent"
```

---

## Task 11: Add `pipeline_git.py` helpers for remote git operations

**Files:**
- Create: `src/executor/pipeline_git.py`
- Create: `tests/executor/test_pipeline_helpers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/executor/test_pipeline_helpers.py`:

```python
"""Tests for the pipeline's Python-driven remote-git helpers."""

from unittest.mock import MagicMock
from pathlib import Path

from src.executor.pipeline_git import (
    commit_local_file_via_api,
    push_local_branch,
)


def test_commit_local_file_via_api_reads_file_and_calls_api(tmp_path):
    (tmp_path / "TICKET.md").write_text("# EV-1\n\nHello.")
    api = MagicMock()

    commit_local_file_via_api(
        api,
        repo_dir=str(tmp_path),
        branch="feat/ev-1",
        file_path="TICKET.md",
        message="chore: add TICKET.md",
    )

    api.commit_files.assert_called_once()
    kwargs = api.commit_files.call_args.kwargs or {}
    args = api.commit_files.call_args.args
    # Accept both positional and kwargs styles — the fake API is freeform.
    payload = {**dict(zip(["branch", "message", "actions"], args)), **kwargs}
    assert payload["branch"] == "feat/ev-1"
    assert payload["message"] == "chore: add TICKET.md"
    assert payload["actions"][0]["file_path"] == "TICKET.md"
    assert "Hello." in payload["actions"][0]["content"]


def test_commit_local_file_raises_when_file_missing(tmp_path):
    api = MagicMock()
    import pytest
    with pytest.raises(FileNotFoundError):
        commit_local_file_via_api(
            api, repo_dir=str(tmp_path), branch="b", file_path="nope.md", message="m"
        )


def test_push_local_branch_runs_git_push(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, **kw):
        calls.append((cmd, cwd))
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    monkeypatch.setattr("src.executor.pipeline_git.subprocess.run", fake_run)
    push_local_branch(str(tmp_path), "feat/ev-1")
    assert calls == [(["git", "push", "origin", "feat/ev-1"], str(tmp_path))]
```

- [ ] **Step 2: Run tests — expect failure**

Run: `./venv/bin/pytest tests/executor/test_pipeline_helpers.py -v`
Expected: `ModuleNotFoundError: src.executor.pipeline_git`.

- [ ] **Step 3: Implement the helpers**

Create `src/executor/pipeline_git.py`:

```python
"""Python-driven remote git operations used by the pipeline.

All functions that previously lived inside the orchestrator agent's
prompt (create remote branch, commit a file via the git-provider API,
git push, create a PR/MR) are collected here. Pipeline phases are thin
Python coordinators around these helpers — the LLM never executes them.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def create_remote_branch(api, *, branch: str, base: str) -> None:
    """Create a feature branch on the remote from ``base``.

    No-op if the branch already exists (idempotent — useful for retries).
    """
    try:
        api.create_branch(branch, ref=base)
        logger.info(f"Created remote branch {branch} from {base}")
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "branch already exists" in msg:
            logger.info(f"Remote branch {branch} already exists — reusing")
            return
        raise


def commit_local_file_via_api(api, *, repo_dir: str, branch: str, file_path: str, message: str) -> None:
    """Read a file from ``repo_dir`` and commit it to the remote branch via API.

    Used for TICKET.md and PLAN.md, where the agent wrote the file locally
    but Python owns the commit/push so the agent doesn't need git tools.
    """
    full_path = Path(repo_dir) / file_path
    if not full_path.exists():
        raise FileNotFoundError(f"Expected {file_path} at {full_path} — agent did not write it")
    content = full_path.read_text()
    api.commit_files(
        branch,
        message,
        [{"file_path": file_path, "action": "create", "content": content}],
    )
    logger.info(f"Committed {file_path} to {branch} via API")


def push_local_branch(repo_dir: str, branch: str) -> None:
    """Run ``git push origin <branch>`` in ``repo_dir``.

    Raises ``RuntimeError`` with stderr on non-zero exit.
    """
    result = subprocess.run(
        ["git", "push", "origin", branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git push failed: {result.stderr.strip()}")
    logger.info(f"Pushed {branch} to origin")


def create_merge_request(
    api, *, source: str, target: str, title: str, description: str
) -> dict:
    """Create a PR / MR via the git-provider API. Returns the provider's response dict."""
    mr = api.create_pr(source, target, title, description)
    logger.info(f"Created MR/PR: {mr}")
    return mr
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `./venv/bin/pytest tests/executor/test_pipeline_helpers.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/executor/pipeline_git.py tests/executor/test_pipeline_helpers.py
git commit -m "feat(executor): add pipeline_git helpers for Python-driven remote ops"
```

---

## Task 12: Pipeline — rewrite Phase 1 (Analyze)

**Files:**
- Modify: `src/executor/pipeline.py`

- [ ] **Step 1: Add imports**

At the top of `src/executor/pipeline.py`, add:

```python
from src.executor.phase_scope import (
    ANALYZE_SCOPE,
    PLAN_SCOPE,
    IMPLEMENT_SCOPE,
    REWORK_SCOPE,
    FEEDBACK_PARSER_SCOPE,
)
from src.executor.pipeline_git import (
    create_remote_branch,
    commit_local_file_via_api,
    push_local_branch,
    create_merge_request,
)
from src.providers.git_provider import get_git_provider
```

Verify `src/providers/git_provider.py` exists and exposes `get_git_provider()`. If the exact import path differs, adjust to match the existing codebase (check `src/providers/` for the factory).

- [ ] **Step 2: Rewrite the analyze phase block**

In `run_pipeline_phases`, find the "Step 4: Phase 1 — Analyze" block (around line 348) and replace the whole block with:

```python
    # ── Step 4: Phase 1 — Analyze ────────────────────────
    # Agent writes TICKET.md to repo_dir locally. Python then creates the
    # remote branch and commits TICKET.md via the git-provider API.
    _log_step(issue_key, "Preparing git-provider API client...")
    git_adapter, git_config = get_git_provider()
    import os as _os
    git_api = git_adapter.create_api(dict(_os.environ), repo_dir=repo_dir)

    _log_step(issue_key, f"Creating remote branch {branch} from {base_branch}...")
    try:
        create_remote_branch(git_api, branch=branch, base=base_branch)
    except Exception as e:
        transition_state(branch, "failed", error={
            "phase": "analyzing", "agent": "pipeline",
            "message": f"Failed to create remote branch: {e}",
        })
        _try_notify_slack(f"{issue_key} pipeline failed — branch creation error")
        return

    analyze_payload = {
        "issueKey": issue_key,
        "branch": branch,
        "summary": summary,
        "projectKey": project_key,
        "baseBranch": base_branch,
        "statuses": statuses,
        "apiMode": app_config["issue_tracker"]["api_mode"],
    }
    if ticket_data:
        analyze_payload["ticketData"] = ticket_data
    analyze_input = json.dumps(analyze_payload)

    result = _run_phase(
        issue_key, branch, "analyze", "orchestrator:analyze",
        analyze_input, statuses, repo_dir,
        phase_scope=ANALYZE_SCOPE,
    )
    if result is None:
        return

    # Python commits the agent-produced TICKET.md via the git-provider API.
    try:
        commit_local_file_via_api(
            git_api,
            repo_dir=repo_dir,
            branch=branch,
            file_path="TICKET.md",
            message=f"docs({issue_key}): add ticket context",
        )
    except Exception as e:
        _log_step(issue_key, f"CRITICAL: failed to commit TICKET.md — {e}")
        transition_state(branch, "failed", error={
            "phase": "analyzing", "agent": "pipeline",
            "message": f"Failed to commit TICKET.md: {e}",
        })
        return

    _try_add_comment(issue_key, f"Analysis complete for {issue_key}. See TICKET.md on branch `{branch}`.")
```

- [ ] **Step 3: Update `_run_phase` to accept `phase_scope`**

Replace the entire `_run_phase` function (around line 237) with:

```python
def _run_phase(
    issue_key, branch, agent_name, phase_label,
    input_data, statuses, repo_dir, *, phase_scope=None,
):
    """Run a single pipeline phase with full tracking and error handling.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name.
        agent_name: Agent to invoke (e.g. "analyze").
        phase_label: Label for tracking (e.g. "orchestrator:analyze").
        input_data: JSON string input for the agent.
        statuses: Dict of issue status names.
        repo_dir: Working directory for the agent.
        phase_scope: Optional :class:`PhaseScope` restricting agent tools.

    Returns:
        Agent result dict on success, or None if the phase failed/blocked.
    """
    current = get_state(branch)
    record_phase_start(branch, current["state"], phase_label)
    _log_phase(issue_key, phase_label, "Starting...")

    try:
        result = run_agent(
            agent_name, input_data,
            cwd=repo_dir, issue_key=issue_key,
            phase_scope=phase_scope,
        )
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(
            issue_key, branch, phase_label,
            {"success": False, "error": str(e)}, statuses,
        )
        return None

    if not result.get("success"):
        record_phase_end(branch, result.get("exit_code", -1), "failed")
        _handle_agent_failure(issue_key, branch, phase_label, result, statuses)
        return None

    if _is_blocked(result):
        record_phase_end(branch, 0, "blocked")
        _handle_blocked(issue_key, branch, statuses, result)
        return None

    record_phase_end(branch, 0, "success")
    _log_phase(issue_key, phase_label, "Completed successfully")
    return result
```

- [ ] **Step 4: Smoke-check syntax**

Run: `./venv/bin/python -c "from src.executor import pipeline; print('ok')"`
Expected: `ok` (no import error).

- [ ] **Step 5: Commit**

```bash
git add src/executor/pipeline.py
git commit -m "refactor(pipeline): analyze phase uses analyze agent + Python-driven commit"
```

---

## Task 13: Pipeline — rewrite Phase 2 (Plan)

**Files:**
- Modify: `src/executor/pipeline.py`

- [ ] **Step 1: Replace the plan block**

Find "Step 4: Phase 2 — Plan" (around line 369) and replace the block with:

```python
    # ── Step 5: Phase 2 — Plan ───────────────────────────
    _log_step(issue_key, "Transitioning state: analyzing → planning")
    transition_state(branch, "planning")

    plan_input = json.dumps({
        "issueKey": issue_key,
        "branch": branch,
    })
    result = _run_phase(
        issue_key, branch, "plan", "orchestrator:plan",
        plan_input, statuses, repo_dir,
        phase_scope=PLAN_SCOPE,
    )
    if result is None:
        return

    # Python commits the agent-produced PLAN.md via the git-provider API.
    try:
        commit_local_file_via_api(
            git_api,
            repo_dir=repo_dir,
            branch=branch,
            file_path="PLAN.md",
            message=f"docs({issue_key}): add implementation plan",
        )
    except Exception as e:
        _log_step(issue_key, f"CRITICAL: failed to commit PLAN.md — {e}")
        transition_state(branch, "failed", error={
            "phase": "planning", "agent": "pipeline",
            "message": f"Failed to commit PLAN.md: {e}",
        })
        return

    _try_add_comment(issue_key, f"Plan written for {issue_key}. See PLAN.md on branch `{branch}`.")
```

- [ ] **Step 2: Smoke-check syntax**

Run: `./venv/bin/python -c "from src.executor import pipeline; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/executor/pipeline.py
git commit -m "refactor(pipeline): plan phase uses plan agent + Python-driven commit"
```

---

## Task 14: Pipeline — rewrite Phase 3 (Implement)

**Files:**
- Modify: `src/executor/pipeline.py`

- [ ] **Step 1: Replace the implement block**

Find "Step 6: Phase 3 — Implement" (around line 392) and replace the block with:

```python
    # ── Step 6: Phase 3 — Implement ─────────────────────
    _log_step(issue_key, "Transitioning state: planning → developing")
    transition_state(branch, "developing")
    _log_step(issue_key, f"Checking out feature branch {branch} for implementation...")
    _prepare_repo_for_branch(repo_dir, base_branch, feature_branch=branch)

    implement_input = json.dumps({
        "issueKey": issue_key,
        "branch": branch,
    })
    result = _run_phase(
        issue_key, branch, "implement", "orchestrator:implement",
        implement_input, statuses, repo_dir,
        phase_scope=IMPLEMENT_SCOPE,
    )
    if result is None:
        return

    # Python pushes the branch (agent committed locally but cannot push).
    _log_step(issue_key, f"Pushing {branch} to origin...")
    try:
        push_local_branch(repo_dir, branch)
    except Exception as e:
        _log_step(issue_key, f"CRITICAL: git push failed — {e}")
        transition_state(branch, "failed", error={
            "phase": "developing", "agent": "pipeline",
            "message": f"git push failed: {e}",
        })
        return

    # Python creates the MR via git-provider API.
    _log_step(issue_key, "Creating merge/pull request...")
    try:
        mr = create_merge_request(
            git_api,
            source=branch,
            target=base_branch,
            title=f"feat({issue_key}): {summary}",
            description=f"Ticket: {issue_key}\n\nSee PLAN.md for the file-level change list.",
        )
        mr_url = mr.get("web_url") or mr.get("html_url") or mr.get("url") or "(no URL returned)"
    except Exception as e:
        _log_step(issue_key, f"CRITICAL: MR creation failed — {e}")
        transition_state(branch, "failed", error={
            "phase": "developing", "agent": "pipeline",
            "message": f"MR creation failed: {e}",
        })
        return

    # ── Step 7: Complete — awaiting review ───────────────
    _log_step(issue_key, "Transitioning state: developing → awaiting-review")
    transition_state(branch, "awaiting-review")
    _log_step(issue_key, f"Transitioning ticket to '{statuses['done']}'...")
    _try_transition_issue(issue_key, statuses["done"])
    _try_add_comment(issue_key, f"Implementation complete for {issue_key}. MR: {mr_url}")
    _try_notify_slack(f"MR created for {issue_key}: {mr_url}")

    logger.info(f"\n{'='*60}")
    logger.info(f"  PIPELINE COMPLETED: {issue_key}")
    logger.info(f"  State: awaiting-review")
    logger.info(f"  Branch: {branch}")
    logger.info(f"  MR: {mr_url}")
    logger.info(f"{'='*60}\n")
```

- [ ] **Step 2: Smoke-check syntax**

Run: `./venv/bin/python -c "from src.executor import pipeline; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/executor/pipeline.py
git commit -m "refactor(pipeline): implement phase uses implement agent + Python push/MR"
```

---

## Task 15: Pipeline — rewrite rework flow

**Files:**
- Modify: `src/executor/pipeline.py`

- [ ] **Step 1: Rewrite `run_rework_phases`**

Replace the entire `run_rework_phases` body (around line 425) with the rework-specific coordination. Find the whole function and replace:

```python
def run_rework_phases(issue_key, branch, pr_id, statuses, repo_dir):
    """Drive the rework loop: parse feedback -> apply fixes -> push -> awaiting-review.

    Same feature branch as the original implementation. Python now handles
    the push; the rework agent commits locally only.
    """
    state = get_state(branch)
    rework_num = (state.get("reworkCount", 0) if state else 0) + 1

    logger.info(f"\n{'='*60}")
    logger.info(f"  REWORK STARTED: {issue_key} (iteration {rework_num})")
    logger.info(f"  Branch: {branch}")
    logger.info(f"  PR/MR: {pr_id}")
    logger.info(f"{'='*60}\n")

    base_branch = get_base_branch()
    _log_step(issue_key, f"Checking out feature branch {branch}...")
    _prepare_repo_for_branch(repo_dir, base_branch, feature_branch=branch)

    if is_api_mode():
        _log_step(issue_key, f"Transitioning ticket to '{statuses['development']}'...")
        try:
            adapter, _ = get_issue_tracker()
            adapter.transition_issue(issue_key, statuses["development"])
        except Exception as e:
            transition_state(branch, "failed", error={
                "phase": "reworking", "agent": "pipeline",
                "message": f"Failed to transition ticket: {e}",
            })
            return

    transition_state(branch, "reworking")

    # ── Step 1: Parse feedback ───────────────────────────
    feedback_input = json.dumps({"issueKey": issue_key, "branch": branch, "prId": pr_id})
    result = _run_phase(
        issue_key, branch, "feedback-parser", "feedback-parser",
        feedback_input, statuses, repo_dir,
        phase_scope=FEEDBACK_PARSER_SCOPE,
    )
    if result is None:
        return

    # ── Step 2: Apply rework ─────────────────────────────
    rework_input = json.dumps({"issueKey": issue_key, "branch": branch})
    result = _run_phase(
        issue_key, branch, "rework", "orchestrator:rework",
        rework_input, statuses, repo_dir,
        phase_scope=REWORK_SCOPE,
    )
    if result is None:
        return

    # ── Step 3: Python pushes ────────────────────────────
    _log_step(issue_key, f"Pushing rework commits on {branch}...")
    try:
        push_local_branch(repo_dir, branch)
    except Exception as e:
        transition_state(branch, "failed", error={
            "phase": "reworking", "agent": "pipeline",
            "message": f"git push failed: {e}",
        })
        return

    # ── Step 4: Complete — back to awaiting review ───────
    transition_state(branch, "awaiting-review")
    _try_transition_issue(issue_key, statuses["done"])
    _try_add_comment(issue_key, f"Rework iteration {rework_num} complete for {issue_key}.")
    _try_notify_slack(f"Rework complete for {issue_key} (iteration {rework_num})")

    logger.info(f"  REWORK COMPLETED: {issue_key} (iteration {rework_num})")
```

- [ ] **Step 2: Smoke-check syntax**

Run: `./venv/bin/python -c "from src.executor import pipeline; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/executor/pipeline.py
git commit -m "refactor(pipeline): rework uses rework agent + Python-driven push"
```

---

## Task 16: Delete orphaned agent files

**Files:**
- Delete: `agents/orchestrator.md`
- Delete: `agents/brainstorm.md`
- Delete: `agents/developer.md`

- [ ] **Step 1: Verify no code still references them**

Run:
```bash
grep -rn "orchestrator" --include="*.py" src/ | grep -v "orchestrator:analyze\|orchestrator:plan\|orchestrator:implement\|orchestrator:rework"
grep -rn "brainstorm\|developer.md" --include="*.py" src/
```
Expected: no hits for agent-file references. (Phase labels `orchestrator:analyze` etc. remain as state labels — that's fine.)

- [ ] **Step 2: Delete the files**

```bash
git rm agents/orchestrator.md agents/brainstorm.md agents/developer.md
```

- [ ] **Step 3: Clean symlinks in target repos**

Run: `./stop.sh` (existing script already cleans up stale agent symlinks).

- [ ] **Step 4: Re-link new agent files into target repos**

Run: `./venv/bin/python -m installer.linker` (or whatever the setup step runs). Confirm new symlinks exist:
```bash
ls -la "$(awk '/path:/ {print $2; exit}' config.yaml)"/.claude/agents/
```
Expected to see symlinks for `analyze.md`, `plan.md`, `implement.md`, `rework.md`, `feedback-parser.md`.

- [ ] **Step 5: Commit the deletions**

```bash
git add -A agents/
git commit -m "chore(agents): remove orchestrator/brainstorm/developer (replaced by phase agents)"
```

---

## Task 17: Update `docs/codebase-guide.md`

**Files:**
- Modify: `docs/codebase-guide.md`

- [ ] **Step 1: Find the pipeline/agents sections**

Run: `grep -n "orchestrator\|brainstorm\|developer" docs/codebase-guide.md` to locate affected sections.

- [ ] **Step 2: Replace references**

For each hit, update the narrative to reflect:
- Four phase agents: `analyze.md`, `plan.md`, `implement.md`, `rework.md` (plus `feedback-parser.md`).
- Pipeline (not an agent) coordinates push + MR creation via `src/executor/pipeline_git.py`.
- `PhaseScope` (src/executor/phase_scope.py) restricts tools per phase; adapters translate.

Keep the diff tight — edit prose in place rather than rewriting sections.

- [ ] **Step 3: Commit**

```bash
git add docs/codebase-guide.md
git commit -m "docs: update codebase guide for phase-agent architecture"
```

---

## Task 18: End-to-end verification (mocked CLI)

**Files:**
- Create: `tests/executor/test_pipeline_e2e.py`

- [ ] **Step 1: Write an end-to-end test that asserts phase boundaries**

Create `tests/executor/test_pipeline_e2e.py`:

```python
"""End-to-end test: drive run_pipeline_phases with a recording CLI adapter.

Asserts that each phase subprocess receives the right phase_scope (so the
boundary-enforcement wiring can't silently regress), without spending
model tokens.
"""

from unittest.mock import MagicMock
import json


def test_pipeline_invokes_each_phase_with_its_own_scope(tmp_path, monkeypatch):
    from src.executor import pipeline, runner
    from src.executor.phase_scope import ANALYZE_SCOPE, PLAN_SCOPE, IMPLEMENT_SCOPE

    recorded = []

    def fake_run_agent(agent_name, input_text, cwd=None, issue_key=None, phase_scope=None, **_):
        recorded.append((agent_name, phase_scope))
        # Agent "writes" required artifacts so pipeline can continue.
        repo = cwd or str(tmp_path)
        if agent_name == "analyze":
            (tmp_path / "TICKET.md").write_text("# TICKET")
        elif agent_name == "plan":
            (tmp_path / "PLAN.md").write_text("# PLAN")
        return {"success": True, "output": '__PIPELINE_RESULT__:{"blocked":false}', "exit_code": 0}

    monkeypatch.setattr(pipeline, "run_agent", fake_run_agent)

    # Stub state + external calls
    monkeypatch.setattr(pipeline, "transition_state", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "get_state", lambda b: {"state": "analyzing"})
    monkeypatch.setattr(pipeline, "record_phase_start", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "record_phase_end", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "is_api_mode", lambda: False)
    monkeypatch.setattr(pipeline, "_try_transition_issue", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_try_add_comment", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_try_notify_slack", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_prepare_repo_for_branch", lambda *a, **k: None)

    # Stub git-provider API
    fake_api = MagicMock()
    fake_api.create_pr.return_value = {"web_url": "https://example/mr/1"}
    fake_adapter = MagicMock()
    fake_adapter.create_api.return_value = fake_api
    monkeypatch.setattr(pipeline, "get_git_provider", lambda: (fake_adapter, {}))

    # Stub push_local_branch to avoid subprocess
    monkeypatch.setattr(pipeline, "push_local_branch", lambda *a, **k: None)

    pipeline.run_pipeline_phases(
        issue_key="EV-1",
        branch="feat/ev-1",
        summary="demo",
        project_key="EV",
        base_branch="main",
        statuses={"trigger": "ready", "development": "dev", "done": "done", "blocked": "block"},
        repo_dir=str(tmp_path),
    )

    names = [n for n, _ in recorded]
    scopes = [s for _, s in recorded]
    assert names == ["analyze", "plan", "implement"]
    assert scopes == [ANALYZE_SCOPE, PLAN_SCOPE, IMPLEMENT_SCOPE]
```

- [ ] **Step 2: Run the test**

Run: `./venv/bin/pytest tests/executor/test_pipeline_e2e.py -v`
Expected: PASS. If it fails, inspect the failure — most likely missing monkeypatches for new helper functions. Extend the stub list and re-run.

- [ ] **Step 3: Run the full test suite**

Run: `./venv/bin/pytest -v`
Expected: all tests pass (phase_scope, adapter, runner, pipeline helpers, pipeline e2e).

- [ ] **Step 4: Commit**

```bash
git add tests/executor/test_pipeline_e2e.py
git commit -m "test(pipeline): end-to-end boundary verification with mocked CLI"
```

---

## Task 19: Manual live smoke test

**Files:** none (verification step only)

- [ ] **Step 1: Start the server**

Run: `./start.sh`
Expected: server running on configured port (check config.yaml `pipeline.port`).

- [ ] **Step 2: Trigger a pipeline on a test ticket**

Move a low-risk Jira ticket to `Ready for Development`. Watch `logs/` for the pipeline trace.

- [ ] **Step 3: Verify phase boundaries were enforced**

Inspect the logs directory for this issue. You should see:
- Exactly 3 subprocess invocations for normal flow: `analyze`, `plan`, `implement` (plus `feedback-parser` + `rework` if review comments come in).
- Each subprocess's command line should contain `--allowed-tools` and `--disallowed-tools`.
- No `git push`, `glab mr`, `gh pr` lines inside any phase's log — those should appear ONLY in the pipeline log (Python driver), not inside an agent's stdout.

Run:
```bash
grep -E "git push|glab mr|gh pr" logs/<issue-key>/*.log
```
Expected: hits only in the pipeline-level log, not in `analyze`, `plan`, `implement`, or `rework` agent logs.

- [ ] **Step 4: Verify artifacts exist on the MR**

Check the MR / PR in GitLab / GitHub:
- Commit history: `docs(<key>): add ticket context` → `docs(<key>): add implementation plan` → `feat(<key>): <summary>`.
- MR description references the ticket.

- [ ] **Step 5: Tear down**

Run: `./stop.sh`

No commit — this task is verification only.

---

## Post-plan checklist

- [ ] All tests pass: `./venv/bin/pytest -v`
- [ ] Python imports clean: `./venv/bin/python -c "from src.executor import pipeline; from src.providers.cli.claude_code import adapter; print('ok')"`
- [ ] Deleted agent files absent from target repos' `.claude/agents/`
- [ ] One live ticket verified end-to-end
- [ ] docs/codebase-guide.md reflects the new architecture
