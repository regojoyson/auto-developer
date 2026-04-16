"""
Abstract base classes for all four provider types.

Every adapter in the system extends one of these. The ABCs enforce the
interface at import time — if a required method is missing, you get a
clear error immediately, not at runtime when a webhook arrives.

Base classes:
    - IssueTrackerBase  — Jira, GitHub Issues, Linear, etc.
    - GitProviderBase   — GitLab, GitHub, Bitbucket, etc.
    - CliAdapterBase    — Claude Code, Codex, Gemini, etc.
    - NotificationBase  — Slack, Teams, etc.

To add a new provider, extend the appropriate base class and implement
all @abstractmethod methods. See docs/custom-providers.md for examples.
"""

from abc import ABC, abstractmethod


class IssueTrackerBase(ABC):
    """Base class for issue tracker adapters.

    Subclasses must define:
        - name (str):        Provider identifier (e.g. "jira")
        - event_label (str): Human term for a work item (e.g. "ticket", "issue")
        - parse_webhook():   Parse incoming webhook into structured data
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'jira', 'github-issues')."""
        ...

    @property
    @abstractmethod
    def event_label(self) -> str:
        """Human-readable label for a work item (e.g. 'ticket', 'issue')."""
        ...

    @abstractmethod
    def parse_webhook(self, headers: dict, payload: dict, config: dict) -> dict | None:
        """Parse an incoming webhook payload.

        Args:
            headers: HTTP request headers.
            payload: Webhook JSON body.
            config: issue_tracker section from config.yaml.

        Returns:
            Dict with keys (issue_key, summary, component) if the event
            matches the trigger criteria. None if the event should be ignored.
        """
        ...

    @abstractmethod
    def read_issue(self, issue_key: str) -> dict:
        """Read full issue details from the tracker.

        Used in API mode so the Python server can read the ticket
        and pass it to the agent without requiring MCP.

        Args:
            issue_key: Issue identifier (e.g. "PROJ-123").

        Returns:
            Dict with keys: summary, description, acceptance_criteria,
            components, labels, priority, linked_issues, comments, attachments.
        """
        ...

    @abstractmethod
    def transition_issue(self, issue_key: str, status_name: str) -> None:
        """Transition an issue to a new status.

        Args:
            issue_key: Issue identifier (e.g. "PROJ-123").
            status_name: Target status name (e.g. "Development", "Done").
        """
        ...

    @abstractmethod
    def add_comment(self, issue_key: str, body: str) -> None:
        """Add a comment to an issue.

        Args:
            issue_key: Issue identifier (e.g. "PROJ-123").
            body: Comment text body.
        """
        ...


class GitProviderBase(ABC):
    """Base class for git provider adapters.

    Subclasses must define:
        - name (str):      Provider identifier (e.g. "gitlab")
        - pr_label (str):  Human term for a PR/MR (e.g. "merge request")
        - parse_webhook(): Parse incoming webhook into structured data
        - create_api():    Return API client with all 8 required methods

    The API client returned by create_api() must implement:
        create_branch, commit_files, create_pr, get_pr, update_pr,
        list_pr_comments, post_pr_comment, get_file
    """

    REQUIRED_API_METHODS = [
        "create_branch", "commit_files", "create_pr", "get_pr",
        "update_pr", "list_pr_comments", "post_pr_comment", "get_file",
    ]

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'gitlab', 'github')."""
        ...

    @property
    @abstractmethod
    def pr_label(self) -> str:
        """Human-readable label for a PR/MR (e.g. 'merge request', 'pull request')."""
        ...

    @abstractmethod
    def parse_webhook(self, headers: dict, payload: dict, config: dict) -> dict | None:
        """Parse an incoming webhook payload.

        Args:
            headers: HTTP request headers.
            payload: Webhook JSON body.
            config: git_provider section from config.yaml.

        Returns:
            Dict with keys (event, branch, pr_id, author) where event is
            'approved', 'push', or 'comment'. None if event should be ignored.
        """
        ...

    @abstractmethod
    def create_api(self, env: dict, repo_dir: str | None = None):
        """Create an API client for this git provider.

        Args:
            env: Environment variables (contains tokens like GITLAB_TOKEN).
            repo_dir: Path to the target repo. Used to derive project
                identifiers (owner/repo/project_id) from git remote URL
                when not explicitly set in env.

        Returns:
            Object implementing all methods in REQUIRED_API_METHODS.
        """
        ...

    def validate_api(self, api):
        """Validate that an API client implements all required methods.

        Call this in your create_api() to catch mistakes early.

        Args:
            api: The API client object to validate.

        Raises:
            NotImplementedError: If any required method is missing.
        """
        for method in self.REQUIRED_API_METHODS:
            if not callable(getattr(api, method, None)):
                raise NotImplementedError(f"{self.__class__.__name__}.create_api(): missing '{method}'")


class CliAdapterBase(ABC):
    """Base class for AI coding CLI adapters.

    Subclasses must define:
        - name (str):             Adapter identifier (e.g. "claude-code")
        - label (str):            Display name (e.g. "Claude Code CLI")
        - default_command (str):  CLI executable (e.g. "claude")
        - agent_dir (str):        Where the CLI looks for agent files (e.g. ".claude/agents")
        - config_dir (str):       CLI config directory (e.g. ".claude")
        - rules_file_name (str):  Global rules filename (e.g. "CLAUDE.md")
        - build_args():           Build CLI arguments for agent invocation
        - parse_output():         Normalize CLI output into success/error dict
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Adapter identifier (e.g. 'claude-code', 'codex', 'gemini')."""
        ...

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable display name (e.g. 'Claude Code CLI')."""
        ...

    @property
    @abstractmethod
    def default_command(self) -> str:
        """Default CLI command if not overridden in config (e.g. 'claude')."""
        ...

    @property
    @abstractmethod
    def agent_dir(self) -> str:
        """Relative path where the CLI looks for agent .md files (e.g. '.claude/agents')."""
        ...

    @property
    @abstractmethod
    def config_dir(self) -> str:
        """Relative path to CLI config directory (e.g. '.claude')."""
        ...

    @property
    @abstractmethod
    def rules_file_name(self) -> str:
        """Filename for global rules in the CLI config dir (e.g. 'CLAUDE.md')."""
        ...

    @abstractmethod
    def build_args(self, agent_name: str, input_text: str, config: dict) -> list[str]:
        """Build CLI arguments for invoking an agent.

        Args:
            agent_name: Agent name (e.g. 'orchestrator', 'brainstorm').
            input_text: JSON string input to pass to the agent.
            config: cli_adapter section from config.yaml.

        Returns:
            List of CLI argument strings.
        """
        ...

    def build_env(self, base_env: dict, config: dict) -> dict:
        """Build environment variables for the agent process.

        Default: merge base env with any config.env overrides.
        Override in subclass for adapter-specific env vars.

        Args:
            base_env: Current process.env.
            config: cli_adapter section from config.yaml.

        Returns:
            Merged environment dict.
        """
        return {**base_env, **(config.get("env") or {})}

    @abstractmethod
    def parse_output(self, stdout: str, stderr: str, exit_code: int) -> dict:
        """Parse and normalize the CLI's output.

        Args:
            stdout: Standard output from the CLI process.
            stderr: Standard error from the CLI process.
            exit_code: Process exit code.

        Returns:
            Dict with keys (success: bool, output: str, error: str|None).
        """
        ...


class OutputHandlerBase(ABC):
    """Base class for agent output handlers.

    Output handlers receive real-time streaming output from agent CLI
    processes. Multiple handlers can be active at once (fan-out pattern).

    Built-in handlers: FileHandler (log files), MemoryHandler (API).
    Add custom handlers (websocket, webhook, etc.) by extending this class.

    Subclasses must define:
        - name (str): Handler identifier (e.g. "file", "memory")
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Handler identifier (e.g. 'file', 'memory')."""
        ...

    def on_start(self, issue_key: str, agent_name: str, cwd: str) -> None:
        """Called when an agent process starts.

        Args:
            issue_key: Ticket identifier (e.g. "PROJ-42").
            agent_name: Agent name (e.g. "orchestrator").
            cwd: Working directory of the agent process.
        """
        pass

    def on_output(self, issue_key: str, agent_name: str, line: str, stream: str) -> None:
        """Called for each line of output from the agent process.

        Args:
            issue_key: Ticket identifier.
            agent_name: Agent name.
            line: Single line of output text.
            stream: Which stream — "stdout" or "stderr".
        """
        pass

    def on_finish(self, issue_key: str, agent_name: str, exit_code: int) -> None:
        """Called when the agent process exits.

        Args:
            issue_key: Ticket identifier.
            agent_name: Agent name.
            exit_code: Process exit code (0 = success).
        """
        pass

    def get_output(self, issue_key: str, agent_name: str | None = None) -> str:
        """Retrieve captured output for an issue/agent.

        Args:
            issue_key: Ticket identifier.
            agent_name: Optional agent name to filter. If None, returns all.

        Returns:
            Captured output text, or empty string if not available.
        """
        return ""

    def delete_logs(self, issue_key: str) -> None:
        """Delete all stored output for an issue.

        Called when a pipeline is cancelled. Subclasses should clean up
        any persisted data (files, buffers, etc.) for the given issue.

        Args:
            issue_key: Ticket identifier (e.g. "PROJ-123").
        """
        pass


class NotificationBase(ABC):
    """Base class for notification adapters.

    Subclasses must define:
        - name (str):   Provider identifier (e.g. "slack")
        - label (str):  Display name (e.g. "Slack")
        - send():       Send a notification message
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'slack', 'teams')."""
        ...

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable display name (e.g. 'Slack')."""
        ...

    @abstractmethod
    async def send(self, message: str, config: dict) -> None:
        """Send a notification message.

        Args:
            message: Message text to send.
            config: notification section from config.yaml.
        """
        ...
