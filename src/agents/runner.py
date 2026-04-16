"""Agent runner — spawns AI coding CLI processes via the configured adapter."""

import logging
import os
import subprocess

from src.config import config
from src.providers.cli_adapter import get_cli_adapter

logger = logging.getLogger(__name__)


def run_agent(
    agent_name: str,
    input_text: str,
    cwd: str | None = None,
    timeout_ms: int | None = None,
    extra_env: dict | None = None,
) -> dict:
    """
    Invoke an agent via the configured CLI adapter.

    Returns: { success, output, error, exit_code }
    """
    adapter, cli_config = get_cli_adapter()

    timeout = (timeout_ms or cli_config.get("timeout") or config["pipeline"]["agent_timeout"]) / 1000
    command = cli_config.get("command") or adapter.default_command
    args = adapter.build_args(agent_name, input_text, cli_config)
    env = adapter.build_env({**os.environ, **(extra_env or {})}, cli_config)
    work_dir = cwd or os.getcwd()

    logger.info(f"Invoking agent: {agent_name} via {adapter.label}", extra={"command": command, "cwd": work_dir})

    try:
        result = subprocess.run(
            [command, *args],
            cwd=work_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        parsed = adapter.parse_output(result.stdout, result.stderr, result.returncode)
        logger.info(f"Agent {agent_name} exited with code {result.returncode}")
        if result.stderr:
            logger.warning(f"Agent {agent_name} stderr: {result.stderr[:500]}")
        return {**parsed, "exit_code": result.returncode}

    except subprocess.TimeoutExpired:
        logger.error(f"Agent {agent_name} timed out after {timeout}s")
        return {"success": False, "output": "", "error": f"Timed out after {timeout}s", "exit_code": -1}

    except FileNotFoundError:
        logger.error(f"CLI command not found: {command}")
        return {"success": False, "output": "", "error": f"Command not found: {command}", "exit_code": -1}
