"""Claude Code CLI adapter.

Implements the :class:`~src.providers.base.CliAdapterBase` interface for
the Claude Code CLI (``claude``). Builds command-line arguments to invoke
agents in non-interactive print mode with auto-approved tool calls, and
parses the resulting stdout/stderr into a normalized result dict.

The module exposes a singleton ``adapter`` instance at module level for
use by the CLI adapter factory.
"""

from src.providers.base import CliAdapterBase


class ClaudeCodeAdapter(CliAdapterBase):
    """Adapter for invoking AI coding agents via the Claude Code CLI.

    Uses ``--print`` for non-interactive output and
    ``--dangerously-skip-permissions`` to auto-approve all tool calls
    during automated pipeline runs. Supports optional model selection
    and max turn limits via config.
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
                optional keys ``model``, ``max_turns``, and ``extra_args``.

        Returns:
            list[str]: CLI argument strings suitable for subprocess execution.
        """
        args = [
            "--agent", agent_name,
            "--print",                  # non-interactive output mode
            "--dangerously-skip-permissions",  # auto-approve all tool calls
        ]
        if config.get("model"):
            args.extend(["--model", config["model"]])
        if config.get("max_turns"):
            args.extend(["--max-turns", str(config["max_turns"])])
        args.extend(config.get("extra_args") or [])
        args.append(input_text)         # prompt as positional argument (must be last)
        return args

    def parse_output(self, stdout, stderr, exit_code):
        """Parse and normalize the Claude Code CLI output.

        Args:
            stdout: Standard output captured from the CLI process.
            stderr: Standard error captured from the CLI process.
            exit_code: Process exit code (0 indicates success).

        Returns:
            dict: A dict with keys ``success`` (bool), ``output`` (str),
                and ``error`` (str or None).
        """
        return {
            "success": exit_code == 0,
            "output": stdout,
            "error": stderr or f"Exited with code {exit_code}" if exit_code != 0 else None,
        }


adapter = ClaudeCodeAdapter()
