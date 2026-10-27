"""The project's own tools. This is the file a project changes; the rest of the server comes from the template.

Rules for every tool (decision 10 of eunomai-business, checked by IT before publishing):
- It acts only on this project's workspaces: start from project.own_workspace(config, workspace).
- It enforces its own limits: what it may read or change is decided here, in code, not by the request.
- It changes nothing outside the workspace by itself: real changes travel as a version, through the git server.
- No secrets: settings (config["settings"]) hold addresses and names only; the build refuses obvious secrets, and
  IT's review the rest.
- A limit is refused with PermissionError or ValueError: Claude gets the reason. Any other failure stays on this
  computer and Claude gets only that the tool failed.

The example below lists a workspace's files under one folder the project names in its settings.
"""

from collections.abc import Callable

from . import project


def register(tool: Callable, config: dict) -> None:
    """Add the project's tools to the server: decorate each with `tool`."""
    settings = config.get("settings", {})

    @tool
    def project_example(workspace: str) -> dict:
        """Example tool of the template: the files under the folder the project's settings name `example_folder`,
        in one of this project's workspaces. Replace it with the project's own tools."""
        folder = project.own_workspace(config, workspace)
        base = (folder / str(settings.get("example_folder") or ".")).resolve()
        if not base.is_relative_to(folder.resolve()):  # a limit the tool enforces itself
            raise PermissionError("example_folder must stay inside the workspace")
        files = sorted(p.relative_to(folder).as_posix() for p in base.rglob("*")
                       if p.is_file() and ".git" not in p.relative_to(folder).parts)
        return {"workspace": workspace, "files": files[:200], "more": max(0, len(files) - 200)}
