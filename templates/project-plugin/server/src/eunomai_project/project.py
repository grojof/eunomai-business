"""What IT configured for this project (project.json, written by the build) and which workspaces are this project's.

A workspace is the project's when the repository it was cloned from is one of the project's repositories, as
eunomai-business's connector registered it at clone time (workspaces.json in its data folder, on the user's computer
where Claude's sandbox does not reach). Never from the workspace's .git/config, which the sandbox can rewrite.
Standard library only: the hook imports this module without the server's dependencies.
"""

import json
import os
import re
from pathlib import Path


def load(path: str | Path) -> dict:
    """The project's configuration. It is checked by the build, so here anything unreadable is an error."""
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    config.setdefault("deny", [])
    config.setdefault("settings", {})
    return config


def repository_key(url: str | None) -> str:
    return (url or "").strip().removesuffix("/").removesuffix(".git").lower()


BASE_PLUGIN = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")


def registry_file(base_plugin: str = "eunomai-business") -> Path:
    """The base plugin's register of workspaces: the folder its connector uses (eunomai_business.data_dir), named
    after the plugin as the organization's build named it."""
    if not BASE_PLUGIN.match(base_plugin):
        raise ValueError(f"base_plugin {base_plugin!r} is not a plugin's name")
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    return Path(base) / base_plugin / "workspaces.json"


def workspaces(config: dict) -> list[dict]:
    """This project's workspaces on this computer: folder name, path and origin."""
    try:
        register = registry_file(str(config.get("base_plugin", "eunomai-business")))
        registry = json.loads(register.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    wanted = {repository_key(url) for url in config.get("repositories", [])}
    found = []
    for folder, entry in sorted(registry.items()) if isinstance(registry, dict) else []:
        origin = entry.get("origin") if isinstance(entry, dict) else None
        if isinstance(origin, str) and repository_key(origin) in wanted and Path(folder).is_dir():
            found.append({"workspace": Path(folder).name, "path": folder, "origin": origin})
    return found


def own_workspace(config: dict, name: str) -> Path:
    """The folder of one of this project's workspaces. Every tool that takes a workspace starts here, so it never
    acts on another project's files."""
    for item in workspaces(config):
        if item["workspace"].lower() == (name or "").strip().lower():
            return Path(item["path"])
    raise PermissionError(f"{name!r} is not a workspace of {config.get('display_name') or config.get('name')}")
