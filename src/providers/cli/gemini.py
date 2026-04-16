"""Gemini CLI adapter."""

from src.providers.base import CliAdapterBase


class GeminiAdapter(CliAdapterBase):
    name = "gemini"
    label = "Gemini CLI"
    default_command = "gemini"
    agent_dir = ".gemini/agents"
    config_dir = ".gemini"
    rules_file_name = "GEMINI.md"

    def build_args(self, agent_name, input_text, config):
        prompt = f"[Agent: {agent_name}]\n{input_text}"
        args = ["--prompt", prompt]
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


adapter = GeminiAdapter()
