#!/usr/bin/env python3
"""Auto Developer — Interactive TUI Setup Wizard.

Walks through a step-by-step terminal wizard to configure everything
needed to run the Auto Developer pipeline. Generates config.yaml + .env
and symlinks agent files into your repos.

Usage::

    ./setup.sh        # or: PYTHONPATH=. python3 installer/setup.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import questionary
from questionary import Style
from installer.choices import (
    REPO_MODES, ISSUE_TRACKERS, ISSUE_TRACKER_DEFAULTS, ISSUE_TRACKER_ENV,
    GIT_PROVIDERS, GIT_PROVIDER_ENV, GIT_PROVIDER_BOTS,
    CLI_ADAPTERS, NOTIFICATION_PROVIDERS, PIPELINE_DEFAULTS,
    OUTPUT_HANDLERS,
)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.status import Status
import yaml

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

# ─── Helpers ──────────────────────────────────────────

def banner():
    """Print the welcome banner."""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Auto Developer[/bold cyan]\n"
        "[dim]Interactive Setup Wizard[/dim]\n\n"
        "[dim]This wizard will configure the pipeline in 7 steps.[/dim]\n"
        "[dim]It generates [cyan]config.yaml[/cyan] and [cyan].env[/cyan], then links agent files into your repos.[/dim]",
        border_style="cyan",
    ))
    console.print()


def step(num: int, total: int, title: str, description: str):
    """Print a step header with description."""
    console.print(f"\n  [cyan]━━━ Step {num}/{total} — {title} ━━━[/cyan]")
    console.print(f"  [dim]{description}[/dim]\n")


def info(msg: str):
    """Print an info message."""
    console.print(f"  [cyan]ℹ[/cyan]  {msg}")


def success(msg: str):
    """Print a success message."""
    console.print(f"  [green]✓[/green]  {msg}")


def warn(msg: str):
    """Print a warning message."""
    console.print(f"  [yellow]⚠[/yellow]  {msg}")


def error(msg: str):
    """Print an error message."""
    console.print(f"  [red]✗[/red]  {msg}")


def check_prerequisite(name: str, check_cmd: str) -> bool:
    """Check if a tool is available and print result."""
    result = shutil.which(check_cmd)
    if result:
        success(f"{name} found: {result}")
        return True
    else:
        warn(f"{name} not found — install it before running the pipeline")
        return False


# ─── Steps ────────────────────────────────────────────

def check_prerequisites():
    """Step 0: Check what's installed and inform the user."""
    console.print("  [cyan]━━━ Pre-flight Check ━━━[/cyan]")
    console.print("  [dim]Checking what tools are available on your system.[/dim]\n")

    with console.status("  Checking tools...", spinner="dots"):
        import time; time.sleep(0.3)  # brief pause so spinner is visible
    check_prerequisite("Git", "git")
    check_prerequisite("Python 3", "python3")

    # Check for AI CLIs
    has_any_cli = False
    for cmd, label in [("claude", "Claude Code CLI"), ("codex", "Codex CLI"), ("gemini", "Gemini CLI")]:
        if shutil.which(cmd):
            success(f"{label} found")
            has_any_cli = True

    if not has_any_cli:
        warn("No AI coding CLI found (claude / codex / gemini)")
        info("You'll need one installed before running the pipeline")
        info("  Claude Code: https://docs.anthropic.com/en/docs/claude-code")
        info("  Codex:       npm install -g @openai/codex")
        info("  Gemini:      https://github.com/google-gemini/gemini-cli")

    console.print()


def ask_repo(total_steps: int, prev: dict | None = None) -> dict:
    """Step 1: Where is the code?"""
    p = (prev or {}).get("repo", {})
    step(1, total_steps, "Repository",
         "Where is the code the AI agents will work on?")

    info("Choose how the pipeline finds your repo(s):")
    info("  • [bold]Local directory[/bold] — one repo, already cloned on this machine")
    info("  • [bold]Parent directory[/bold] — multiple repos as subdirectories")
    info("  • [bold]Clone from URL[/bold] — provide git URL(s), we clone them for you")
    console.print()

    mode = questionary.select(
        "Where is your code?",
        choices=REPO_MODES,
        default=p.get("mode", "dir"),
        style=STYLE,
    ).ask()

    repo = {"mode": mode}

    if mode == "dir":
        path = questionary.path("Repo path:", only_directories=True,
                                default=p.get("path", ""), style=STYLE).ask()
        if path:
            with console.status("  Validating directory...", spinner="dots"):
                resolved = Path(path).expanduser().resolve()
                is_git = (resolved / ".git").exists() if resolved.exists() else False
            if resolved.exists():
                success(f"Directory found: {resolved}")
                if is_git:
                    success("Git repo detected")
                else:
                    warn("Not a git repo — agents may not work correctly")
            else:
                warn(f"Directory does not exist yet: {resolved}")
                info("Create it or clone a repo there before running the pipeline")
            repo["path"] = str(resolved)

    elif mode == "parentDir":
        path = questionary.path("Parent directory:", only_directories=True,
                                default=p.get("path", ""), style=STYLE).ask()
        if path:
            with console.status("  Scanning directories...", spinner="dots"):
                resolved = Path(path).expanduser().resolve()
                subdirs = []
                if resolved.exists():
                    subdirs = [d.name for d in sorted(resolved.iterdir()) if d.is_dir() and not d.name.startswith(".")]
            if resolved.exists():
                if subdirs:
                    success(f"Found {len(subdirs)} repos: {', '.join(subdirs[:8])}")
                    if len(subdirs) > 8:
                        info(f"  ...and {len(subdirs) - 8} more")
                else:
                    warn("No subdirectories found — is this the right path?")
            else:
                warn(f"Directory does not exist: {resolved}")
            repo["path"] = str(resolved)

    elif mode == "clone":
        info("Enter one or more git URLs (comma-separated)")
        info("Example: https://github.com/org/repo.git, https://github.com/org/other.git")
        console.print()
        urls_raw = questionary.text("Git URL(s):", style=STYLE).ask()
        urls = [u.strip() for u in urls_raw.split(",") if u.strip()]
        if not urls:
            error("No URLs provided")
        else:
            success(f"{len(urls)} URL(s) configured")
            for u in urls:
                info(f"  → {u}")

        clone_dir = questionary.text("Clone directory:", default="/tmp/auto-pilot-repos", style=STYLE).ask()
        repo["urls"] = urls
        repo["cloneDir"] = clone_dir

    console.print()
    info("The base branch is where feature branches are created from.")
    info("Typically 'main', 'master', or 'develop'.")
    base_branch = questionary.text("Base branch:", default=p.get("baseBranch", "main"), style=STYLE).ask()
    repo["baseBranch"] = base_branch

    return repo


def ask_issue_tracker(total_steps: int, prev: dict | None = None, prev_env: dict | None = None) -> tuple:
    """Step 2: Which issue tracker + integration method?

    Returns:
        Tuple of (tracker_config dict, env_vars dict).
    """
    p = (prev or {}).get("issueTracker", {})
    pe = prev_env or {}
    step(2, total_steps, "Issue Tracker",
         "Where do your tickets/issues live? Choose the platform and how the pipeline talks to it.")

    info("Two integration methods:")
    info("  [bold]CLI MCP[/bold]  — agent reads/writes tickets through MCP tools in your AI CLI")
    info("  [bold]Built-in API[/bold] — Python server calls the REST API directly (no MCP needed for issue tracking)")
    console.print()

    # Map old config values to new ones for backward compat
    prev_type = p.get("type", "jira-mcp")
    if prev_type == "jira":
        prev_type = "jira-mcp"
    elif prev_type == "github-issues":
        prev_type = "github-mcp"

    tracker_type = questionary.select(
        "Issue tracker:",
        choices=ISSUE_TRACKERS,
        default=prev_type,
        style=STYLE,
    ).ask()

    config = {"type": tracker_type}
    env_vars = {}
    defaults = ISSUE_TRACKER_DEFAULTS[tracker_type]

    is_mcp = tracker_type.endswith("-mcp")
    is_jira = tracker_type.startswith("jira")

    if is_mcp:
        console.print()
        platform = "Jira" if is_jira else "GitHub Issues"
        info(f"[cyan]{platform} MCP[/cyan] must be configured in your AI CLI separately.")
        info("See [cyan]docs/prerequisites.md[/cyan] for setup instructions.")
    else:
        console.print()
        info("The Python server will call the REST API directly.")
        info("API credentials are needed — they'll be saved to [cyan].env[/cyan].")
        console.print()
        # Ask for API credentials
        for var_def in ISSUE_TRACKER_ENV.get(tracker_type, []):
            prev_val = pe.get(var_def["key"], var_def["default"])
            if var_def["secret"]:
                hint = f" (current: {prev_val[:4]}****)" if prev_val else ""
                value = questionary.password(f"{var_def['label']}{hint}:", style=STYLE).ask()
                if not value and prev_val:
                    value = prev_val
                    info(f"  Keeping existing {var_def['key']}")
                elif value:
                    success(f"{var_def['key']} set (masked)")
                else:
                    error(f"{var_def['key']} is empty — issue tracker API calls will fail")
            else:
                value = questionary.text(f"{var_def['label']}:", default=prev_val, style=STYLE).ask()
            env_vars[var_def["key"]] = value

    console.print()
    config["triggerStatus"] = questionary.text(
        f"{defaults['trigger_label']} (starts the pipeline):",
        default=p.get("triggerStatus", defaults["trigger_default"]), style=STYLE
    ).ask()

    console.print()
    info("When the pipeline picks up a ticket, it transitions to this status.")
    info("This shows the team that AI agents are actively working on it.")
    config["developmentStatus"] = questionary.text(
        f"{defaults['development_label']} (while agents are working):",
        default=p.get("developmentStatus", defaults["development_default"]), style=STYLE
    ).ask()

    config["doneStatus"] = questionary.text(
        f"{defaults['done_label']} (after MR created):",
        default=p.get("doneStatus", defaults["done_default"]), style=STYLE
    ).ask()

    console.print()
    info("When a ticket lacks enough detail to proceed, the pipeline blocks it.")
    config["blockedStatus"] = questionary.text(
        f"{defaults['blocked_label']} (insufficient details):",
        default=p.get("blockedStatus", defaults["blocked_default"]), style=STYLE
    ).ask()

    return config, env_vars


def ask_git_provider(total_steps: int, prev: dict | None = None, prev_env: dict | None = None) -> tuple[dict, dict]:
    """Step 3: Git provider + API tokens."""
    p = (prev or {}).get("gitProvider", {})
    pe = prev_env or {}
    step(3, total_steps, "Git Provider + Tokens",
         "Where is your git remote? We need API tokens to create branches, PRs, and commit code.")

    info("Only your API [bold]token[/bold] is needed — project IDs and owner/repo")
    info("are [bold]auto-detected[/bold] from each repo's git remote URL at runtime.")
    info("Tokens are stored in [cyan].env[/cyan] (never committed to git).")
    console.print()

    provider_type = questionary.select(
        "Git provider:",
        choices=GIT_PROVIDERS,
        default=p.get("type", "gitlab"),
        style=STYLE,
    ).ask()

    config = {"type": provider_type}
    env_vars = {}

    # Show where to get tokens
    if provider_type == "gitlab":
        console.print()
        info("How to get a GitLab token:")
        info("  1. Go to GitLab → Settings → Access Tokens")
        info("  2. Create a token with [bold]api[/bold] scope")
        info("  3. Copy the token — that's all you need")
        info("  [dim]Project IDs are auto-detected from git remote URLs[/dim]")
        console.print()
    elif provider_type == "github":
        console.print()
        info("How to get a GitHub token:")
        info("  1. Go to GitHub → Settings → Developer Settings → Personal Access Tokens")
        info("  2. Create a fine-grained token with: Contents (R/W), Pull Requests (R/W)")
        info("  3. Copy the token — that's all you need")
        info("  [dim]Owner and repo name are auto-detected from git remote URLs[/dim]")
        console.print()

    for var_def in GIT_PROVIDER_ENV[provider_type]:
        prev_val = pe.get(var_def["key"], var_def["default"])
        if var_def["secret"]:
            hint = f" (current: {prev_val[:4]}****)" if prev_val else ""
            value = questionary.password(f"{var_def['label']}{hint}:", style=STYLE).ask()
            # Keep previous value if user just pressed Enter on password
            if not value and prev_val:
                value = prev_val
                info(f"  Keeping existing {var_def['key']}")
            elif value:
                success(f"{var_def['key']} set (masked)")
            else:
                error(f"{var_def['key']} is empty — the pipeline won't work without it")
        else:
            value = questionary.text(f"{var_def['label']}:", default=prev_val, style=STYLE).ask()
        env_vars[var_def["key"]] = value

    console.print()
    info("Bot usernames are filtered out from PR/MR comments (they're not human feedback)")
    prev_bots = ", ".join(p.get("botUsers", [])) if p.get("botUsers") else GIT_PROVIDER_BOTS[provider_type]
    bot_users = questionary.text(
        "Bot usernames to ignore (comma-separated):",
        default=prev_bots, style=STYLE
    ).ask()
    config["botUsers"] = [u.strip() for u in bot_users.split(",") if u.strip()]

    return config, env_vars


def ask_cli_adapter(total_steps: int, prev: dict | None = None) -> dict:
    """Step 4: Which AI coding CLI?"""
    p = (prev or {}).get("cliAdapter", {})
    step(4, total_steps, "AI Coding CLI",
         "Which AI coding tool should run the agents? It must be installed on this machine.")

    info("The pipeline spawns this CLI to run each agent (orchestrator, brainstorm, developer, etc.)")
    console.print()

    cli_type = questionary.select(
        "AI coding CLI:",
        choices=CLI_ADAPTERS,
        default=p.get("type", "claude-code"),
        style=STYLE,
    ).ask()

    # Check if the selected CLI is installed
    cmd_map = {"claude-code": "claude", "codex": "codex", "gemini": "gemini"}
    cmd = cmd_map.get(cli_type, cli_type)
    if shutil.which(cmd):
        success(f"{cmd} is installed ✓")
    else:
        error(f"'{cmd}' command not found on this machine")
        info(f"Install it before running the pipeline, or the agents will fail to start")
        if cli_type == "claude-code":
            info("  Install: https://docs.anthropic.com/en/docs/claude-code")
        elif cli_type == "codex":
            info("  Install: npm install -g @openai/codex")
        elif cli_type == "gemini":
            info("  Install: https://github.com/google-gemini/gemini-cli")

    config = {"type": cli_type}

    console.print()
    info("Optional: specify a model name (e.g. claude-sonnet-4-6, codex-mini)")
    info("Press Enter to use the CLI's default model.")
    model = questionary.text(
        "Model name (optional):",
        default=p.get("model", ""), style=STYLE
    ).ask()
    if model:
        config["model"] = model

    return config


def ask_notification(total_steps: int, prev: dict | None = None) -> dict | None:
    """Step 5: Notifications (optional)."""
    p = (prev or {}).get("notification", {}) or {}
    step(5, total_steps, "Notifications (optional)",
         "Get notified on Slack (or other channels) when PRs are created, merged, or need attention.")

    info("Notifications are [bold]optional[/bold]. Skip this if you don't need them.")
    console.print()

    enable = questionary.confirm("Enable notifications?", default=bool(p), style=STYLE).ask()
    if not enable:
        info("Notifications disabled — you can enable them later in config.yaml")
        return None

    notif_type = questionary.select(
        "Notification provider:",
        choices=NOTIFICATION_PROVIDERS,
        style=STYLE,
    ).ask()

    if notif_type == "slack":
        info("Slack MCP server must be configured in your AI CLI separately.")
        info("See docs/prerequisites.md for setup instructions.")
        console.print()

    channel = questionary.text("Channel name:", default=p.get("channel", "dev-team"), style=STYLE).ask()

    return {"type": notif_type, "channel": channel}


def ask_pipeline(total_steps: int, prev: dict | None = None) -> dict:
    """Step 6: Pipeline runtime settings."""
    p = (prev or {}).get("pipeline", {})
    step(6, total_steps, "Pipeline Settings",
         "Configure the webhook server port, rework limits, agent timeouts, and output visibility.")

    info("The webhook server listens for events from your issue tracker and git provider.")
    port = questionary.text("Server port:", default=str(p.get("port", PIPELINE_DEFAULTS["port"])), style=STYLE).ask()

    console.print()
    info("If a reviewer keeps requesting changes, the pipeline caps at a max number of rework cycles.")
    info("After this limit, it sends an escalation notification instead of reworking again.")
    max_rework = questionary.text("Max rework iterations:", default=str(p.get("maxReworkIterations", PIPELINE_DEFAULTS["max_rework"])), style=STYLE).ask()

    console.print()
    info("How long an agent process can run before being killed (in seconds).")
    info("Complex tickets may need more time. Default is 5 minutes (300s).")
    prev_timeout = str(p.get("agentTimeout", 300000) // 1000) if p.get("agentTimeout") else PIPELINE_DEFAULTS["timeout_seconds"]
    timeout = questionary.text("Agent timeout (seconds):", default=prev_timeout, style=STYLE).ask()

    console.print()
    info("Output handlers control where you can see what agents are doing in real-time.")
    info("  • [bold]File[/bold] — writes to logs/agents/ (use [cyan]tail -f[/cyan] to watch)")
    info("  • [bold]Memory[/bold] — serves via API ([cyan]/api/status/{'{key}'}/logs[/cyan])")
    info("Select one or both:")

    # Build checkbox choices with pre-checked state from prev config
    prev_handlers = p.get("outputHandlers", PIPELINE_DEFAULTS["output_handlers"])
    handler_choices = [
        questionary.Choice(c.title, value=c.value, checked=(c.value in prev_handlers))
        for c in OUTPUT_HANDLERS
    ]
    output_handlers = questionary.checkbox(
        "Output handlers:",
        choices=handler_choices,
        style=STYLE,
    ).ask()

    if not output_handlers:
        warn("No output handlers selected — you won't see agent output anywhere")
        output_handlers = []

    console.print()
    info("Your AI CLI may have skills/plugins installed (e.g. brainstorming, TDD, code-review).")
    info("By default, pipeline agents [bold]ignore[/bold] all skills to avoid interference.")
    info("Enable this only if you have custom skills designed for automated pipelines.")
    allow_skills = questionary.confirm(
        "Allow agents to use CLI skills/plugins?",
        default=p.get("allowCliSkills", False),
        style=STYLE,
    ).ask()

    return {
        "port": int(port),
        "maxReworkIterations": int(max_rework),
        "agentTimeout": int(timeout) * 1000,
        "outputHandlers": output_handlers,
        "allowCliSkills": allow_skills,
    }


def show_summary(config: dict, env_vars: dict, total_steps: int):
    """Step 7: Show everything and confirm."""
    step(7, total_steps, "Review & Confirm",
         "Please review your configuration before we write the files.")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan", min_width=20)
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

    tt = config["issueTracker"]["type"]
    table.add_row("Issue tracker", f"{tt} ({'agent via MCP' if tt.endswith('-mcp') else 'built-in REST API'})")
    table.add_row("Trigger", config["issueTracker"].get("triggerStatus", ""))
    table.add_row("Development", config["issueTracker"].get("developmentStatus", ""))
    table.add_row("Done status", config["issueTracker"].get("doneStatus", ""))
    table.add_row("Blocked status", config["issueTracker"].get("blockedStatus", ""))
    table.add_row("", "")

    table.add_row("Git provider", config["gitProvider"]["type"])
    table.add_row("CLI adapter", config["cliAdapter"]["type"])
    if config["cliAdapter"].get("model"):
        table.add_row("Model", config["cliAdapter"]["model"])
    table.add_row("", "")

    if config.get("notification"):
        table.add_row("Notifications", f"{config['notification']['type']} → #{config['notification'].get('channel', '')}")
    else:
        table.add_row("Notifications", "[dim]disabled[/dim]")

    table.add_row("", "")
    table.add_row("Port", str(config["pipeline"]["port"]))
    table.add_row("Max rework", str(config["pipeline"]["maxReworkIterations"]))
    table.add_row("Agent timeout", f"{config['pipeline']['agentTimeout'] // 1000}s")

    table.add_row("", "")
    for key, val in env_vars.items():
        display = val[:4] + "****" if ("TOKEN" in key or "token" in key.lower()) and len(val) > 4 else val
        table.add_row(f".env → {key}", display)

    console.print(Panel(table, title="[bold]Configuration Summary[/bold]", border_style="green"))
    console.print()


def write_config(config: dict):
    """Write config.yaml."""
    yaml_config = {}
    yaml_config["repo"] = dict(config["repo"])
    yaml_config["issueTracker"] = config["issueTracker"]
    yaml_config["gitProvider"] = config["gitProvider"]

    cli = dict(config["cliAdapter"])
    yaml_config["cliAdapter"] = {"type": cli["type"]}
    if cli.get("model"):
        yaml_config["cliAdapter"]["model"] = cli["model"]

    if config.get("notification"):
        yaml_config["notification"] = config["notification"]

    yaml_config["pipeline"] = config["pipeline"]

    CONFIG_PATH.write_text(yaml.dump(yaml_config, default_flow_style=False, sort_keys=False))
    success("config.yaml written")


def write_env(env_vars: dict):
    """Write .env file."""
    lines = ["# Auto-generated by Auto Developer setup wizard\n"]
    for key, val in env_vars.items():
        lines.append(f"{key}={val}\n")
    ENV_PATH.write_text("".join(lines))
    success(".env written (contains your tokens — never commit this file)")


def load_previous() -> tuple[dict | None, dict]:
    """Load existing config.yaml and .env as defaults for reconfiguration.

    Returns:
        Tuple of (prev_config or None, prev_env dict).
    """
    prev_config = None
    prev_env = {}

    if CONFIG_PATH.exists():
        try:
            prev_config = yaml.safe_load(CONFIG_PATH.read_text())
        except Exception:
            pass

    if ENV_PATH.exists():
        try:
            for line in ENV_PATH.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    prev_env[key.strip()] = val.strip()
        except Exception:
            pass

    return prev_config, prev_env


# ─── Main ─────────────────────────────────────────────

def main():
    """Run the setup wizard."""
    banner()

    # Pre-flight checks
    check_prerequisites()

    # Check for existing config — offer reconfigure with pre-filled defaults
    prev = None
    prev_env = {}

    if CONFIG_PATH.exists():
        info("config.yaml already exists from a previous setup.\n")
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("Re-link agent files only (keep current config)", value="relink"),
                questionary.Choice("Reconfigure (edit current settings)", value="reconfig"),
                questionary.Choice("Start fresh (blank config)", value="fresh"),
            ],
            style=STYLE,
        ).ask()

        if action == "relink":
            info("Keeping existing config. Re-linking agent files...\n")
            config = yaml.safe_load(CONFIG_PATH.read_text())
            link_agents(config)
            console.print()
            console.print(Panel.fit(
                "[green]Agent files linked.[/green]\n\n"
                "Next: [cyan]./start.sh[/cyan] to start the pipeline",
                border_style="green",
            ))
            console.print()
            return

        if action == "reconfig":
            prev, prev_env = load_previous()
            info("Current values shown as defaults — press Enter to keep, or type to change.\n")
        else:
            # fresh start
            backup = CONFIG_PATH.with_suffix(".yaml.bak")
            CONFIG_PATH.rename(backup)
            info(f"Old config backed up to {backup.name}\n")

    total_steps = 7

    # Collect all config — pass prev values as defaults
    repo_config = ask_repo(total_steps, prev)
    tracker_config, tracker_env = ask_issue_tracker(total_steps, prev, prev_env)
    git_config, git_env = ask_git_provider(total_steps, prev, prev_env)
    env_vars = {**tracker_env, **git_env}  # merge all env vars
    cli_config = ask_cli_adapter(total_steps, prev)
    notif_config = ask_notification(total_steps, prev)
    pipeline_config = ask_pipeline(total_steps, prev)

    # Assemble
    full_config = {
        "repo": repo_config,
        "issueTracker": tracker_config,
        "gitProvider": git_config,
        "cliAdapter": cli_config,
        "pipeline": pipeline_config,
    }
    if notif_config:
        full_config["notification"] = notif_config

    # Summary
    show_summary(full_config, env_vars, total_steps)

    proceed = questionary.confirm("Write config and proceed?", default=True, style=STYLE).ask()
    if not proceed:
        warn("Setup cancelled. No files were written.")
        console.print()
        return

    # Write files
    console.print()
    with console.status("  Writing configuration files...", spinner="dots"):
        write_config(full_config)
        write_env(env_vars)

    # Symlink agents
    console.print()
    info("Linking agent files into your repos...\n")
    link_agents(full_config)

    # Done — show next steps
    console.print()

    # ─── MCP Servers Panel ────────────────────────────────
    # Show a dedicated panel FIRST so the user sees what they need to configure
    cmd_map = {"claude-code": "claude", "codex": "codex", "gemini": "gemini"}
    cli_cmd = cmd_map.get(cli_config["type"], "claude")
    git_label = "GitLab" if git_config["type"] == "gitlab" else "GitHub"
    pr_label = "MRs" if git_config["type"] == "gitlab" else "PRs"

    tracker_type = tracker_config["type"]
    is_tracker_mcp = tracker_type.endswith("-mcp")
    is_jira = tracker_type.startswith("jira")
    tracker_platform = "Jira" if is_jira else "GitHub Issues"

    # ─── Integration Table ─────────────────────────────────
    int_table = Table(
        title="Integrations for Your Config",
        show_header=True, header_style="bold cyan",
        border_style="cyan", expand=True,
        title_style="bold white",
        padding=(0, 2),
    )
    int_table.add_column("Integration", style="bold", min_width=18)
    int_table.add_column("Method", justify="center", min_width=12)
    int_table.add_column("Purpose", min_width=24)
    int_table.add_column("Action Required", min_width=28)

    # Git provider MCP — always built-in
    int_table.add_row(
        f"{git_label} MCP",
        "[green]Built-in[/green]",
        f"Branches, commits, {pr_label}",
        "[dim]Auto-configured by start.sh[/dim]",
    )
    int_table.add_row("", "", "", "")  # spacer

    # Issue tracker
    if is_tracker_mcp:
        int_table.add_row(
            f"{tracker_platform} MCP",
            "[yellow]CLI MCP[/yellow]",
            "Read tickets, comments, transitions",
            f"[yellow]Configure in {cli_config['type']} CLI[/yellow]\nSee docs/prerequisites.md",
        )
    else:
        int_table.add_row(
            f"{tracker_platform} API",
            "[green]Built-in[/green]",
            "Read tickets, comments, transitions",
            "[dim]Credentials saved to .env[/dim]",
        )
    int_table.add_row("", "", "", "")  # spacer

    # Slack — only if notifications enabled
    if notif_config:
        int_table.add_row(
            "Slack MCP",
            "[yellow]CLI MCP[/yellow]",
            f"Notifications → #{notif_config.get('channel', 'general')}",
            f"[yellow]Configure in {cli_config['type']} CLI[/yellow]\nSee docs/prerequisites.md",
        )

    console.print()
    console.print(Panel(int_table, border_style="cyan"))

    # ─── Next Steps Panel ────────────────────────────────
    step_num = 1
    next_steps = []

    if not shutil.which(cli_cmd):
        next_steps.append(f"  {step_num}. [yellow]Install {cli_config['type']}[/yellow] — '{cli_cmd}' not found")
        step_num += 1

    # Only show MCP setup steps for MCP-mode integrations
    if is_tracker_mcp:
        next_steps.append(f"  {step_num}. Configure [cyan]{tracker_platform} MCP[/cyan] in your CLI  [dim](see table above)[/dim]")
        step_num += 1
    if notif_config:
        next_steps.append(f"  {step_num}. Configure [cyan]Slack MCP[/cyan] in your CLI  [dim](see table above)[/dim]")
        step_num += 1

    next_steps.append(f"  {step_num}. Run [cyan]./start.sh[/cyan] to start the pipeline")
    step_num += 1

    # Git MCP note
    next_steps.append(f"     [dim]{git_label} MCP is built-in and auto-configured by start.sh[/dim]")

    next_steps.extend([
        "",
        f"  {step_num}. Configure webhooks:",
        f"     Issue tracker:  [cyan]http://<your-host>:{pipeline_config['port']}/webhooks/issue-tracker[/cyan]",
        f"     Git provider:   [cyan]http://<your-host>:{pipeline_config['port']}/webhooks/git[/cyan]",
        "",
        "  Or trigger manually:",
        f"    curl -X POST http://localhost:{pipeline_config['port']}/api/trigger \\",
        "      -H 'Content-Type: application/json' \\",
        "      -d '{\"issueKey\": \"PROJ-1\"}'",
    ])

    console.print(Panel(
        "\n".join(next_steps),
        title="[bold green]Setup Complete — Next Steps[/bold green]",
        border_style="green",
    ))

    # ─── Optional Console Panel ────────────────────────
    console_lines = [
        "[dim]A web console to monitor pipelines, view logs, and trigger runs.[/dim]",
        "",
        "  [cyan]cd console[/cyan]",
        "  [cyan]npm install[/cyan]        [dim]# first time only[/dim]",
        "  [cyan]npm run dev[/cyan]        [dim]# starts on http://localhost:3001[/dim]",
        "",
        f"  [dim]Connects to the API server on port {pipeline_config['port']}.[/dim]",
        "  [dim]Requires Node.js >= 18. Install: https://nodejs.org[/dim]",
    ]

    console.print(Panel(
        "\n".join(console_lines),
        title="[bold cyan]Optional — Web Console[/bold cyan]",
        subtitle="[dim]skip this if you prefer CLI / API only[/dim]",
        border_style="dim cyan",
    ))
    console.print()


if __name__ == "__main__":
    main()
