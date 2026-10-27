"""The project plugin's local server: the template's own tools, and the project's tools from project_tools.py.

Tools are shared by the whole Cowork session, and eunomai-business's guard does not watch them: each tool enforces
its own limits (only this project's workspaces, only what IT allowed). It runs on the user's computer, so it reaches
internal servers; secrets never live here (see the template's README).
"""

import argparse
import functools
import inspect

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import project, project_tools


def build(config: dict) -> MCPServer:
    name = config.get("display_name") or config["name"]
    mcp = MCPServer(config["name"], instructions=f"Tools of the {name} project, in its own workspaces only. "
                                                 "eunomai-business's specialist leads the work.")

    def tool(function):
        """Register a tool. A limit it enforces (PermissionError, ValueError) reaches Claude with its reason; any
        other failure stays on this computer, as the MCP library does."""
        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def checked(*args, **kwargs):
                try:
                    return await function(*args, **kwargs)
                except (PermissionError, ValueError) as exc:
                    raise ToolError(str(exc)) from exc
        else:
            @functools.wraps(function)
            def checked(*args, **kwargs):
                try:
                    return function(*args, **kwargs)
                except (PermissionError, ValueError) as exc:
                    raise ToolError(str(exc)) from exc
        return mcp.tool()(checked)

    @tool
    def project_workspaces() -> list[dict]:
        """This project's workspaces on this computer: folder name, path, and the repository it was cloned from."""
        return project.workspaces(config)

    @tool
    def project_rules() -> list[dict]:
        """The paths this project protects in its workspaces, and why. A write to one of them is denied: explain the
        reason to the user and change the work, never work around it."""
        return [{"paths": rule["paths"], "reason": rule["reason"]} for rule in config.get("deny", [])]

    project_tools.register(tool, config)
    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="The project plugin's local server.")
    parser.add_argument("--config", required=True)
    build(project.load(parser.parse_args(argv).config)).run("stdio")
