"""Factory — loads the configured git provider adapter."""

from src.config import config

_instance = None


def get_git_provider():
    global _instance
    if _instance:
        return _instance

    git_config = config["git_provider"]
    adapter_type = git_config["type"]

    if adapter_type == "gitlab":
        from src.providers.git.gitlab import adapter
    elif adapter_type == "github":
        from src.providers.git.github import adapter
    else:
        raise ValueError(f"Unknown git provider: '{adapter_type}'. Supported: gitlab, github")

    _instance = (adapter, git_config)
    return _instance
