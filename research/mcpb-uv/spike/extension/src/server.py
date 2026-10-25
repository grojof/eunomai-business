"""Spike for an MCPB extension of type "uv": answers, inside Claude Cowork, whether Claude Desktop runs a Python
extension without uv or Python installed by the user, whether it honours the bundled uv.lock, and whether a plugin's
mcp_tool hook can call an extension's server. Standard library only, plus one dependency used as a probe: the
lockfile pins six 1.16.0 while pyproject.toml allows any newer version, so the version found tells whether the lock
was used. A minimal MCP server over stdio (newline-delimited JSON-RPC)."""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

MARKER = "eunomai-spike-guard"
DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "eunomai-mcpb-spike"
DATA.mkdir(parents=True, exist_ok=True)
LOG = DATA / "spike.log"


def log(**entry) -> None:
    with open(LOG, "a", encoding="utf-8") as out:
        out.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}) + "\n")


def _parent_command() -> str | None:
    """The command line that started this process's parent (uv), to see which uv Claude Desktop used."""
    if sys.platform != "win32":
        return None
    script = (f"$p=(Get-CimInstance Win32_Process -Filter 'ProcessId={os.getppid()}');"
              "\"$($p.ExecutablePath) | $($p.CommandLine)\"")
    try:
        run = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        return run.stdout.strip()[:600]
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unknown: {exc}"


def runtime(_: dict) -> dict:
    try:
        import six
        probe = six.__version__
    except ImportError:
        probe = None
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "prefix": sys.prefix,
        "platform": platform.platform(),
        "probe_six": probe,
        "lock_honoured": probe == "1.16.0",
        "uv_on_path": shutil.which("uv"),
        "parent": _parent_command(),
        "argv": sys.argv,
        "data_dir": str(DATA),
        "env_uv": {k: v for k, v in os.environ.items() if k.startswith("UV_")},
    }


def guard(args: dict) -> dict:
    text = json.dumps(args or {})
    deny = MARKER in text
    log(guard="deny" if deny else "allow", tool=args.get("tool_name"), via=args.get("via"))
    if not deny:
        return {}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "eunomai MCPB spike: guard test marker found."}}


def guard_log(_: dict) -> list:
    if not LOG.exists():
        return []
    return [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines()[-20:]]


TOOLS = {
    "spike_runtime": ("Which Python and uv run this extension, and whether the bundled lockfile was used.", {},
                      runtime),
    "spike_guard": ("Called by the test plugin's PreToolUse hook; denies tool calls that mention the test marker.",
                    {"tool_name": {"type": "string"}, "file_path": {"type": "string"},
                     "command": {"type": "string"}, "via": {"type": "string"}}, guard),
    "spike_guard_log": ("The last decisions the guard made.", {}, guard_log),
}


def reply(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method, params = message.get("id"), message.get("method"), message.get("params") or {}
        if mid is None:
            continue
        if method == "initialize":
            log(start=runtime({}))
            reply({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                "serverInfo": {"name": "eunomai-mcpb-spike", "version": "0.0.1"}}})
        elif method == "ping":
            reply({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif method == "tools/list":
            reply({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                {"name": name, "description": desc, "inputSchema": {"type": "object", "properties": props}}
                for name, (desc, props, _) in TOOLS.items()]}})
        elif method == "tools/call":
            tool = TOOLS.get(params.get("name"))
            if tool is None:
                reply({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "unknown tool"}],
                                                                "isError": True}})
                continue
            try:
                text = json.dumps(tool[2](params.get("arguments") or {}))
                reply({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}})
            except Exception as exc:  # a spike reports, it does not hide
                reply({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": repr(exc)}],
                                                                "isError": True}})
        else:
            reply({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
