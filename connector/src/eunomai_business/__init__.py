"""Local connector of eunomai-business: sign-in, workspaces, versions and save points."""

import os
import re
from pathlib import Path

DEFAULT_PLUGIN = "eunomai-business"
PLUGIN_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
"""What an organization may name its plugin: the build checks it, and the connector reads it from EUNOMAI_PLUGIN."""


def plugin_name() -> str:
    """The plugin this connector belongs to, as the build named it. Several plugins built from eunomai-business can
    live on one computer; each keeps its own folder, sign-ins, workspaces and previews. Without a valid name, the
    original one, so an install from before names were configurable keeps what it had."""
    name = os.environ.get("EUNOMAI_PLUGIN", "").strip()
    return name if PLUGIN_NAME.match(name) else DEFAULT_PLUGIN


def data_dir() -> Path:
    """Per-user folder for logs and state, outside any repository: one per plugin."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    path = Path(base) / plugin_name()
    path.mkdir(parents=True, exist_ok=True)
    return path
