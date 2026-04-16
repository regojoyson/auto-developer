"""
TUI wizard choice definitions.

All selectable options for the setup wizard are defined here in one place.
When a new provider, CLI adapter, or notification type is added, update
this file — the wizard picks up the changes automatically.

Usage::

    from installer.choices import REPO_MODES, ISSUE_TRACKERS, GIT_PROVIDERS
"""

import questionary

# ─── Repository Modes ────────────────────────────────────

REPO_MODES = [
    questionary.Choice("Local directory (one repo)", value="dir"),
    questionary.Choice("Parent directory (multiple repos)", value="parentDir"),
    questionary.Choice("Clone from git URL(s)", value="clone"),
]

# ─── Issue Trackers ──────────────────────────────────────

ISSUE_TRACKERS = [
    questionary.Choice("Jira", value="jira"),
    questionary.Choice("GitHub Issues", value="github-issues"),
]

# Default values per issue tracker type
ISSUE_TRACKER_DEFAULTS = {
    "jira": {
        "trigger_label": "Trigger status",
        "trigger_default": "Ready for Development",
        "done_label": "Done status",
        "done_default": "Done",
    },
    "github-issues": {
        "trigger_label": "Trigger label",
        "trigger_default": "ready-for-dev",
        "done_label": "Done label",
        "done_default": "done",
    },
}

# ─── Git Providers ───────────────────────────────────────

GIT_PROVIDERS = [
    questionary.Choice("GitLab", value="gitlab"),
    questionary.Choice("GitHub", value="github"),
]

# Environment variables required per git provider
GIT_PROVIDER_ENV = {
    "gitlab": [
        {"key": "GITLAB_BASE_URL", "label": "GitLab URL", "default": "https://gitlab.com", "secret": False},
        {"key": "GITLAB_TOKEN", "label": "GitLab token (api scope)", "default": "", "secret": True},
        {"key": "GITLAB_PROJECT_ID", "label": "GitLab project ID (numeric)", "default": "", "secret": False},
    ],
    "github": [
        {"key": "GITHUB_TOKEN", "label": "GitHub token", "default": "", "secret": True},
        {"key": "GITHUB_OWNER", "label": "GitHub owner (org or username)", "default": "", "secret": False},
        {"key": "GITHUB_REPO", "label": "GitHub repo name", "default": "", "secret": False},
    ],
}

# Default bot users per git provider
GIT_PROVIDER_BOTS = {
    "gitlab": "project_bot, ghost, ci-bot",
    "github": "dependabot[bot], github-actions[bot]",
}

# ─── CLI Adapters ────────────────────────────────────────

CLI_ADAPTERS = [
    questionary.Choice("Claude Code", value="claude-code"),
    questionary.Choice("Codex", value="codex"),
    questionary.Choice("Gemini", value="gemini"),
]

# ─── Notification Providers ──────────────────────────────

NOTIFICATION_PROVIDERS = [
    questionary.Choice("Slack", value="slack"),
]

# ─── Pipeline Defaults ───────────────────────────────────

PIPELINE_DEFAULTS = {
    "port": "3000",
    "max_rework": "3",
    "timeout_seconds": "300",
}
