"""
Agent runner — spawns AI coding CLI processes with real-time output streaming.

Uses subprocess.Popen instead of subprocess.run so output lines are
streamed to output handlers (file logger, memory buffer, etc.) as they
arrive — not buffered until the process finishes.

Usage::

    from src.executor.runner import run_agent
    result = run_agent("orchestrator", '{"issueKey": "PROJ-1"}', cwd="/projects/app")
"""

import logging
import os
import subprocess
import threading
import time

from src.config import config
from src.providers.cli_adapter import get_cli_adapter
from src.providers.output_handler import get_output_handlers

logger = logging.getLogger(__name__)


def _stream_pipe(pipe, issue_key: str, agent_name: str, stream_name: str, handlers, lines: list):
    """Read lines from a pipe and fan out to handlers.

    Runs in a separate thread for each of stdout/stderr.

    Args:
        pipe: The subprocess pipe (stdout or stderr).
        issue_key: Ticket identifier.
        agent_name: Agent name.
        stream_name: "stdout" or "stderr".
        handlers: OutputHandlerRegistry instance.
        lines: Shared list to collect lines for final output.
    """
    for raw_line in pipe:
        line = raw_line.rstrip("\n").rstrip("\r")
        lines.append(line)
        handlers.on_output(issue_key, agent_name, line, stream_name)
    pipe.close()


def run_agent(
    agent_name: str,
    input_text: str,
    cwd: str | None = None,
    timeout_ms: int | None = None,
    extra_env: dict | None = None,
    issue_key: str | None = None,
) -> dict:
    """Invoke an agent via the configured CLI adapter with real-time output streaming.

    Args:
        agent_name: Name of the agent to invoke (e.g. "orchestrator").
        input_text: JSON string input to pass to the agent.
        cwd: Working directory for the agent process.
        timeout_ms: Process timeout in milliseconds.
        extra_env: Additional environment variables to merge.
        issue_key: Ticket identifier for output handler routing.
            If not provided, attempts to extract from input_text.

    Returns:
        Dict with keys: success, output, error, exit_code.
    """
    adapter, cli_config = get_cli_adapter()
    handlers = get_output_handlers()

    timeout = (timeout_ms or cli_config.get("timeout") or config["pipeline"]["agent_timeout"]) / 1000
    command = cli_config.get("command") or adapter.default_command
    args = adapter.build_args(agent_name, input_text, cli_config)
    env = adapter.build_env({**os.environ, **(extra_env or {})}, cli_config)
    work_dir = cwd or os.getcwd()

    # Extract issue_key from input if not provided
    if not issue_key:
        try:
            import json
            issue_key = json.loads(input_text).get("issueKey", "unknown")
        except Exception:
            issue_key = "unknown"

    logger.info(f"Invoking agent: {agent_name} via {adapter.label}", extra={"command": command, "cwd": work_dir})
    handlers.on_start(issue_key, agent_name, work_dir)

    try:
        proc = subprocess.Popen(
            [command, *args],
            cwd=work_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Stream stdout and stderr in parallel threads
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        stdout_thread = threading.Thread(
            target=_stream_pipe,
            args=(proc.stdout, issue_key, agent_name, "stdout", handlers, stdout_lines),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_stream_pipe,
            args=(proc.stderr, issue_key, agent_name, "stderr", handlers, stderr_lines),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        # Wait for process with timeout
        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            handlers.on_finish(issue_key, agent_name, -1)
            logger.error(f"Agent {agent_name} timed out after {timeout}s")
            return {"success": False, "output": "\n".join(stdout_lines), "error": f"Timed out after {timeout}s", "exit_code": -1}

        # Wait for stream threads to finish
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        handlers.on_finish(issue_key, agent_name, exit_code)

        stdout = "\n".join(stdout_lines)
        stderr = "\n".join(stderr_lines)
        parsed = adapter.parse_output(stdout, stderr, exit_code)

        logger.info(f"Agent {agent_name} exited with code {exit_code}")
        if stderr:
            logger.warning(f"Agent {agent_name} stderr: {stderr[:500]}")

        return {**parsed, "exit_code": exit_code}

    except FileNotFoundError:
        handlers.on_finish(issue_key, agent_name, -1)
        logger.error(f"CLI command not found: {command}")
        return {"success": False, "output": "", "error": f"Command not found: {command}", "exit_code": -1}
