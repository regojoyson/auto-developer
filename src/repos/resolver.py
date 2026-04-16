"""
Repo directory resolver.

Resolves which directory to run agents in, based on the repo mode
configured in config.yaml. Also handles git operations to prepare
the repo before each new ticket (stash, checkout baseBranch, reset).

Three modes:
    - dir:       One local repo directory
    - parentDir: Parent directory where each subdirectory is a repo
    - clone:     One or more git URLs, cloned on first use

Usage:
    from src.repos.resolver import get_repo_dir, prepare_repo, get_base_branch

    repo = get_repo_dir("frontend-app")  # or get_repo_dir() for default
    prepare_repo(repo)                    # stash + checkout baseBranch + pull
    branch = get_base_branch()            # "main" or whatever is configured
"""

import logging
import subprocess
from pathlib import Path

from src.config import config

logger = logging.getLogger(__name__)


def get_repo_dir(component: str | None = None) -> str:
    """Resolve the repo directory for the given component.

    Args:
        component: Subdirectory or repo name. Used in parentDir and
            clone modes to select which repo. Ignored in dir mode.

    Returns:
        Absolute path to the repo directory.

    Raises:
        ValueError: If the repo mode is unknown.
    """
    mode = config["repo"]["mode"]

    if mode == "dir":
        return config["repo"]["path"]

    if mode == "parentDir":
        base = config["repo"]["path"]
        if not component:
            return base
        return str(Path(base) / component)

    if mode == "clone":
        clone_dir = Path(config["repo"]["clone_dir"])
        clone_dir.mkdir(parents=True, exist_ok=True)

        # Clone all URLs that haven't been cloned yet
        for url in config["repo"]["urls"]:
            repo_name = Path(url).stem  # strip .git
            target = clone_dir / repo_name
            if not target.exists():
                logger.info(f"Cloning {url} into {target}")
                subprocess.run(["git", "clone", url, str(target)], check=True)

        urls = config["repo"]["urls"]
        if len(urls) == 1:
            return str(clone_dir / Path(urls[0]).stem)

        if component:
            return str(clone_dir / component)
        return str(clone_dir)

    raise ValueError(f"Unknown repo mode: '{mode}'. Supported: dir, parentDir, clone")


def get_base_branch() -> str:
    """Get the configured base branch name (e.g. 'main', 'develop').

    Returns:
        Branch name string from config.yaml repo.baseBranch.
    """
    return config["repo"]["base_branch"]


def prepare_repo(repo_dir: str) -> None:
    """Prepare a repo for a new ticket.

    Ensures the local repo is clean and on the latest base branch:
    1. git stash --include-untracked (save any leftover changes)
    2. git checkout <baseBranch>
    3. git fetch origin
    4. git reset --hard origin/<baseBranch>

    This prevents checkout failures from leftover agent work or
    diverged local branches.

    Args:
        repo_dir: Absolute path to the repo directory.
    """
    base = get_base_branch()
    logger.info(f"Preparing repo: stash, checkout {base}, reset to origin", extra={"repo_dir": repo_dir})

    def run(cmd):
        """Run a git command, return stdout or None on failure."""
        try:
            return subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True).stdout.strip()
        except Exception:
            return None

    # 1. Stash any uncommitted changes
    result = run(["git", "stash", "--include-untracked"])
    if result and "No local changes" not in result:
        logger.info("Stashed uncommitted changes")

    # 2. Checkout base branch
    if run(["git", "checkout", base]) is None:
        logger.warning(f"Failed to checkout {base}")
        return

    # 3. Fetch latest from origin
    run(["git", "fetch", "origin"])

    # 4. Reset local branch to match origin
    if run(["git", "reset", "--hard", f"origin/{base}"]) is None:
        run(["git", "pull"])  # fallback if reset fails

    logger.info(f"Repo ready on {base}")


def list_repos() -> list[str]:
    """List all repo directories based on the configured mode.

    Returns:
        List of absolute path strings to repo directories.
    """
    mode = config["repo"]["mode"]

    if mode == "dir":
        return [config["repo"]["path"]]

    if mode == "parentDir":
        base = Path(config["repo"]["path"])
        if not base.exists():
            return []
        return [str(d) for d in sorted(base.iterdir()) if d.is_dir() and not d.name.startswith(".")]

    if mode == "clone":
        clone_dir = Path(config["repo"]["clone_dir"])
        return [str(clone_dir / Path(url).stem) for url in config["repo"]["urls"]]

    return []
