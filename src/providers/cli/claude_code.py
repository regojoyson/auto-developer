"""Claude Code CLI adapter.

Implements the :class:`~src.providers.base.CliAdapterBase` interface for
the Claude Code CLI (``claude``). Builds command-line arguments to invoke
agents in non-interactive print mode with auto-approved tool calls, and
parses the resulting stream-json events into a normalized result dict.

The module exposes a singleton ``adapter`` instance at module level for
use by the CLI adapter factory.
"""

import json

from src.providers.base import CliAdapterBase

DEFAULT_MAX_TURNS = 40


class ClaudeCodeAdapter(CliAdapterBase):
    """Adapter for invoking AI coding agents via the Claude Code CLI.

    Uses ``--print`` with ``--output-format stream-json`` so every tool
    call, assistant message, and tool result is emitted as a JSON line in
    real time — giving the pipeline live visibility into what the agent
    is doing instead of a silent wait until completion.
    """

    name = "claude-code"
    label = "Claude Code CLI"
    default_command = "claude"
    agent_dir = ".claude/agents"
    config_dir = ".claude"
    rules_file_name = "CLAUDE.md"

    def build_args(self, agent_name, input_text, config):
        """Build command-line arguments for a Claude Code agent invocation.

        Args:
            agent_name: Name of the agent to invoke (e.g. ``"orchestrator"``).
            input_text: JSON-encoded input string to pass to the agent.
            config: The ``cli_adapter`` section from config.yaml. Supports
                optional keys ``model``, ``fallback_model``, ``max_turns``,
                and ``extra_args``.

        Returns:
            list[str]: CLI argument strings suitable for subprocess execution.
        """
        args = [
            "--agent", agent_name,
            "--print",                              # non-interactive
            "--output-format", "stream-json",       # one JSON event per line
            "--verbose",                            # required with stream-json
            "--dangerously-skip-permissions",       # auto-approve all tool calls
            "--disable-slash-commands",             # agent must not invoke skills
            "--no-session-persistence",             # ephemeral CI runs
        ]
        if config.get("model"):
            args.extend(["--model", config["model"]])
        if config.get("fallback_model"):
            args.extend(["--fallback-model", config["fallback_model"]])
        max_turns = config.get("max_turns") or DEFAULT_MAX_TURNS
        args.extend(["--max-turns", str(max_turns)])
        args.extend(config.get("extra_args") or [])
        args.append(input_text)                     # prompt positional, must be last
        return args

    def format_stream_line(self, line):
        """Render a stream-json event as a concise human-readable line.

        Returns an empty string for noise events (hooks, rate limits) so
        they are suppressed from the log. Falls back to the raw line if
        the input isn't a parseable JSON event.
        """
        stripped = line.strip()
        if not stripped:
            return ""
        if not stripped.startswith("{"):
            return line
        try:
            evt = json.loads(stripped)
        except json.JSONDecodeError:
            return line
        return _format_event(evt)

    def parse_output(self, stdout, stderr, exit_code):
        """Parse stream-json events and return the agent's final text.

        stdout is a stream of JSON events (one per line). The agent's final
        response lives in the ``result`` field of the terminal ``result``
        event. Returns that text so downstream parsing can find the
        ``__PIPELINE_RESULT__:`` marker on its own line.

        Falls back to raw stdout if no ``result`` event is present (agent
        killed mid-run) so debug output is not lost.
        """
        final_text = ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "result" and "result" in evt:
                final_text = evt["result"] or ""
                break

        return {
            "success": exit_code == 0,
            "output": final_text or stdout,
            "error": stderr or f"Exited with code {exit_code}" if exit_code != 0 else None,
        }


def _truncate(s, n=160):
    s = str(s).replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _format_tool_args(name, input_dict):
    """Pick the most informative argument for common tool calls."""
    if not isinstance(input_dict, dict):
        return ""
    for key in ("file_path", "path", "command", "pattern", "url", "query", "issueKey"):
        if key in input_dict:
            return f"{key}={_truncate(input_dict[key], 120)}"
    # Fallback — first key/value or a compact JSON dump
    if input_dict:
        k = next(iter(input_dict))
        return f"{k}={_truncate(input_dict[k], 120)}"
    return ""


def _format_event(evt):
    """Turn a single stream-json event into one readable line (or '' to suppress)."""
    t = evt.get("type")
    sub = evt.get("subtype")

    if t == "system":
        if sub == "init":
            return f"[init] model={evt.get('model', '?')} cwd={evt.get('cwd', '?')}"
        # Hook noise (SessionStart blobs, etc.) — drop
        return ""

    if t == "assistant":
        for block in evt.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "").strip()
                if text:
                    return f"[assistant] {_truncate(text, 300)}"
            elif btype == "tool_use":
                name = block.get("name", "?")
                args = _format_tool_args(name, block.get("input", {}))
                return f"[tool] {name}({args})"
            elif btype == "thinking":
                text = block.get("thinking", "").strip()
                if text:
                    return f"[thinking] {_truncate(text, 200)}"
        return ""

    if t == "user":
        # Tool results come back as user messages from the harness
        for block in evt.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                summary = _truncate(content, 200)
                marker = " [error]" if block.get("is_error") else ""
                return f"[result]{marker} {summary}"
        return ""

    if t == "result":
        status = "ok" if not evt.get("is_error") else "error"
        turns = evt.get("num_turns", "?")
        dur_ms = evt.get("duration_ms")
        cost = evt.get("total_cost_usd")
        dur = f"{dur_ms/1000:.1f}s" if isinstance(dur_ms, (int, float)) else "?"
        cost_str = f"${cost:.3f}" if isinstance(cost, (int, float)) else "?"
        return f"[done] {status} — {turns} turns, {dur}, {cost_str}"

    # rate_limit_event, stream_event, anything else → drop
    return ""


adapter = ClaudeCodeAdapter()
