"""Symlink agent files into target repositories.

After the setup wizard generates ``config.yaml``, this module creates the
necessary directory structure and symlinks in each target repository so the
chosen AI CLI (Claude Code, Codex, or Gemini) can discover the agent
definition files and rules.

For each target repo, the linker:

1. Symlinks ``.auto-developer/`` to the shared ``agents/`` directory.
2. Creates the CLI-specific agent directory (e.g. ``.claude/agents/``).
3. Symlinks each agent ``.md`` file into the agent directory.
4. Symlinks ``RULES.md`` as the CLI-specific rules file (e.g. ``CLAUDE.md``).

Usage::

    from installer.linker import link_agents
    link_agents(config)
"""

import os
import sys
from pathlib import Path

from rich.console import Console

console = Console()
PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"


def get_cli_dirs(cli_type: str) -> dict:
    """Return the directory layout for a given CLI adapter type.

    Args:
        cli_type: One of ``"claude-code"``, ``"codex"``, or ``"gemini"``.

    Returns:
        dict: A dict with keys ``agent_dir`` (relative path where the CLI
            looks for agent files), ``config_dir`` (CLI config directory),
            and ``rules_file`` (filename for the global rules file).
            Defaults to Claude Code layout for unknown types.
    """
    mapping = {
        "claude-code": {"agent_dir": ".claude/agents", "config_dir": ".claude", "rules_file": "CLAUDE.md"},
        "codex": {"agent_dir": ".codex/agents", "config_dir": ".codex", "rules_file": "AGENTS.md"},
        "gemini": {"agent_dir": ".gemini/agents", "config_dir": ".gemini", "rules_file": "GEMINI.md"},
    }
    return mapping.get(cli_type, mapping["claude-code"])


def resolve_repo_dirs(config: dict) -> list[str]:
    """Resolve the list of target repository directories from config.

    Supports three repo modes:
    - ``dir``: Returns a single directory path.
    - ``parentDir``: Returns all non-hidden subdirectories.
    - ``clone``: Constructs paths from clone URLs and target directory.

    Args:
        config: The full configuration dict. Must contain a ``repo``
            section with a ``mode`` key.

    Returns:
        list[str]: Absolute paths to each target repository directory.
            May be empty if no directories are found or the mode is
            unrecognized.
    """
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
    """Symlink agent definition files and rules into all target repos.

    For each resolved repository directory, creates the CLI-specific
    agent directory structure and symlinks all agent ``.md`` files plus
    the global rules file. Skips files that already exist as symlinks
    or regular files to avoid overwriting manual customizations.

    Args:
        config: The full configuration dict. Must contain ``cliAdapter``
            (with ``type``) and ``repo`` sections.
    """
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
