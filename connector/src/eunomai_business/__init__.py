"""Local connector of eunomai-business: sign-in, workspaces, versions and save points."""

import os
from pathlib import Path


def data_dir() -> Path:
    """Per-user folder for logs and state, outside any repository."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    path = Path(base) / "eunomai-business"
    path.mkdir(parents=True, exist_ok=True)
    return path
