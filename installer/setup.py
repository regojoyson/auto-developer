#!/usr/bin/env python3
"""Auto Developer -- Interactive TUI Setup Wizard.

Walks the user through a 7-step terminal-based wizard to configure the
Auto Developer pipeline. Collects settings for the repository layout,
issue tracker, git provider credentials, AI CLI adapter, notifications,
and pipeline tuning parameters, then writes ``config.yaml`` and ``.env``
files and symlinks agent definitions into the target repositories.

Steps:
    1. Repository location and base branch
    2. Issue tracker (Jira or GitHub Issues)
    3. Git provider and API tokens (GitLab or GitHub)
    4. AI coding CLI selection (Claude Code, Codex, or Gemini)
    5. Notification channel (optional Slack)
    6. Pipeline settings (port, rework limit, timeout)
    7. Summary and confirmation

Usage::

    python installer/setup.py
"""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so 'installer' and 'src' are importable
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import questionary
from questionary import Style

from installer.choices import (
    REPO_MODES, ISSUE_TRACKERS, ISSUE_TRACKER_DEFAULTS,
    GIT_PROVIDERS, GIT_PROVIDER_ENV, GIT_PROVIDER_BOTS,
    CLI_ADAPTERS, NOTIFICATION_PROVIDERS, PIPELINE_DEFAULTS,
)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import yaml
sys.path.insert(0, str(PROJECT_ROOT))

from installer.linker import link_agents

console = Console()

STYLE = Style([
    ("qmark", "fg:cyan bold"),
    ("question", "bold"),
    ("answer", "fg:green bold"),
    ("pointer", "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected", "fg:green"),
])

CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"


def banner():
    """Print the setup wizard banner to the terminal."""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Auto Developer[/bold cyan]\n"
        "[dim]Interactive Setup Wizard[/dim]",
        border_style="cyan",
    ))
    console.print()


def step(num: int, total: int, title: str):
    """Print a step header showing progress through the wizard.

    Args:
        num: Current step number (1-based).
        total: Total number of steps.
        title: Human-readable title for this step.
    """
    console.print(f"\n  [cyan]Step {num}/{total}[/cyan] — [bold]{title}[/bold]\n")


def ask_repo(total_steps: int) -> dict:
    """Prompt the user for repository configuration.

    Supports three modes: single local directory, parent directory with
    multiple repos, or cloning from git URLs.

    Args:
        total_steps: Total wizard steps (for the progress header).

    Returns:
        dict: Repository config with keys ``mode``, ``baseBranch``, and
            mode-specific keys (``path``, ``urls``/``cloneDir``).
    """
    step(1, total_steps, "Repository")

    mode = questionary.select(
        "Where is your code?",
        choices=REPO_MODES,
        style=STYLE,
    ).ask()

    repo = {"mode": mode}

    if mode == "dir":
        path = questionary.path("Repo path:", only_directories=True, style=STYLE).ask()
        if path and not Path(path).exists():
            console.print(f"  [yellow]Warning: {path} does not exist yet[/yellow]")
        repo["path"] = path

    elif mode == "parentDir":
        path = questionary.path("Parent directory:", only_directories=True, style=STYLE).ask()
        if path and Path(path).exists():
            subdirs = [d.name for d in sorted(Path(path).iterdir()) if d.is_dir() and not d.name.startswith(".")]
            if subdirs:
                console.print(f"  [green]Found {len(subdirs)} repos:[/green] {', '.join(subdirs[:10])}")
        repo["path"] = path

    elif mode == "clone":
        urls_raw = questionary.text("Git URL(s) (comma-separated):", style=STYLE).ask()
        urls = [u.strip() for u in urls_raw.split(",") if u.strip()]
        clone_dir = questionary.text("Clone directory:", default="/tmp/auto-pilot-repos", style=STYLE).ask()
        repo["urls"] = urls
        repo["cloneDir"] = clone_dir

    base_branch = questionary.text("Base branch:", default="main", style=STYLE).ask()
    repo["baseBranch"] = base_branch

    return repo


def ask_issue_tracker(total_steps: int) -> dict:
    """Prompt the user for issue tracker configuration.

    Supports Jira (trigger on status change) and GitHub Issues (trigger
    on label application).

    Args:
        total_steps: Total wizard steps (for the progress header).

    Returns:
        dict: Issue tracker config with keys ``type``, ``triggerStatus``,
            and ``doneStatus``.
    """
    step(2, total_steps, "Issue Tracker")

    tracker_type = questionary.select(
        "Issue tracker:",
        choices=ISSUE_TRACKERS,
        style=STYLE,
    ).ask()

    config = {"type": tracker_type}
    defaults = ISSUE_TRACKER_DEFAULTS[tracker_type]

    config["triggerStatus"] = questionary.text(
        f"{defaults['trigger_label']} (starts the pipeline):",
        default=defaults["trigger_default"], style=STYLE
    ).ask()
    config["doneStatus"] = questionary.text(
        f"{defaults['done_label']} (after merge):",
        default=defaults["done_default"], style=STYLE
    ).ask()

    return config


def ask_git_provider(total_steps: int) -> tuple[dict, dict]:
    """Prompt the user for git provider selection and API credentials.

    Collects tokens and project identifiers for either GitLab or GitHub,
    storing sensitive values in the env vars dict (written to ``.env``).

    Args:
        total_steps: Total wizard steps (for the progress header).

    Returns:
        tuple[dict, dict]: A 2-tuple of (git_config, env_vars) where
            *git_config* contains ``type`` and ``botUsers``, and
            *env_vars* contains the provider-specific environment
            variables (tokens, project IDs, etc.).
    """
    step(3, total_steps, "Git Provider + Tokens")

    provider_type = questionary.select(
        "Git provider:",
        choices=GIT_PROVIDERS,
        style=STYLE,
    ).ask()

    config = {"type": provider_type}
    env_vars = {}

    console.print(f"  [dim]Enter your {provider_type} credentials (stored in .env)[/dim]\n")

    # Ask for each env var defined in choices.py
    for var_def in GIT_PROVIDER_ENV[provider_type]:
        if var_def["secret"]:
            value = questionary.password(f"{var_def['label']}:", style=STYLE).ask()
        else:
            value = questionary.text(f"{var_def['label']}:", default=var_def["default"], style=STYLE).ask()
        env_vars[var_def["key"]] = value

    bot_users = questionary.text(
        "Bot usernames to ignore (comma-separated):",
        default=GIT_PROVIDER_BOTS[provider_type], style=STYLE
    ).ask()
    config["botUsers"] = [u.strip() for u in bot_users.split(",") if u.strip()]

    return config, env_vars


def ask_cli_adapter(total_steps: int) -> dict:
    """Prompt the user for AI coding CLI adapter selection.

    Supports Claude Code, Codex, and Gemini with optional model override.

    Args:
        total_steps: Total wizard steps (for the progress header).

    Returns:
        dict: CLI adapter config with keys ``type`` and optionally ``model``.
    """
    step(4, total_steps, "AI Coding CLI")

    cli_type = questionary.select(
        "AI coding CLI:",
        choices=CLI_ADAPTERS,
        style=STYLE,
    ).ask()

    config = {"type": cli_type}

    model = questionary.text(
        "Model name (optional, press Enter to skip):",
        default="", style=STYLE
    ).ask()
    if model:
        config["model"] = model

    return config


def ask_notification(total_steps: int) -> dict | None:
    """Prompt the user for notification configuration.

    Notifications are optional. Currently only Slack is supported.

    Args:
        total_steps: Total wizard steps (for the progress header).

    Returns:
        dict or None: Notification config with keys ``type`` and ``channel``
            if enabled, or None if the user declines notifications.
    """
    step(5, total_steps, "Notifications")

    enable = questionary.confirm("Enable notifications?", default=False, style=STYLE).ask()
    if not enable:
        return None

    notif_type = questionary.select(
        "Notification provider:",
        choices=NOTIFICATION_PROVIDERS,
        style=STYLE,
    ).ask()

    channel = questionary.text("Channel name:", default="dev-team", style=STYLE).ask()

    return {"type": notif_type, "channel": channel}


def ask_pipeline(total_steps: int) -> dict:
    """Prompt the user for pipeline runtime settings.

    Collects the server port, maximum rework iteration count, and agent
    timeout duration.

    Args:
        total_steps: Total wizard steps (for the progress header).

    Returns:
        dict: Pipeline config with keys ``port`` (int),
            ``maxReworkIterations`` (int), and ``agentTimeout`` (int,
            in milliseconds).
    """
    step(6, total_steps, "Pipeline Settings")

    port = questionary.text("Server port:", default=PIPELINE_DEFAULTS["port"], style=STYLE).ask()
    max_rework = questionary.text("Max rework iterations:", default=PIPELINE_DEFAULTS["max_rework"], style=STYLE).ask()
    timeout = questionary.text("Agent timeout (seconds):", default=PIPELINE_DEFAULTS["timeout_seconds"], style=STYLE).ask()

    return {
        "port": int(port),
        "maxReworkIterations": int(max_rework),
        "agentTimeout": int(timeout) * 1000,
    }


def show_summary(config: dict, env_vars: dict, total_steps: int):
    """Display a formatted summary table of all collected configuration.

    Shows repository settings, provider choices, pipeline parameters,
    and masked environment variable values for user review before writing.

    Args:
        config: The assembled configuration dict.
        env_vars: Environment variables to write to ``.env`` (tokens are
            masked in the display).
        total_steps: Total wizard steps (for the progress header).
    """
    step(7, total_steps, "Summary")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()

    repo = config["repo"]
    table.add_row("Repo mode", repo["mode"])
    if repo["mode"] in ("dir", "parentDir"):
        table.add_row("Repo path", repo.get("path", ""))
    elif repo["mode"] == "clone":
        table.add_row("Clone URLs", ", ".join(repo.get("urls", [])))
        table.add_row("Clone dir", repo.get("cloneDir", ""))
    table.add_row("Base branch", repo.get("baseBranch", "main"))
    table.add_row("", "")
    table.add_row("Issue tracker", config["issueTracker"]["type"])
    table.add_row("Trigger status", config["issueTracker"].get("triggerStatus", ""))
    table.add_row("Git provider", config["gitProvider"]["type"])
    table.add_row("CLI adapter", config["cliAdapter"]["type"])
    if config["cliAdapter"].get("model"):
        table.add_row("Model", config["cliAdapter"]["model"])
    table.add_row("", "")

    if config.get("notification"):
        table.add_row("Notifications", f"{config['notification']['type']} → #{config['notification'].get('channel', '')}")
    else:
        table.add_row("Notifications", "disabled")

    table.add_row("Port", str(config["pipeline"]["port"]))
    table.add_row("Max rework", str(config["pipeline"]["maxReworkIterations"]))
    table.add_row("Agent timeout", f"{config['pipeline']['agentTimeout'] // 1000}s")

    # Show env vars (masked tokens)
    table.add_row("", "")
    for key, val in env_vars.items():
        display = val[:4] + "****" if ("TOKEN" in key or "token" in key.lower()) and len(val) > 4 else val
        table.add_row(f".env: {key}", display)

    console.print(Panel(table, title="Configuration Summary", border_style="green"))
    console.print()


def write_config(config: dict):
    """Write the assembled configuration to ``config.yaml``.

    Cleans up the config dict (removes empty optional fields) and writes
    it as YAML to the project root.

    Args:
        config: The full configuration dict assembled from wizard responses.
    """
    # Clean up config for YAML output
    yaml_config = {}

    repo = dict(config["repo"])
    yaml_config["repo"] = repo

    yaml_config["issueTracker"] = config["issueTracker"]
    yaml_config["gitProvider"] = config["gitProvider"]

    cli = dict(config["cliAdapter"])
    if not cli.get("model"):
        cli.pop("model", None)
    yaml_config["cliAdapter"] = {"type": cli["type"]}
    if cli.get("model"):
        yaml_config["cliAdapter"]["model"] = cli["model"]

    if config.get("notification"):
        yaml_config["notification"] = config["notification"]

    yaml_config["pipeline"] = config["pipeline"]

    CONFIG_PATH.write_text(yaml.dump(yaml_config, default_flow_style=False, sort_keys=False))
    console.print(f"  [green]+[/green] config.yaml written")


def write_env(env_vars: dict):
    """Write environment variables to ``.env`` in the project root.

    Args:
        env_vars: Dict of environment variable names to values (e.g.
            tokens, project IDs).
    """
    lines = ["# Auto-generated by setup wizard\n"]
    for key, val in env_vars.items():
        lines.append(f"{key}={val}\n")
    ENV_PATH.write_text("".join(lines))
    console.print(f"  [green]+[/green] .env written")


def main():
    """Run the interactive setup wizard.

    Orchestrates the full wizard flow: checks for existing config (offers
    to reconfigure or just re-link), collects settings through each step,
    shows a summary for confirmation, writes config files, and symlinks
    agent files into target repositories.
    """
    banner()

    # Check for existing config
    if CONFIG_PATH.exists():
        reconfig = questionary.confirm(
            "config.yaml already exists. Reconfigure?",
            default=False, style=STYLE,
        ).ask()
        if not reconfig:
            console.print("  [dim]Skipping wizard, running symlink step...[/dim]\n")
            config = yaml.safe_load(CONFIG_PATH.read_text())
            link_agents(config)
            console.print("\n  [green]Done.[/green] Run [cyan]./start.sh[/cyan] to start.\n")
            return
        # Backup old config
        backup = CONFIG_PATH.with_suffix(".yaml.bak")
        CONFIG_PATH.rename(backup)
        console.print(f"  [dim]Old config backed up to {backup.name}[/dim]\n")

    total_steps = 7

    # Step 1: Repo
    repo_config = ask_repo(total_steps)

    # Step 2: Issue tracker
    tracker_config = ask_issue_tracker(total_steps)

    # Step 3: Git provider + tokens
    git_config, env_vars = ask_git_provider(total_steps)

    # Step 4: CLI adapter
    cli_config = ask_cli_adapter(total_steps)

    # Step 5: Notifications
    notif_config = ask_notification(total_steps)

    # Step 6: Pipeline
    pipeline_config = ask_pipeline(total_steps)

    # Assemble full config
    full_config = {
        "repo": repo_config,
        "issueTracker": tracker_config,
        "gitProvider": git_config,
        "cliAdapter": cli_config,
        "pipeline": pipeline_config,
    }
    if notif_config:
        full_config["notification"] = notif_config

    # Step 7: Summary + confirm
    show_summary(full_config, env_vars, total_steps)

    proceed = questionary.confirm("Write config and proceed?", default=True, style=STYLE).ask()
    if not proceed:
        console.print("  [yellow]Aborted.[/yellow]\n")
        return

    # Write files
    console.print()
    write_config(full_config)
    write_env(env_vars)

    # Symlink agents
    console.print()
    link_agents(full_config)

    # Done
    console.print()
    console.print(Panel.fit(
        "[bold green]Setup complete![/bold green]\n\n"
        "Next: [cyan]./start.sh[/cyan] to start the pipeline\n"
        "Stop: [cyan]./stop.sh[/cyan] to stop everything",
        border_style="green",
    ))
    console.print()


if __name__ == "__main__":
    main()
