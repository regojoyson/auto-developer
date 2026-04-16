"""Abstract base classes for all provider types."""

from abc import ABC, abstractmethod


class IssueTrackerBase(ABC):
    """Base class for issue tracker adapters (Jira, GitHub Issues, etc.)."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def event_label(self) -> str: ...

    @abstractmethod
    def parse_webhook(self, headers: dict, payload: dict, config: dict) -> dict | None:
        """Parse webhook → { issue_key, summary, component } or None."""
        ...


class GitProviderBase(ABC):
    """Base class for git provider adapters (GitLab, GitHub, etc.)."""

    REQUIRED_API_METHODS = [
        "create_branch", "commit_files", "create_pr", "get_pr",
        "update_pr", "list_pr_comments", "post_pr_comment", "get_file",
    ]

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def pr_label(self) -> str: ...

    @abstractmethod
    def parse_webhook(self, headers: dict, payload: dict, config: dict) -> dict | None:
        """Parse webhook → { event, branch, pr_id, author } or None."""
        ...

    @abstractmethod
    def create_api(self, env: dict):
        """Return API client implementing all REQUIRED_API_METHODS."""
        ...

    def validate_api(self, api):
        for method in self.REQUIRED_API_METHODS:
            if not callable(getattr(api, method, None)):
                raise NotImplementedError(f"{self.__class__.__name__}.create_api(): missing '{method}'")


class CliAdapterBase(ABC):
    """Base class for AI coding CLI adapters (Claude Code, Codex, Gemini, etc.)."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def label(self) -> str: ...

    @property
    @abstractmethod
    def default_command(self) -> str: ...

    @property
    @abstractmethod
    def agent_dir(self) -> str: ...

    @property
    @abstractmethod
    def config_dir(self) -> str: ...

    @property
    @abstractmethod
    def rules_file_name(self) -> str: ...

    @abstractmethod
    def build_args(self, agent_name: str, input_text: str, config: dict) -> list[str]: ...

    def build_env(self, base_env: dict, config: dict) -> dict:
        return {**base_env, **(config.get("env") or {})}

    @abstractmethod
    def parse_output(self, stdout: str, stderr: str, exit_code: int) -> dict: ...


class NotificationBase(ABC):
    """Base class for notification adapters (Slack, Teams, etc.)."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def label(self) -> str: ...

    @abstractmethod
    async def send(self, message: str, config: dict) -> None: ...
