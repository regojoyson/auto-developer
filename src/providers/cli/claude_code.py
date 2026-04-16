"""Claude Code CLI adapter."""

from src.providers.base import CliAdapterBase


class ClaudeCodeAdapter(CliAdapterBase):
    name = "claude-code"
    label = "Claude Code CLI"
    default_command = "claude"
    agent_dir = ".claude/agents"
    config_dir = ".claude"
    rules_file_name = "CLAUDE.md"

    def build_args(self, agent_name, input_text, config):
        args = ["--agent", agent_name, "--print", "--input", input_text]
        if config.get("model"):
            args.extend(["--model", config["model"]])
        if config.get("max_turns"):
            args.extend(["--max-turns", str(config["max_turns"])])
        args.extend(config.get("extra_args") or [])
        return args

    def parse_output(self, stdout, stderr, exit_code):
        return {
            "success": exit_code == 0,
            "output": stdout,
            "error": stderr or f"Exited with code {exit_code}" if exit_code != 0 else None,
        }


adapter = ClaudeCodeAdapter()
