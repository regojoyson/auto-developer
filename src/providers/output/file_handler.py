"""File-based output handler — writes agent output to log files in real-time.

Each agent run creates a log file at ``logs/agents/{issueKey}-{agent}.log``.
Lines are flushed immediately so you can ``tail -f`` while the agent runs.

Usage::

    tail -f logs/agents/EV-14942-orchestrator.log
"""

from pathlib import Path
from src.providers.base import OutputHandlerBase

LOG_DIR = Path(__file__).parent.parent.parent.parent / "logs" / "agents"


class FileHandler(OutputHandlerBase):
    """Writes agent output to per-agent log files."""

    name = "file"

    def __init__(self):
        self._files: dict[str, object] = {}

    def _key(self, issue_key: str, agent_name: str) -> str:
        return f"{issue_key}-{agent_name}"

    def on_start(self, issue_key, agent_name, cwd):
        """Open the log file for writing."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        key = self._key(issue_key, agent_name)
        path = LOG_DIR / f"{key}.log"
        self._files[key] = open(path, "a", buffering=1)  # line-buffered
        self._files[key].write(f"--- Agent {agent_name} started for {issue_key} (cwd: {cwd}) ---\n")
        self._files[key].flush()

    def on_output(self, issue_key, agent_name, line, stream):
        """Write a line to the log file."""
        key = self._key(issue_key, agent_name)
        f = self._files.get(key)
        if f:
            prefix = "[ERR] " if stream == "stderr" else ""
            f.write(f"{prefix}{line}\n")
            f.flush()

    def on_finish(self, issue_key, agent_name, exit_code):
        """Close the log file."""
        key = self._key(issue_key, agent_name)
        f = self._files.pop(key, None)
        if f:
            f.write(f"--- Agent {agent_name} finished with exit code {exit_code} ---\n")
            f.flush()
            f.close()

    def delete_logs(self, issue_key):
        """Delete all log files for an issue.

        Closes any open file handles first, then removes matching log files.

        Args:
            issue_key: Ticket identifier (e.g. "PROJ-123").
        """
        # Close any open handles for this issue
        keys_to_close = [k for k in self._files if k.startswith(f"{issue_key}-")]
        for key in keys_to_close:
            f = self._files.pop(key, None)
            if f:
                f.close()

        # Delete matching log files
        for path in LOG_DIR.glob(f"{issue_key}-*.log"):
            path.unlink(missing_ok=True)

    def get_output(self, issue_key, agent_name=None):
        """Read the log file contents."""
        if agent_name:
            path = LOG_DIR / f"{self._key(issue_key, agent_name)}.log"
            return path.read_text() if path.exists() else ""
        # Return all agent logs for this issue
        output = []
        for path in sorted(LOG_DIR.glob(f"{issue_key}-*.log")):
            output.append(path.read_text())
        return "\n".join(output)


handler = FileHandler()
