"""Launch script for the Draft Developer Cockpit.

Usage:
    python run_tui.py

This sets up the Python path correctly so that both the agent
modules and the TUI modules can be imported.
"""

import os
import sys

# Project root
project_root = os.path.dirname(os.path.abspath(__file__))

# Add agent directory to path (for events, runtime, etc.)
agent_dir = os.path.join(project_root, "agent")
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

# Add project root to path (for tui package)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Ensure we run from the project root (for relative paths in tools)
os.chdir(project_root)

from tui.app import DraftApp


def main() -> None:
    """Launch the Draft Developer Cockpit."""
    app = DraftApp()
    app.run()


if __name__ == "__main__":
    main()
