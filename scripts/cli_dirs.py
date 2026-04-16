#!/usr/bin/env python3
"""Print CLI adapter directory paths for use by shell scripts.

A small helper that loads the configured CLI adapter and prints one of its
directory-related properties to stdout. Used by shell scripts (e.g.
``start.sh``, ``stop.sh``) that need to know where agent files live without
parsing YAML themselves.

Usage::

    python3 scripts/cli_dirs.py agentDir      # e.g. ".claude/agents"
    python3 scripts/cli_dirs.py configDir     # e.g. ".claude"
    python3 scripts/cli_dirs.py rulesFileName # e.g. "CLAUDE.md"
"""

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
