# Phase-Boundary Redesign: Pipeline-Driven Coordination + Per-Phase Tool Sandbox

**Date:** 2026-04-17
**Status:** Design (pending approval)
**Supersedes:** Current orchestrator dispatcher pattern in `agents/orchestrator.md`

## 1. Problem

The orchestrator agent, when invoked with `action=analyze`, performs the work of *all* phases (analyze + plan + implement + push + MR creation) in a single subprocess. Root causes:

1. **All phases visible in one agent file.** `agents/orchestrator.md` contains every action block, giving the LLM an obvious "complete the workflow" nudge.
2. **Sub-agents are reachable.** The `brainstorm` and `developer` subagents exist in the same `.claude/agents/` directory, so the model can invoke them from any phase.
3. **No physical tool restriction.** The agent has `Bash(git push)`, `Task` (subagent), and MCP write tools available in every phase.
4. **Internal prompt contradictions** (e.g. analyze step 7 "MANDATORY: transition ticket" vs rule 160 "DO NOT transition") erode trust in stated boundaries.

## 2. Goals

- **Hard guarantee** that phase N cannot perform the work of phase N+1, regardless of prompt wording or ticket-content injection.
- Keep the **adapter-based extensibility** the codebase already uses (Claude Code / Codex / Gemini adapters).
- Move deterministic coordination (push, MR creation) out of the LLM and into Python.
- No regression in MCP-mode issue-tracker behaviour.

## 3. Non-goals

- Eliminating the issue-tracker `mcp` vs `api` mode split — stays as-is.
- Changing the webhook / state-machine layer.
- Changing the dashboard.

## 4. Architecture

Two changes combined (Option B + Option C from the brainstorm):

- **B — Python drives coordination.** Pipeline invokes one concrete agent per phase. Push and MR creation happen in Python via the existing `GitProviderBase.create_api()` client. No agent dispatches to another agent.
- **C — Per-phase tool sandbox.** Each phase invocation of the CLI gets a restricted toolset via a new `PhaseScope` abstraction the CLI adapter translates into native flags. The agent *cannot* call `git push`, `gh pr create`, or sub-agents during analyze/plan — those tools don't exist in its env.

### 4.1 Component overview

```
┌────────────────────────────────────────────────────────────────┐
│  pipeline.py  (single coordinator)                             │
│                                                                │
│   analyze  →  plan  →  implement  →  (push + MR in Python)     │
│      │         │          │                                    │
│      ↓         ↓          ↓                                    │
│   run_agent(name, input, phase_scope=…)                        │
│      │                                                         │
│      ↓                                                         │
│   CliAdapterBase.build_args(…, phase_scope)                    │
│      │                                                         │
│      ├─ Claude Code: --allowed-tools / --disallowed-tools      │
│      │               / --mcp-config <temp>  / --max-turns       │
│      ├─ Codex:       --approval / config flags                 │
│      └─ Gemini:      native equivalents                        │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 Agent file restructure

Source of truth stays in `agents/` (installer symlinks it to the CLI's native dir — no adapter changes needed).

**New / renamed files:**

| File | Single responsibility |
|---|---|
| `agents/analyze.md` | Write `TICKET.md` to `repo_dir/`. Nothing else. |
| `agents/plan.md` | Write `PLAN.md` to `repo_dir/` (absorbs current `brainstorm.md`). |
| `agents/implement.md` | Edit code, run tests, `git commit` locally. No push. No MR. |
| `agents/rework.md` | Read `FEEDBACK.md`, apply changes, `git commit` locally. No push. |
| `agents/feedback-parser.md` | *(unchanged)* |

**Deleted:** `agents/orchestrator.md`, `agents/brainstorm.md`, `agents/developer.md`.

Each file contains ONLY its own phase's steps. No `action` dispatch field. No cross-agent invocation text. No mentions of other phases.

### 4.3 Pipeline coordination (Option B)

Expanded responsibilities in `src/executor/pipeline.py`:

```
Phase 1 — Analyze
  1. Python: create remote feature branch via git-provider API
  2. Python: prepare local repo (checkout feature branch)
  3. Python: run_agent("analyze", input, phase_scope=ANALYZE_SCOPE)
     → agent writes TICKET.md to repo_dir/
  4. Python: read TICKET.md, commit via git-provider API, push
  5. Python: post "analysis complete" comment (if api mode)

Phase 2 — Plan
  1. Python: run_agent("plan", input, phase_scope=PLAN_SCOPE)
     → agent writes PLAN.md to repo_dir/
  2. Python: commit PLAN.md via git-provider API, push
  3. Python: post plan comment (if api mode)

Phase 3 — Implement
  1. Python: checkout feature branch locally
  2. Python: run_agent("implement", input, phase_scope=IMPLEMENT_SCOPE)
     → agent edits code, runs tests, commits locally
  3. Python: git push origin <branch>
  4. Python: create MR via git-provider API
  5. Python: transition ticket to done, post MR link comment

Rework
  1. Python: run_agent("feedback-parser", input)
     → writes FEEDBACK.md
  2. Python: run_agent("rework", input, phase_scope=REWORK_SCOPE)
     → agent edits code, commits locally
  3. Python: git push
  4. Python: post rework-complete comment
```

Key invariants enforced by Python:
- No agent ever calls `git push` or creates an MR.
- Branch creation and PLAN.md/TICKET.md commits go through the git-provider API (already implemented in `GitLabAdapter.create_api()`).
- Implement/rework phases commit locally because multi-file code edits are naturally committed by the local git client.

### 4.4 PhaseScope abstraction (Option C)

**New module:** `src/executor/phase_scope.py`

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PhaseScope:
    """CLI-agnostic restrictions to apply to a single agent invocation.

    Adapter implementations translate these into native flags. Fields
    set to None mean 'no override' (adapter default applies).
    """
    allowed_tools: tuple[str, ...] | None = None
    disallowed_tools: tuple[str, ...] | None = None
    allowed_mcp_servers: tuple[str, ...] | None = None
    allowed_subagents: tuple[str, ...] | None = None  # () = none
    max_turns: int | None = None


ANALYZE_SCOPE = PhaseScope(
    allowed_tools=("Read", "Write", "Edit"),
    disallowed_tools=("Task", "Bash", "WebFetch"),
    allowed_mcp_servers=(),           # no MCP — agent only writes TICKET.md
    allowed_subagents=(),
    max_turns=15,
)

PLAN_SCOPE = PhaseScope(
    allowed_tools=("Read", "Write", "Edit", "Glob", "Grep"),
    disallowed_tools=("Task", "Bash", "WebFetch"),
    allowed_mcp_servers=(),
    allowed_subagents=(),
    max_turns=25,
)

IMPLEMENT_SCOPE = PhaseScope(
    allowed_tools=("Read", "Write", "Edit", "Glob", "Grep", "Bash"),
    # Bash is allowed (for tests, local git commit) but NOT push / MR creation.
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

REWORK_SCOPE = PhaseScope(
    allowed_tools=IMPLEMENT_SCOPE.allowed_tools,
    disallowed_tools=IMPLEMENT_SCOPE.disallowed_tools,
    allowed_mcp_servers=(),
    allowed_subagents=(),
    max_turns=30,
)

FEEDBACK_PARSER_SCOPE = PhaseScope(
    allowed_tools=("Read", "Write", "Edit"),
    disallowed_tools=("Task", "Bash"),
    allowed_mcp_servers=("git-provider",),  # needs to read MR comments
    max_turns=10,
)
```

### 4.5 CliAdapterBase extension

`src/providers/base.py`:

```python
class CliAdapterBase(ABC):
    ...
    @abstractmethod
    def build_args(
        self,
        agent_name: str,
        input_text: str,
        config: dict,
        phase_scope: "PhaseScope | None" = None,
    ) -> list[str]:
        ...
```

`phase_scope=None` preserves backward compatibility (existing behaviour). Each adapter decides how to translate non-None scopes.

**Claude Code translation** (`src/providers/cli/claude_code.py`):

- `allowed_tools` → `--allowed-tools "Read,Write,Edit"`
- `disallowed_tools` → `--disallowed-tools "Task,Bash(git push:*)"`
- `allowed_mcp_servers` → write a temp `mcp-config.json` containing only allowed servers (or `{}` for none) and pass `--mcp-config <path>`; temp file cleaned up after subprocess exits
- `max_turns` → override `DEFAULT_MAX_TURNS` when present
- `allowed_subagents` → when `()`, add `Task` to `disallowed_tools` (Claude Code's subagent-invocation tool is `Task`)

**Codex / Gemini:** initial implementation can honour `max_turns` and any natively supported allow/deny concepts. Unsupported fields are no-ops with a one-line `logger.debug(...)` note, so the system degrades gracefully on other CLIs while still enforcing boundaries via agent-file structure.

### 4.6 Runner changes

`src/executor/runner.py`:

```python
def run_agent(
    agent_name,
    input_text,
    cwd=None,
    timeout_ms=None,
    extra_env=None,
    issue_key=None,
    phase_scope: "PhaseScope | None" = None,   # NEW
) -> dict:
    ...
    args = adapter.build_args(agent_name, prompted_input, cli_config, phase_scope=phase_scope)
```

Temp `mcp-config.json` lifecycle: created in a `tempfile.TemporaryDirectory()` scoped to the `run_agent` call, guaranteeing cleanup even on exceptions.

### 4.7 Mode compatibility

- **Issue-tracker `api` mode:** Python does reads / comments / transitions (no change from today).
- **Issue-tracker `mcp` mode:** phase agents don't touch the tracker at all — Python does it. This is a behaviour change: the old orchestrator posted the "analysis" / "plan" detail comments from inside the agent. We replace that by having Python read TICKET.md / PLAN.md after the phase and post the comment via the configured tracker adapter. This eliminates a source of prompt contradictions.

If the project genuinely needs the agent to post the comment in mcp mode (e.g. because the tracker doesn't have a REST client implemented), we can keep an explicit `*-commenter` micro-agent with only the tracker-MCP server allowed. Out of scope for this design unless we hit it.

## 5. Files changed

**New:**
- `agents/analyze.md`
- `agents/plan.md`
- `agents/implement.md`
- `agents/rework.md`
- `src/executor/phase_scope.py`

**Modified:**
- `src/providers/base.py` — `CliAdapterBase.build_args` signature
- `src/providers/cli/claude_code.py` — `build_args` implements PhaseScope translation
- `src/providers/cli/codex.py` — honour what's natively supportable
- `src/providers/cli/gemini.py` — honour what's natively supportable
- `src/executor/runner.py` — forward `phase_scope`
- `src/executor/pipeline.py` — split phases; Python does push + MR creation; invoke per-phase agents
- `docs/codebase-guide.md` — reflect new agents + phase-scope

**Deleted:**
- `agents/orchestrator.md`
- `agents/brainstorm.md`
- `agents/developer.md`

**No changes needed to:** `installer/linker.py` (already symlinks every `.md` in `agents/`), webhook routes, state manager, providers (issue tracker / notification / output), dashboard.

## 6. Migration

Single-cycle replacement. After merge, operators run `./stop.sh && ./setup.sh` (or whatever they already use) to re-link agent files. Old `orchestrator.md` symlinks in target repos are removed by `stop.sh`'s existing cleanup.

## 7. Testing strategy

- **Unit:** `PhaseScope` dataclass round-trip; each adapter's `build_args(..., phase_scope=X)` produces expected arg list.
- **Integration (mocked CLI):** pipeline runs a fake adapter that records each subprocess's args and asserts phase scopes match expectations — proves boundary enforcement is wired end to end without spending model tokens.
- **End-to-end (live):** one real ticket through the full pipeline with Claude Code; verify 3 distinct subprocess invocations, each with its own `--allowed-tools` and `--mcp-config`, and that no `git push` happens from inside any subprocess.

## 8. Risk / open questions

1. **Does Claude Code respect `--disallowed-tools` with a `Bash(pattern:*)` glob?** If the flag only supports whole-tool names, we fall back to `--disallowed-tools Task` plus a `Bash` permission rule via settings.json. Verify before implementing.
2. **`--mcp-config` overriding vs merging:** confirm whether passing `--mcp-config` replaces or augments `.claude/settings.json`. If it augments, we pass an empty config file to suppress the default.
3. **MR-creation comments in MCP mode:** section 4.7 assumes Python can post the final MR comment. For `jira-mcp` tracker this requires the Jira adapter's `add_comment` path to work (currently gated on `is_api_mode()`). Either lift that gate when safe or keep a tiny `mr-comment.md` agent as an escape hatch.
4. **Codex / Gemini parity:** these adapters won't fully enforce tool sandbox on day one. Phase-boundary enforcement is strongest on Claude Code; on other CLIs the split-file restructure still prevents most drift.
