"""MCP server (stdio): the tools Claude uses. Sign-in and workspace tools always; diagnostics only when the
organization's build enables them (EUNOMAI_DIAGNOSTICS=1)."""

import os

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from . import auth, gitops, hook, probe

mcp = MCPServer("eunomai-business")


def _safe(call, *args):
    try:
        return call(*args)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


# --- sign-in --------------------------------------------------------------------------------------------

@mcp.tool()
def sign_in_start(provider: str) -> dict:
    """Start signing in with a configured provider ("git" for workspaces). Opens the system browser; then call
    sign_in_status until it is no longer "waiting"."""
    return _safe(auth.start, provider, True)


@mcp.tool()
def sign_in_status(provider: str) -> dict:
    """State of the sign-in started with sign_in_start: idle, waiting, signed_in, failed or expired."""
    return _safe(auth.status, provider)


@mcp.tool()
def whoami(provider: str) -> dict:
    """Who the stored sign-in for a provider belongs to; refreshes the token if it expired. Never returns tokens."""
    return _safe(auth.whoami, provider)


@mcp.tool()
def sign_out(provider: str) -> dict:
    """Forget the stored sign-in for a provider on this computer (it is not revoked on the server)."""
    return _safe(auth.sign_out, provider)


# --- workspaces and versions ----------------------------------------------------------------------------

@mcp.tool()
def workspace_clone(repo_url: str, workspace: str = "") -> dict:
    """Clone a repository of the signed-in git server as a workspace in the user's workspaces folder.
    Returns the folder path on this computer: the user selects that folder in Cowork to work on its files."""
    return _safe(gitops.clone, repo_url, workspace)


@mcp.tool()
def workspace_list() -> dict:
    """List the workspaces in the user's workspaces folder: path, current version (branch) and origin."""
    return _safe(gitops.workspaces)


@mcp.tool()
def workspace_status(workspace: str) -> dict:
    """Current version (branch) and the files changed since the last save point, as this computer sees them."""
    return _safe(gitops.status, workspace)


@mcp.tool()
def version_create(workspace: str, name: str) -> dict:
    """Create a version (branch) from the current one and switch to it. Changed files are kept."""
    return _safe(gitops.branch, workspace, name)


@mcp.tool()
def version_save(workspace: str, message: str) -> dict:
    """Save point (commit) of every change in the workspace, as the signed-in git user. Never on the main branch."""
    return _safe(gitops.save, workspace, message)


@mcp.tool()
def version_send(workspace: str) -> dict:
    """Send the current version (branch) to the git server. Never the main branch, never forced."""
    return _safe(gitops.push, workspace)


@mcp.tool()
def version_propose(workspace: str, title: str, description: str = "") -> dict:
    """Open a pull request that proposes the current version for the main branch. Send it first (version_send)."""
    return _safe(gitops.pull_request, workspace, title, description)


# --- diagnostics (only when the build enables them) -----------------------------------------------------

async def diag_environment(ctx: Context) -> dict:
    """Where this connector runs (host, OS, user, Python), whether ${CLAUDE_PLUGIN_ROOT} was expanded, the
    configured sign-in providers, and the folders the client shares as roots."""
    report = probe.environment()
    report["providers"] = sorted(_safe(auth.providers) or {})
    try:
        roots = await ctx.session.list_roots()
        report["client_roots"] = [str(root.uri) for root in roots.roots]
    except Exception as exc:
        report["client_roots"] = f"unavailable: {type(exc).__name__}: {exc}"[:200]
    report["client_protocol"] = ctx.protocol_version
    return report


def diag_reach(url: str) -> dict:
    """Try an HTTP(S) URL from this computer: DNS, TLS with the OS certificate store and with the bundled one."""
    return _safe(probe.reach, url)


def diag_hook_log(lines: int = 20) -> list[dict] | dict:
    """Last lines written by the plugin's diagnostic hooks on this computer (empty if they never ran)."""
    return _safe(hook.read_log, lines)


if os.environ.get("EUNOMAI_DIAGNOSTICS") == "1":
    for _tool in (diag_environment, diag_reach, diag_hook_log):
        mcp.tool()(_tool)


def main() -> None:
    mcp.run("stdio")
