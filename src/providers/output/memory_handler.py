"""In-memory output handler — keeps agent output in a buffer for API queries.

Serves the ``GET /api/status/{issueKey}/logs`` endpoint. Output is kept
in memory while the agent runs and for a period after completion.

Call ``clear(issue_key)`` to free memory after the pipeline finishes.
"""

from collections import defaultdict
from src.providers.base import OutputHandlerBase


class MemoryHandler(OutputHandlerBase):
    """Keeps agent output in memory for API access."""

    name = "memory"

    def __init__(self):
        # {issue_key: {agent_name: [lines]}}
        self._buffers: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    def on_start(self, issue_key, agent_name, cwd):
        """Initialize the buffer for this agent run."""
        self._buffers[issue_key][agent_name] = [
            f"--- Agent {agent_name} started (cwd: {cwd}) ---"
        ]

    def on_output(self, issue_key, agent_name, line, stream):
        """Append a line to the in-memory buffer."""
        prefix = "[ERR] " if stream == "stderr" else ""
        self._buffers[issue_key][agent_name].append(f"{prefix}{line}")

    def on_finish(self, issue_key, agent_name, exit_code):
        """Mark the agent as finished in the buffer."""
        self._buffers[issue_key][agent_name].append(
            f"--- Agent {agent_name} finished with exit code {exit_code} ---"
        )

    def get_output(self, issue_key, agent_name=None):
        """Get buffered output for an issue.

        Args:
            issue_key: Ticket identifier.
            agent_name: Optional — if set, returns only that agent's output.

        Returns:
            String with all buffered lines joined by newlines.
        """
        if issue_key not in self._buffers:
            return ""

        if agent_name:
            lines = self._buffers[issue_key].get(agent_name, [])
            return "\n".join(lines)

        # All agents for this issue
        output = []
        for agent, lines in self._buffers[issue_key].items():
            output.extend(lines)
        return "\n".join(output)

    def delete_logs(self, issue_key: str):
        """Delete all buffered output for an issue.

        Args:
            issue_key: Ticket identifier to clear.
        """
        self._buffers.pop(issue_key, None)

    def clear(self, issue_key: str):
        """Free memory for a completed pipeline.

        Args:
            issue_key: Ticket identifier to clear.
        """
        self._buffers.pop(issue_key, None)


handler = MemoryHandler()
