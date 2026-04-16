"""
Unified configuration loader.

Reads config.yaml once on first import and caches the result as a module-level
dict. Every other module in the pipeline imports from here:

    from src.config import config
    print(config["repo"]["mode"])       # 'dir', 'parentDir', or 'clone'
    print(config["git_provider"]["type"])  # 'gitlab' or 'github'

The config dict has these top-level keys:
    - repo           — repo mode, path, baseBranch, clone URLs
    - issue_tracker  — type, triggerStatus, doneStatus, botUsers
    - git_provider   — type, botUsers
    - cli_adapter    — type, model, timeout, command, extra_args
    - notification   — type, channel (or None if disabled)
    - pipeline       — port, max_rework_iterations, agent_timeout

Secrets (tokens) stay in .env and are read via os.environ at runtime —
they are NOT in this config.
"""

from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_cache = None


def load() -> dict:
    """
    Load and parse config.yaml into a normalized dict.

    Returns the cached config if already loaded. Raises FileNotFoundError
    if config.yaml doesn't exist (user needs to run ./setup.sh first).

    Returns:
        dict with keys: repo, issue_tracker, git_provider, cli_adapter,
        notification, pipeline.
    """
    global _cache
    if _cache:
        return _cache

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"config.yaml not found at {CONFIG_PATH}.\n"
            "Run ./setup.sh to generate it, or create it manually (see docs/configuration.md)."
        )

    raw = yaml.safe_load(CONFIG_PATH.read_text())

    _cache = {
        "repo": {
            "mode": raw.get("repo", {}).get("mode", "dir"),
            "path": raw.get("repo", {}).get("path"),
            "urls": raw.get("repo", {}).get("urls", []),
            "clone_dir": raw.get("repo", {}).get("cloneDir", "/tmp/auto-pilot-repos"),
            "base_branch": raw.get("repo", {}).get("baseBranch", "main"),
        },
        "issue_tracker": {
            "type": raw.get("issueTracker", {}).get("type", "jira"),
            "trigger_status": raw.get("issueTracker", {}).get("triggerStatus", "Ready for Development"),
            "done_status": raw.get("issueTracker", {}).get("doneStatus", "Done"),
            "blocked_status": raw.get("issueTracker", {}).get("blockedStatus", "Blocked"),
            "bot_users": raw.get("issueTracker", {}).get("botUsers", []),
        },
        "git_provider": {
            "type": raw.get("gitProvider", {}).get("type", "gitlab"),
            "bot_users": raw.get("gitProvider", {}).get("botUsers", []),
        },
        "cli_adapter": {
            "type": raw.get("cliAdapter", {}).get("type", "claude-code"),
            "model": raw.get("cliAdapter", {}).get("model"),
            "max_turns": raw.get("cliAdapter", {}).get("maxTurnsPerRun"),
            "timeout": raw.get("cliAdapter", {}).get("timeout", 300000),
            "command": raw.get("cliAdapter", {}).get("command"),
            "extra_args": raw.get("cliAdapter", {}).get("extraArgs", []),
        },
        "notification": (
            {
                "type": raw["notification"]["type"],
                "channel": raw["notification"].get("channel"),
            }
            if raw.get("notification")
            else None
        ),
        "pipeline": {
            "max_rework_iterations": raw.get("pipeline", {}).get("maxReworkIterations", 3),
            "agent_timeout": raw.get("pipeline", {}).get("agentTimeout", 300000),
            "port": raw.get("pipeline", {}).get("port", 3000),
            "output_handlers": raw.get("pipeline", {}).get("outputHandlers", ["file", "memory"]),
        },
    }
    return _cache


def reload() -> dict:
    """Clear the cached config and re-read from disk. Returns the fresh config."""
    global _cache
    _cache = None
    return load()


# Auto-load on first import so other modules can do: from src.config import config
config = load()
