"""The hook's entry point. uv runs it as a plain script with its own Python 3.12 (`--no-project`), not in the server's
environment: the guard needs only the standard library, so a hook never waits for, or fails on, installing the
server's dependencies, and every write does not start the whole server's environment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from eunomai_project.guard import main  # noqa: E402

if __name__ == "__main__":
    main()
