"""Gemini CLI adapter.

Implements the :class:`~src.providers.base.CliAdapterBase` interface for
the Gemini CLI (``gemini``). Builds command-line arguments to invoke agents
in auto-approve mode and parses the resulting stdout/stderr into a normalized
result dict.

The module exposes a singleton ``adapter`` instance at module level for
use by the CLI adapter factory.
"""

from src.providers.base import CliAdapterBase


class GeminiAdapter(CliAdapterBase):
    """Adapter for invoking AI coding agents via the Gemini CLI.

    Prepends the agent name to the prompt text and uses ``--auto-approve``
    to auto-approve all actions during automated pipeline runs. Supports
    optional model selection via config.
    """

    name = "gemini"
    label = "Gemini CLI"
    default_command = "gemini"
    agent_dir = ".gemini/agents"
    config_dir = ".gemini"
    rules_file_name = "GEMINI.md"

    def build_args(self, agent_name, input_text, config):
        """Build command-line arguments for a Gemini agent invocation.

        The agent name is embedded in the prompt as a ``[Agent: ...]``
        prefix so the CLI can route to the correct agent behavior.

        Args:
            agent_name: Name of the agent to invoke (e.g. ``"orchestrator"``).
            input_text: JSON-encoded input string to pass to the agent.
            config: The ``cli_adapter`` section from config.yaml. Supports
                optional keys ``model`` and ``extra_args``.

        Returns:
            list[str]: CLI argument strings suitable for subprocess execution.
        """
        prompt = f"[Agent: {agent_name}]\n{input_text}"
        args = [
            "--prompt", prompt,
            "--auto-approve",           # auto-approve all actions
        ]
        if config.get("model"):
            args.extend(["--model", config["model"]])
        args.extend(config.get("extra_args") or [])
        return args

    def parse_output(self, stdout, stderr, exit_code):
        """Parse and normalize the Gemini CLI output.

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


adapter = GeminiAdapter()
