"""Codex CLI adapter."""

from src.providers.base import CliAdapterBase


class CodexAdapter(CliAdapterBase):
    name = "codex"
    label = "Codex CLI"
    default_command = "codex"
    agent_dir = ".codex/agents"
    config_dir = ".codex"
    rules_file_name = "AGENTS.md"

    def build_args(self, agent_name, input_text, config):
        prompt = f"[Agent: {agent_name}]\n{input_text}"
        args = ["--prompt", prompt, "--full-auto"]
        if config.get("model"):
            args.extend(["--model", config["model"]])
        args.extend(config.get("extra_args") or [])
        return args

    def parse_output(self, stdout, stderr, exit_code):
        return {
            "success": exit_code == 0,
            "output": stdout,
            "error": stderr or f"Exited with code {exit_code}" if exit_code != 0 else None,
        }


adapter = CodexAdapter()
