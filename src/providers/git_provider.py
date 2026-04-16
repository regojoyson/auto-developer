"""Factory for loading the configured git provider adapter.

Reads the ``git_provider.type`` field from the application configuration and
lazily imports the corresponding adapter module (GitLab or GitHub). The adapter
instance is cached as a module-level singleton so subsequent calls return the
same object without re-importing.

Usage::

    adapter, git_config = get_git_provider()
    parsed = adapter.parse_webhook(headers, payload, git_config)
    api = adapter.create_api(env)
"""

from src.config import config

_instance = None


def get_git_provider():
    """Return the git provider adapter and its configuration.

    On first call, reads ``config["git_provider"]["type"]`` to determine
    which adapter to load, imports the corresponding module, and caches the
    result. Subsequent calls return the cached instance immediately.

    Returns:
        tuple: A 2-tuple of ``(adapter, git_config)`` where *adapter* is
            a :class:`~src.providers.base.GitProviderBase` instance and
            *git_config* is the ``git_provider`` section of config.yaml.

    Raises:
        ValueError: If the configured adapter type is not one of the
            supported values (``gitlab``, ``github``).
    """
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
