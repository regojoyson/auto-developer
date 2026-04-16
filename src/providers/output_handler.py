"""Output handler registry — fans out agent output to all enabled handlers.

Reads ``pipeline.outputHandlers`` from config.yaml (default: ["file", "memory"])
and loads the matching handler modules. All calls are fanned out to every
enabled handler.

Usage::

    from src.providers.output_handler import get_output_handlers

    handlers = get_output_handlers()
    handlers.on_start("PROJ-42", "orchestrator", "/projects/app")
    handlers.on_output("PROJ-42", "orchestrator", "Reading PLAN.md...", "stdout")
    handlers.on_finish("PROJ-42", "orchestrator", 0)
    print(handlers.get_output("PROJ-42"))
"""

from src.config import config

_instance = None


class OutputHandlerRegistry:
    """Fans out output events to all enabled handlers."""

    def __init__(self, handlers: list):
        self._handlers = handlers

    def on_start(self, issue_key: str, agent_name: str, cwd: str):
        """Notify all handlers that an agent started."""
        for h in self._handlers:
            try:
                h.on_start(issue_key, agent_name, cwd)
            except Exception:
                pass

    def on_output(self, issue_key: str, agent_name: str, line: str, stream: str):
        """Send a line of output to all handlers."""
        for h in self._handlers:
            try:
                h.on_output(issue_key, agent_name, line, stream)
            except Exception:
                pass

    def on_finish(self, issue_key: str, agent_name: str, exit_code: int):
        """Notify all handlers that an agent finished."""
        for h in self._handlers:
            try:
                h.on_finish(issue_key, agent_name, exit_code)
            except Exception:
                pass

    def get_output(self, issue_key: str, agent_name: str | None = None) -> str:
        """Get output from the first handler that has it (typically memory)."""
        for h in self._handlers:
            output = h.get_output(issue_key, agent_name)
            if output:
                return output
        return ""


def get_output_handlers() -> OutputHandlerRegistry:
    """Load and return the output handler registry (cached).

    Reads ``pipeline.outputHandlers`` from config (default: ["file", "memory"]).

    Returns:
        OutputHandlerRegistry with all enabled handlers.
    """
    global _instance
    if _instance:
        return _instance

    handler_names = config.get("pipeline", {}).get("output_handlers", ["file", "memory"])
    handlers = []

    for name in handler_names:
        if name == "file":
            from src.providers.output.file_handler import handler
            handlers.append(handler)
        elif name == "memory":
            from src.providers.output.memory_handler import handler
            handlers.append(handler)
        # Add more handlers here as needed

    _instance = OutputHandlerRegistry(handlers)
    return _instance
