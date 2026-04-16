#!/usr/bin/env python3
"""Auto Developer — Interactive TUI Setup Wizard.

Generates config.yaml + .env in one interactive session.
Then symlinks agent files into target repos.
"""

import os
import sys
from pathlib import Path

import questionary
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import yaml

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent
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
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Auto Developer[/bold cyan]\n"
        "[dim]Interactive Setup Wizard[/dim]",
        border_style="cyan",
    ))
    console.print()


def step(num: int, total: int, title: str):
    console.print(f"\n  [cyan]Step {num}/{total}[/cyan] — [bold]{title}[/bold]\n")


def ask_repo(total_steps: int) -> dict:
    step(1, total_steps, "Repository")

    mode = questionary.select(
        "Where is your code?",
        choices=[
            questionary.Choice("Local directory (one repo)", value="dir"),
            questionary.Choice("Parent directory (multiple repos)", value="parentDir"),
            questionary.Choice("Clone from git URL(s)", value="clone"),
        ],
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
    step(2, total_steps, "Issue Tracker")

    tracker_type = questionary.select(
        "Issue tracker:",
        choices=[
            questionary.Choice("Jira", value="jira"),
            questionary.Choice("GitHub Issues", value="github-issues"),
        ],
        style=STYLE,
    ).ask()

    config = {"type": tracker_type}

    if tracker_type == "jira":
        config["triggerStatus"] = questionary.text(
            "Trigger status (ticket status that starts the pipeline):",
            default="Ready for Development", style=STYLE
        ).ask()
        config["doneStatus"] = questionary.text(
            "Done status (after merge):", default="Done", style=STYLE
        ).ask()

    elif tracker_type == "github-issues":
        config["triggerStatus"] = questionary.text(
            "Trigger label (label that starts the pipeline):",
            default="ready-for-dev", style=STYLE
        ).ask()
        config["doneStatus"] = questionary.text(
            "Done label (after merge):", default="done", style=STYLE
        ).ask()

    return config


def ask_git_provider(total_steps: int) -> tuple[dict, dict]:
    step(3, total_steps, "Git Provider + Tokens")

    provider_type = questionary.select(
        "Git provider:",
        choices=[
            questionary.Choice("GitLab", value="gitlab"),
            questionary.Choice("GitHub", value="github"),
        ],
        style=STYLE,
    ).ask()

    config = {"type": provider_type}
    env_vars = {}

    if provider_type == "gitlab":
        console.print("  [dim]Enter your GitLab credentials (stored in .env)[/dim]\n")
        env_vars["GITLAB_BASE_URL"] = questionary.text(
            "GitLab URL:", default="https://gitlab.com", style=STYLE
        ).ask()
        env_vars["GITLAB_TOKEN"] = questionary.password(
            "GitLab token (api scope):", style=STYLE
        ).ask()
        env_vars["GITLAB_PROJECT_ID"] = questionary.text(
            "GitLab project ID (numeric):", style=STYLE
        ).ask()

        bot_users = questionary.text(
            "Bot usernames to ignore (comma-separated):",
            default="project_bot, ghost, ci-bot", style=STYLE
        ).ask()
        config["botUsers"] = [u.strip() for u in bot_users.split(",") if u.strip()]

    elif provider_type == "github":
        console.print("  [dim]Enter your GitHub credentials (stored in .env)[/dim]\n")
        env_vars["GITHUB_TOKEN"] = questionary.password(
            "GitHub token:", style=STYLE
        ).ask()
        env_vars["GITHUB_OWNER"] = questionary.text(
            "GitHub owner (org or username):", style=STYLE
        ).ask()
        env_vars["GITHUB_REPO"] = questionary.text(
            "GitHub repo name:", style=STYLE
        ).ask()

        bot_users = questionary.text(
            "Bot usernames to ignore (comma-separated):",
            default="dependabot[bot], github-actions[bot]", style=STYLE
        ).ask()
        config["botUsers"] = [u.strip() for u in bot_users.split(",") if u.strip()]

    return config, env_vars


def ask_cli_adapter(total_steps: int) -> dict:
    step(4, total_steps, "AI Coding CLI")

    cli_type = questionary.select(
        "AI coding CLI:",
        choices=[
            questionary.Choice("Claude Code", value="claude-code"),
            questionary.Choice("Codex", value="codex"),
            questionary.Choice("Gemini", value="gemini"),
        ],
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
    step(5, total_steps, "Notifications")

    enable = questionary.confirm("Enable notifications?", default=False, style=STYLE).ask()
    if not enable:
        return None

    notif_type = questionary.select(
        "Notification provider:",
        choices=[questionary.Choice("Slack", value="slack")],
        style=STYLE,
    ).ask()

    channel = questionary.text("Channel name:", default="dev-team", style=STYLE).ask()

    return {"type": notif_type, "channel": channel}


def ask_pipeline(total_steps: int) -> dict:
    step(6, total_steps, "Pipeline Settings")

    port = questionary.text("Server port:", default="3000", style=STYLE).ask()
    max_rework = questionary.text("Max rework iterations:", default="3", style=STYLE).ask()
    timeout = questionary.text("Agent timeout (seconds):", default="300", style=STYLE).ask()

    return {
        "port": int(port),
        "maxReworkIterations": int(max_rework),
        "agentTimeout": int(timeout) * 1000,
    }


def show_summary(config: dict, env_vars: dict, total_steps: int):
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
    lines = ["# Auto-generated by setup wizard\n"]
    for key, val in env_vars.items():
        lines.append(f"{key}={val}\n")
    ENV_PATH.write_text("".join(lines))
    console.print(f"  [green]+[/green] .env written")


def main():
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
