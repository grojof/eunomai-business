"""Hook entry point (diagnostics): records where and how plugin hooks run, then gets out of the way.

Only built into the plugin when diagnostics are enabled. It never blocks: it exits 0 whatever happens. On
SessionStart it prints one line, which Claude receives as context, so the session itself can tell where the hook
ran. The log is rotated at 1 MB (one previous file is kept).
"""

import json
import os
import platform
import socket
import sys
import time

from . import data_dir

LOG_NAME = "hooks.log"
_LOG_LIMIT = 1_000_000  # bytes


def _shell_hint() -> str:
    if os.environ.get("PSModulePath") and not os.environ.get("SHELL"):
        return "powershell-or-cmd"
    return os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown"


def main() -> None:
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}
    event = payload.get("hook_event_name", "unknown")
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": event,
        "tool": payload.get("tool_name"),
        "host": socket.gethostname(),
        "os": platform.platform(),
        "shell": _shell_hint(),
        "cwd": os.getcwd(),
        "plugin_root": os.environ.get("CLAUDE_PLUGIN_ROOT"),
        "session": payload.get("session_id"),
    }
    try:
        path = data_dir() / LOG_NAME
        if path.exists() and path.stat().st_size > _LOG_LIMIT:
            os.replace(path, path.with_suffix(".log.1"))
        with open(path, "a", encoding="utf-8") as log:
            log.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    if event == "SessionStart":
        print(f"[eunomai-business] SessionStart hook ran on host {entry['host']} ({entry['os']}), "
              f"shell {entry['shell']}.")
    sys.exit(0)


def read_log(lines: int = 20) -> list[dict]:
    path = data_dir() / LOG_NAME
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as log:
        for line in log.readlines()[-lines:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"unreadable_line": line[:200]})
    return entries
