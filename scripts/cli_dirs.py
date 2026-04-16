#!/usr/bin/env python3
"""Helper for shell scripts — prints CLI adapter directory paths."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.providers.cli_adapter import get_cli_adapter

field = sys.argv[1] if len(sys.argv) > 1 else ""
adapter, _ = get_cli_adapter()

if field == "agentDir":
    print(adapter.agent_dir)
elif field == "configDir":
    print(adapter.config_dir)
elif field == "rulesFileName":
    print(adapter.rules_file_name)
else:
    print("Usage: python3 cli_dirs.py agentDir|configDir|rulesFileName", file=sys.stderr)
    sys.exit(1)
