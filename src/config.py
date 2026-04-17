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

# Maps config type to (platform, api_mode)
_TRACKER_TYPE_MAP = {
    "jira-mcp": ("jira", "mcp"),
    "jira-api": ("jira", "api"),
    "github-mcp": ("github-issues", "mcp"),
    "github-api": ("github-issues", "api"),
    # Backward compat: old type names default to mcp mode
    "jira": ("jira", "mcp"),
    "github-issues": ("github-issues", "mcp"),
}


def _parse_issue_tracker(raw_tracker: dict) -> dict:
    """Parse the issueTracker config section.

    Handles the 4 type values (jira-mcp, jira-api, github-mcp, github-api)
    and splits into platform + api_mode for internal use.
    """
    raw_type = raw_tracker.get("type", "jira-mcp")
    if raw_type not in _TRACKER_TYPE_MAP:
        raise ValueError(
            f"Unknown issue tracker type: '{raw_type}'. "
            f"Supported: {', '.join(_TRACKER_TYPE_MAP.keys())}"
        )
    platform, api_mode = _TRACKER_TYPE_MAP[raw_type]

    return {
        "type": raw_type,
        "platform": platform,       # "jira" or "github-issues"
        "api_mode": api_mode,        # "mcp" or "api"
        "trigger_status": raw_tracker.get("triggerStatus", "Ready for Development"),
        "development_status": raw_tracker.get("developmentStatus", "Development"),
        "done_status": raw_tracker.get("doneStatus", "Done"),
        "blocked_status": raw_tracker.get("blockedStatus", "Blocked"),
        "bot_users": raw_tracker.get("botUsers", []),
    }


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
            "default_component": raw.get("repo", {}).get("defaultComponent"),
        },
        "issue_tracker": _parse_issue_tracker(raw.get("issueTracker", {})),
        "git_provider": {
            "type": raw.get("gitProvider", {}).get("type", "gitlab"),
            "bot_users": raw.get("gitProvider", {}).get("botUsers", []),
        },
        "cli_adapter": {
            "type": raw.get("cliAdapter", {}).get("type", "claude-code"),
            "model": raw.get("cliAdapter", {}).get("model"),
            "fallback_model": raw.get("cliAdapter", {}).get("fallbackModel"),
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
            "allow_cli_skills": raw.get("pipeline", {}).get("allowCliSkills", False),
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
