"""Launch script for the Draft Developer Cockpit."""

import os
import sys

# Keep the directory containing the application source/runtime
# available for development-mode imports.
if not getattr(sys, "frozen", False):
    project_root = os.path.dirname(os.path.abspath(__file__))

    agent_dir = os.path.join(project_root, "agent")

    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)

    if project_root not in sys.path:
        sys.path.insert(0, project_root)


from tui.app import DraftApp


def main() -> None:
    """Launch the Draft Developer Cockpit."""
    app = DraftApp()
    app.run()


if __name__ == "__main__":
    main()