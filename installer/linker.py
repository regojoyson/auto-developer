"""Symlink agent files into target repos based on CLI adapter config."""

import os
import sys
from pathlib import Path

from rich.console import Console

console = Console()
PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"


def get_cli_dirs(cli_type: str) -> dict:
    """Return agent_dir, config_dir, rules_file_name for a CLI type."""
    mapping = {
        "claude-code": {"agent_dir": ".claude/agents", "config_dir": ".claude", "rules_file": "CLAUDE.md"},
        "codex": {"agent_dir": ".codex/agents", "config_dir": ".codex", "rules_file": "AGENTS.md"},
        "gemini": {"agent_dir": ".gemini/agents", "config_dir": ".gemini", "rules_file": "GEMINI.md"},
    }
    return mapping.get(cli_type, mapping["claude-code"])


def resolve_repo_dirs(config: dict) -> list[str]:
    """Get list of repo directories from config."""
    mode = config["repo"]["mode"]

    if mode == "dir":
        return [config["repo"]["path"]]

    if mode == "parentDir":
        parent = Path(config["repo"]["path"])
        if not parent.exists():
            return []
        return [str(d) for d in sorted(parent.iterdir()) if d.is_dir() and not d.name.startswith(".")]

    if mode == "clone":
        clone_dir = config["repo"].get("cloneDir", "/tmp/auto-pilot-repos")
        urls = config["repo"].get("urls", [])
        return [str(Path(clone_dir) / Path(url).stem) for url in urls]

    return []


def link_agents(config: dict) -> None:
    """Symlink agent .md files + RULES.md into target repos."""
    cli_type = config.get("cliAdapter", {}).get("type", "claude-code")
    dirs = get_cli_dirs(cli_type)
    repo_dirs = resolve_repo_dirs(config)

    if not repo_dirs:
        console.print("  [yellow]No repo directories found — check config.yaml[/yellow]")
        return

    console.print(f"  CLI agent dir: [cyan]{dirs['agent_dir']}[/cyan]")
    console.print(f"  Linking agent files into repos...\n")

    for repo_path in repo_dirs:
        repo = Path(repo_path)
        repo_name = repo.name

        if not repo.exists():
            console.print(f"  [yellow]![/yellow] {repo_name} — directory does not exist yet")
            continue

        # 1. Symlink .auto-developer/
        ad_link = repo / ".auto-developer"
        if ad_link.is_symlink():
            console.print(f"  [green]+[/green] {repo_name} — .auto-developer/ already linked")
        elif not ad_link.exists():
            ad_link.symlink_to(AGENTS_DIR)
            console.print(f"  [green]+[/green] {repo_name} — linked .auto-developer/")

        # 2. Create CLI agent dir
        agent_dir = repo / dirs["agent_dir"]
        agent_dir.mkdir(parents=True, exist_ok=True)

        # 3. Symlink each agent .md file
        for agent_file in AGENTS_DIR.glob("*.md"):
            if agent_file.name == "RULES.md":
                continue
            target = agent_dir / agent_file.name
            if target.is_symlink():
                console.print(f"  [green]+[/green] {repo_name} — {agent_file.name} already linked")
            elif target.exists():
                console.print(f"  [yellow]![/yellow] {repo_name} — {agent_file.name} already exists (skipped)")
            else:
                target.symlink_to(agent_file)
                console.print(f"  [green]+[/green] {repo_name} — linked {agent_file.name}")

        # 4. Symlink RULES.md as CLI-specific filename
        config_dir = repo / dirs["config_dir"]
        config_dir.mkdir(parents=True, exist_ok=True)
        rules_target = config_dir / dirs["rules_file"]
        rules_src = AGENTS_DIR / "RULES.md"

        if rules_target.is_symlink():
            console.print(f"  [green]+[/green] {repo_name} — {dirs['rules_file']} already linked")
        elif rules_target.exists():
            console.print(f"  [yellow]![/yellow] {repo_name} — {dirs['rules_file']} already exists (skipped)")
        else:
            rules_target.symlink_to(rules_src)
            console.print(f"  [green]+[/green] {repo_name} — linked RULES.md as {dirs['rules_file']}")
