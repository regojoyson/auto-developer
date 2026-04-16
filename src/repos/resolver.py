"""Repo directory resolver — 3 modes (dir, parentDir, clone) + baseBranch."""

import logging
import subprocess
from pathlib import Path

from src.config import config

logger = logging.getLogger(__name__)


def get_repo_dir(component: str | None = None) -> str:
    """Resolve the repo directory for the given component."""
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
    return config["repo"]["base_branch"]


def prepare_repo(repo_dir: str) -> None:
    """Stash changes, checkout baseBranch, reset to origin."""
    base = get_base_branch()
    logger.info(f"Preparing repo: stash, checkout {base}, reset to origin", extra={"repo_dir": repo_dir})

    def run(cmd):
        try:
            return subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True).stdout.strip()
        except Exception:
            return None

    result = run(["git", "stash", "--include-untracked"])
    if result and "No local changes" not in result:
        logger.info("Stashed uncommitted changes")

    if run(["git", "checkout", base]) is None:
        logger.warning(f"Failed to checkout {base}")
        return

    run(["git", "fetch", "origin"])

    if run(["git", "reset", "--hard", f"origin/{base}"]) is None:
        run(["git", "pull"])

    logger.info(f"Repo ready on {base}")


def list_repos() -> list[str]:
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
