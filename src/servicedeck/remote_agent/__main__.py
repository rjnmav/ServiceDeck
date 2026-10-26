"""Allow executing servicedeck-remote as a module: python -m servicedeck.remote_agent."""

import sys

from servicedeck.remote_agent.main import main

if __name__ == "__main__":
    sys.exit(main())
