"""Files Claude never writes or saves: the project's context, which only IT changes, and anything Windows would
run on a double click, since the workspace folder lives on the user's computer.

The same rules serve two barriers. The PreToolUse hook denies a write as it is attempted (Write, Edit and the
sandbox shell, the latter best effort), so Claude learns at once. `version_save` enforces them on the host, where the
sandbox cannot reach: context and configuration files are put back as the last save point has them, and executables
stop the save.
"""

import json
import re
import sys

CONTEXT_FILES = {"agents.md", "claude.md"}
CONFIG_FOLDERS = {".claude", ".git"}
CONFIG_FILES = {".mcp.json"}
# What Windows runs or follows on a double click. Source code (.py, .js) is not here: it needs an interpreter.
HOST_EXECUTABLES = {".appref-ms", ".bat", ".cmd", ".com", ".cpl", ".exe", ".hta", ".jse", ".lnk", ".msc", ".msi",
                    ".msp", ".pif", ".ps1", ".psd1", ".psm1", ".reg", ".scf", ".scr", ".url", ".vbe", ".vbs",
                    ".wsf", ".wsh"}
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_SHELL_TOOLS = {"Bash", "mcp__workspace__bash"}
# In a command, extensions that also end host names (example.com) or common words are left to version_save.
_SHELL_EXTENSIONS = HOST_EXECUTABLES - {".com", ".cpl", ".msc", ".pif", ".scf", ".url"}
_WRITES = r"(?:>|\btee\b|\bcp\b|\bmv\b|\bln\b|\btouch\b|sed\s+-i|Set-Content|Add-Content|Out-File)[^|;&]*?"
_EXECUTABLE_WRITE = re.compile(
    _WRITES + r"([\w.-]+(?:" + "|".join(re.escape(e) for e in sorted(_SHELL_EXTENSIONS)) + r"))\b", re.IGNORECASE)
_CONTEXT_WRITE = re.compile(_WRITES + r"\b((?:AGENTS|CLAUDE)\.md)\b", re.IGNORECASE)

REASONS = {
    "context": "the project's context ({name}) is kept by IT; propose a change in the pull request summary instead",
    "config": "{name} configures Claude or the repository, and only IT changes it",
    "executable": "{name} would run on the user's computer with a double click; nothing that runs there is "
                  "written, the work is tried inside the sandbox",
}


def _parts(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", path or "") if p]


def kind(path: str) -> str | None:
    """"context", "config" or "executable" for a path Claude may not write; None otherwise."""
    parts = [p.lower() for p in _parts(path)]
    if not parts:
        return None
    if parts[-1] in CONTEXT_FILES:
        return "context"
    if parts[-1] in CONFIG_FILES or any(p in CONFIG_FOLDERS for p in parts[:-1]):
        return "config"
    if any(parts[-1].endswith(ext) for ext in HOST_EXECUTABLES):
        return "executable"
    return None


def reason(path: str) -> str | None:
    """Why a path may not be written, or None."""
    found = kind(path)
    return REASONS[found].format(name=_parts(path)[-1]) if found else None


def shell_reason(command: str) -> str | None:
    """Best effort for the sandbox shell: a command that writes an executable or a context file. Removing one is
    allowed, so Claude can clean up what version_save refused."""
    for pattern, found in ((_EXECUTABLE_WRITE, "executable"), (_CONTEXT_WRITE, "context")):
        match = pattern.search(command or "")
        if match:
            return REASONS[found].format(name=match.group(1))
    return None


def decide(payload: dict) -> str | None:
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if tool in _WRITE_TOOLS:
        return reason(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
    if tool in _SHELL_TOOLS:
        return shell_reason(str(tool_input.get("command") or ""))
    return None


def main() -> None:
    """PreToolUse hook. Anything it cannot read is let through: version_save is the barrier that holds."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    found = decide(payload) if isinstance(payload, dict) else None
    if found:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": f"eunomai-business: {found}."}}))
    sys.exit(0)
