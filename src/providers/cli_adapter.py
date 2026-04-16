"""Factory — loads the configured CLI adapter."""

from src.config import config

_instance = None


def get_cli_adapter():
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
