"""The project plugin's own local server: two tools that report what it sees."""

import json
import os
import sys

from mcp.server import MCPServer

from .guard import log_file

mcp = MCPServer("project-spike", instructions="H10 spike tools for eunomai-business's project plugin test.")


@mcp.tool()
def project_ping() -> dict:
    """Report this project server's runtime: the Python (and the installation it comes from) and the plugin root."""
    return {"server": "project-spike", "python": sys.version.split()[0], "executable": sys.executable,
            "python_installation": sys.base_prefix, "plugin_root": os.environ.get("CLAUDE_PLUGIN_ROOT")}


@mcp.tool()
def project_guard_log(last: int = 20) -> list:
    """The project hook's last consultations: which tool, which target, and whether it denied it."""
    try:
        lines = log_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [json.loads(line) for line in lines[-max(1, min(last, 200)):]]


def main() -> None:
    mcp.run("stdio")
