"""Factory for loading the configured CLI adapter.

Reads the ``cli_adapter.type`` field from the application configuration and
lazily imports the corresponding adapter module (Claude Code, Codex, or
Gemini). The adapter instance is cached as a module-level singleton so
subsequent calls return the same object without re-importing.

Usage::

    adapter, cli_config = get_cli_adapter()
    args = adapter.build_args("orchestrator", input_json, cli_config)
"""

from src.config import config

_instance = None


def get_cli_adapter():
    """Return the CLI adapter and its configuration.

    On first call, reads ``config["cli_adapter"]["type"]`` to determine
    which adapter to load, imports the corresponding module, and caches the
    result. Subsequent calls return the cached instance immediately.

    Returns:
        tuple: A 2-tuple of ``(adapter, cli_config)`` where *adapter* is
            a :class:`~src.providers.base.CliAdapterBase` instance and
            *cli_config* is the ``cli_adapter`` section of config.yaml.

    Raises:
        ValueError: If the configured adapter type is not one of the
            supported values (``claude-code``, ``codex``, ``gemini``).
    """
    global _instance
    if _instance:
        return _instance

    cli_config = config["cli_adapter"]
    adapter_type = cli_config["type"]

    if adapter_type == "claude-code":
        from src.providers.cli.claude_code import adapter
    elif adapter_type == "codex":
        from src.providers.cli.codex import adapter
    elif adapter_type == "gemini":
        from src.providers.cli.gemini import adapter
    else:
        raise ValueError(f"Unknown CLI adapter: '{adapter_type}'. Supported: claude-code, codex, gemini")

    _instance = (adapter, cli_config)
    return _instance
