"""Shared pytest configuration.

Adds the project root to sys.path so tests can import `src.*` modules
without installing the project as a package.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
