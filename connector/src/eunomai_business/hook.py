"""Hook entry point (diagnostics): records where and how plugin hooks run, then gets out of the way.

Only built into the plugin when diagnostics are enabled. On SessionStart it prints one line, which Claude receives
as context, so the session itself can tell where the hook ran. The log is rotated at 1 MB (one previous file is
kept); it records the names of a tool's input fields, never their values.

Validation of the planned file guard (H9): a tool whose input mentions a test marker is denied, with a JSON answer
or with exit code 2, the two ways a hook can stop a tool. Nothing else is ever blocked.
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
_GUARD_TEST = {"eunomai-guard-test-json": "json", "eunomai-guard-test-exit2": "exit2"}
_DENIED = "eunomai-business guard test (H9): this file is protected."


def _shell_hint() -> str:
    if os.environ.get("PSModulePath") and not os.environ.get("SHELL"):
        return "powershell-or-cmd"
    return os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown"


def _process_start(pid: int) -> float | None:
    """When a process started (Windows), to measure how long launching the hook takes."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return created / 1e7 - 11644473600  # FILETIME: 100 ns since 1601
    finally:
        kernel32.CloseHandle(handle)


def main() -> None:
    started = time.time()
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}
    event = payload.get("hook_event_name", "unknown")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    guard = None
    if event == "PreToolUse":
        text = json.dumps(tool_input)
        guard = next((mode for marker, mode in _GUARD_TEST.items() if marker in text), None)
    parent_start = _process_start(os.getppid())
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": event,
        "tool": payload.get("tool_name"),
        "input_keys": sorted(tool_input),
        "guard": guard,
        "launch_ms": round((started - parent_start) * 1000) if parent_start else None,
        "host": socket.gethostname(),
        "os": platform.platform(),
        "shell": _shell_hint(),
        "cwd": os.getcwd(),
        "plugin_root": os.environ.get("CLAUDE_PLUGIN_ROOT"),
        "session": payload.get("session_id"),
    }
    entry["hook_ms"] = round((time.time() - started) * 1000)
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
    if guard == "json":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": _DENIED}}))
    elif guard == "exit2":
        print(_DENIED, file=sys.stderr)
        sys.exit(2)
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
