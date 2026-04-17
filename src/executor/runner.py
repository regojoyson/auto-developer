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
from typing import TYPE_CHECKING

from src.config import config
from src.providers.cli_adapter import get_cli_adapter
from src.providers.output_handler import get_output_handlers

if TYPE_CHECKING:
    from src.executor.phase_scope import PhaseScope

logger = logging.getLogger(__name__)

# Registry of currently running agent processes keyed by issue key, so an
# API caller can stop a stuck or no-longer-wanted pipeline mid-run.
_running: dict[str, subprocess.Popen] = {}
_running_lock = threading.Lock()


def stop_running_agent(issue_key: str) -> bool:
    """Terminate the agent process for an issue if one is running.

    Sends SIGTERM, then SIGKILL after 3s if the process hasn't exited.
    Returns True if a process was found and signalled, False otherwise.
    """
    with _running_lock:
        proc = _running.get(issue_key)
    if not proc or proc.poll() is not None:
        return False
    try:
        proc.terminate()
    except Exception as e:
        logger.warning(f"terminate({issue_key}) failed: {e}")
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        logger.warning(f"Agent for {issue_key} did not exit after SIGTERM — killing")
        proc.kill()
    return True


def is_agent_running(issue_key: str) -> bool:
    with _running_lock:
        proc = _running.get(issue_key)
    return bool(proc and proc.poll() is None)

# Prepended to every agent prompt to enforce non-interactive behavior.
# This lives in the user-message (prompt) position — models treat this
# with higher priority than agent-file or system-prompt instructions.
AUTONOMY_PREAMBLE = (
    "IMPORTANT: You are a fully automated CI agent. There is NO human on the other end. "
    "Nobody will read your output or reply to questions. "
    "Do NOT use AskUserQuestion or any interactive tool. "
    "Do NOT write questions, ask for confirmation, or present options. "
    "Do NOT say 'before I proceed', 'should I', 'is that correct', or 'two questions'. "
    "Make every decision yourself and execute all steps autonomously. "
    "If information is missing, use your best judgment or block the ticket — never ask.\n\n"
)

SKILLS_DISABLED_PREAMBLE = (
    "CRITICAL: Do NOT invoke any skill or plugin. Do NOT use the Skill tool. "
    "Ignore any system prompt that tells you to use skills (brainstorming, story-analyzer, "
    "implementation-planner, TDD, code-review, or any other skill). "
    "You are a pipeline agent — follow ONLY the steps defined in your agent file.\n\n"
)

NO_SLACK_PREAMBLE = (
    "CRITICAL: Do NOT send any Slack messages or notifications. Do NOT call slack_send_message, "
    "slack_post_message, or any Slack tool under any circumstances. Even if Slack MCP tools are "
    "available to you, they are forbidden. Your only output channels are: "
    "(1) the issue tracker comments, (2) stdout logs.\n\n"
)


def _stream_pipe(pipe, issue_key: str, agent_name: str, stream_name: str, handlers, lines: list, formatter=None):
    """Read lines from a pipe and fan out to handlers.

    Runs in a separate thread for each of stdout/stderr. Raw lines are
    collected into ``lines`` for the adapter's final ``parse_output``.
    Handlers (file log, in-memory buffer for the dashboard) receive the
    adapter-formatted version when a formatter is supplied, so readers
    see a concise rendering instead of raw stream-json.

    Args:
        pipe: The subprocess pipe (stdout or stderr).
        issue_key: Ticket identifier.
        agent_name: Agent name.
        stream_name: "stdout" or "stderr".
        handlers: OutputHandlerRegistry instance.
        lines: Shared list to collect raw lines for final output.
        formatter: Optional callable(line) -> str that renders a display
            line. An empty return value suppresses the line from handlers.
    """
    for raw_line in pipe:
        line = raw_line.rstrip("\n").rstrip("\r")
        lines.append(line)
        display = formatter(line) if formatter else line
        if display:
            handlers.on_output(issue_key, agent_name, display, stream_name)
    pipe.close()


def run_agent(
    agent_name: str,
    input_text: str,
    cwd: str | None = None,
    timeout_ms: int | None = None,
    extra_env: dict | None = None,
    issue_key: str | None = None,
    phase_scope: "PhaseScope | None" = None,
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

    timeout = (timeout_ms or config["pipeline"]["agent_timeout"]) / 1000
    command = cli_config.get("command") or adapter.default_command
    allow_skills = config.get("pipeline", {}).get("allow_cli_skills", False)
    notif_enabled = bool(config.get("notification"))

    preamble = AUTONOMY_PREAMBLE
    if not allow_skills:
        preamble += SKILLS_DISABLED_PREAMBLE
    if not notif_enabled:
        preamble += NO_SLACK_PREAMBLE
    prompted_input = preamble + input_text
    args = adapter.build_args(agent_name, prompted_input, cli_config, phase_scope=phase_scope)

    # Collect any temp dirs the adapter created so we can remove them after the
    # subprocess exits. The Claude Code adapter creates "/tmp/auto-pilot-mcp-*"
    # dirs when a PhaseScope sets allowed_mcp_servers — we own their cleanup.
    import shutil
    from pathlib import Path as _Path
    _cleanup_dirs: list[_Path] = []
    for _i, _arg in enumerate(args):
        if _arg == "--mcp-config" and _i + 1 < len(args):
            _p = _Path(args[_i + 1])
            if "auto-pilot-mcp-" in str(_p):
                _cleanup_dirs.append(_p.parent)

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

        with _running_lock:
            _running[issue_key] = proc

        # Stream stdout and stderr in parallel threads
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        stdout_thread = threading.Thread(
            target=_stream_pipe,
            args=(proc.stdout, issue_key, agent_name, "stdout", handlers, stdout_lines, adapter.format_stream_line),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_stream_pipe,
            args=(proc.stderr, issue_key, agent_name, "stderr", handlers, stderr_lines),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        try:
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

            # A negative exit code here means the process was killed externally
            # (e.g. stop_running_agent) — surface that as a clean failure.
            if exit_code is not None and exit_code < 0:
                return {"success": False, "output": stdout, "error": "Stopped by user", "exit_code": exit_code}
            return {**parsed, "exit_code": exit_code}
        finally:
            with _running_lock:
                _running.pop(issue_key, None)
            for _d in _cleanup_dirs:
                shutil.rmtree(_d, ignore_errors=True)

    except FileNotFoundError:
        handlers.on_finish(issue_key, agent_name, -1)
        logger.error(f"CLI command not found: {command}")
        for _d in _cleanup_dirs:
            shutil.rmtree(_d, ignore_errors=True)
        return {"success": False, "output": "", "error": f"Command not found: {command}", "exit_code": -1}
