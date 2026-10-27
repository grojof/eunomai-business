"""Files Claude never writes or saves: the project's context and the repository's configuration, which only IT
changes, and anything Windows runs or opens as a program on a double click, since the workspace folder lives on
the user's computer.

The same rules serve two barriers. The PreToolUse hook denies a write as it is attempted (the file tools always; the
sandbox shell best effort, since it sees a command as text), so Claude learns at once and nothing dangerous lands
on the computer. `version_save` enforces them on the host, where the sandbox cannot reach: context and
configuration files are put back as the last save point has them, and an executable stops the save.

Executables are refused everywhere Claude writes. Context and configuration rules apply inside workspaces only, so
the plugin does not get in the way of Cowork's own files elsewhere.
"""

import argparse
import json
import os
import re
import sys

from . import data_dir, rules

CONTEXT_FILES = {"agents.md", "claude.md"}
# Claude's configuration, the repository's, the project's declaration, and continuous integration, which runs on
# IT's servers.
CONFIG_FOLDERS = {".claude", ".eunomai", ".git", ".gitea", ".github", ".forgejo", ".circleci", ".woodpecker"}
CONFIG_FILES = {".mcp.json", ".gitlab-ci.yml", ".woodpecker.yml", ".drone.yml", "jenkinsfile", "azure-pipelines.yml",
                "bitbucket-pipelines.yml"}
# What Windows runs, installs or follows on a double click. Script sources that need an interpreter's file
# association (.js through Windows Script Host, .py through the Python launcher) cannot be refused without refusing
# every web application; turning those associations off is an operating-system control (docs/barriers.md).
HOST_EXECUTABLES = {".appinstaller", ".application", ".appref-ms", ".appx", ".bat", ".chm", ".cmd", ".com", ".cpl",
                    ".diagcab", ".exe", ".gadget", ".hta", ".jar", ".jse", ".library-ms", ".lnk", ".msc", ".msi",
                    ".msix", ".msp", ".pif", ".ps1", ".psd1", ".psm1", ".reg", ".scf", ".scr", ".search-ms",
                    ".settingcontent-ms", ".url", ".vbe", ".vbs", ".wsf", ".wsh", ".xll"}
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_SHELL_TOOLS = {"Bash", "mcp__workspace__bash"}
# In a command, extensions that also end host names (example.com) or common words are left to version_save.
_SHELL_EXTENSIONS = HOST_EXECUTABLES - {".com", ".cpl", ".msc", ".pif", ".scf", ".url"}
_WRITES = r"(?:>|\btee\b|\bcp\b|\bmv\b|\bln\b|\btouch\b|\bmkdir\b|sed\s+-i|Set-Content|Add-Content|Out-File|New-Item)" \
          r"[^|;&]*?"
_EXECUTABLE_WRITE = re.compile(
    _WRITES + r"([\w.-]+(?:" + "|".join(re.escape(e) for e in sorted(_SHELL_EXTENSIONS)) + r"))\b", re.IGNORECASE)
_FOLDERS = "|".join(re.escape(f) for f in sorted(CONFIG_FOLDERS))
_FILES = "|".join(re.escape(f) for f in sorted(CONFIG_FILES))
_PROTECTED_WRITE = re.compile(
    _WRITES + r"(?<![\w.-])((?:AGENTS|CLAUDE)\.md\b|[\w./\\-]*?(?:" + _FOLDERS + r")(?:[\\/]|\b(?![\w.-]))"
    r"|[\w./\\-]*?(?:" + _FILES + r")\b)", re.IGNORECASE)

# An 8.3 short name (AGENTS~1.MD, CLAUDE~1) can stand for a protected file or folder on Windows.
_SHORT_NAME = re.compile(r"^[^~]{1,6}~[0-9]+(\.[^.]{0,3})?$")

REASONS = {
    "context": "the project's context ({name}) is kept by IT; propose a change in the pull request summary instead",
    "config": "{name} configures Claude, the repository or its automation, and only IT changes it",
    "executable": "{name} would run on the user's computer with a double click; nothing that runs there is "
                  "written, the work is tried inside the sandbox",
}


def _parts(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", path or "") if p]


def kind(path: str, in_workspace: bool = True) -> str | None:
    """"context", "config" or "executable" for a path Claude may not write; None otherwise. Outside a workspace
    only executables count."""
    parts = [p.lower().rstrip(". ") for p in _parts(path)]  # Windows ignores trailing dots and spaces
    if not parts:
        return None
    name = parts[-1].split(":")[0]  # an alternate data stream (run.bat:x) is still run.bat
    if any(name.endswith(ext) for ext in HOST_EXECUTABLES):
        return "executable"
    if not in_workspace:
        return None
    if name in CONTEXT_FILES:
        return "context"
    # the folder itself counts too: on Linux a link named .claude is a single entry, not a folder
    if name in CONFIG_FILES or any(p in CONFIG_FOLDERS for p in parts[:-1] + [name]):
        return "config"
    if any(_SHORT_NAME.match(p) for p in parts):
        return "config"
    return None


def reason(path: str, in_workspace: bool = True) -> str | None:
    """Why a path may not be written, or None."""
    found = kind(path, in_workspace)
    return REASONS[found].format(name=_parts(path)[-1]) if found else None


def shell_reason(command: str, in_workspace: bool = True) -> str | None:
    """Best effort for the sandbox shell: a command that writes an executable, or a protected file in a workspace.
    Removing one is allowed, so Claude can clean up what version_save refused."""
    match = _EXECUTABLE_WRITE.search(command or "")
    if match:
        return REASONS["executable"].format(name=match.group(1))
    match = _PROTECTED_WRITE.search(command or "") if in_workspace else None
    if match:
        found = "context" if match.group(1).lower().endswith(".md") else "config"
        return REASONS[found].format(name=match.group(1))
    return None


def _workspace_folders() -> list[str]:
    """The folders of the workspaces the connector registered."""
    try:
        return list(json.loads((data_dir() / "workspaces.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _workspace_names() -> set[str]:
    """Their folder names (the sandbox sees the same names)."""
    return {_parts(folder)[-1].lower() for folder in _workspace_folders() if _parts(folder)}


def _inside(text: str, names: set[str]) -> bool:
    return any(part.lower() in names for part in _parts(text.replace(" ", "/")))


# The connector, the workspace folders and the git servers are on the user's computer and its network, which a
# Cowork task in the cloud cannot reach: such a task is refused outright, prompt by prompt and tool by tool. Claude
# Code sets these variables in cloud sessions for hooks to read; the PreToolUse hook's onFailure also blocks when
# the hook cannot start there.
CLOUD = ("this Cowork task runs in the cloud, and eunomai-business only works with tasks on the user's computer. "
         "Ask the user to start a new task on this computer; if Cowork offers no way to, IT has to turn off running "
         "tasks in the cloud for the organization")


def in_the_cloud() -> bool:
    return (os.environ.get("CLAUDE_CODE_REMOTE", "").strip().lower() == "true"
            or bool(os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID", "").strip()))


def decide(payload: dict, policy: list[dict] | None = None) -> str | None:
    """Why a tool call may not run, or None: the file guard first, then the organization's deny rules (Bash rules
    anywhere, Edit rules in workspaces)."""
    if in_the_cloud():
        return CLOUD
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    found = None
    if tool in _WRITE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        found = reason(path, _inside(path, _workspace_names()))
    elif tool in _SHELL_TOOLS:
        command = str(tool_input.get("command") or "")
        found = shell_reason(command, _inside(command + " " + str(payload.get("cwd") or ""), _workspace_names()))
    if found or not policy or tool not in _WRITE_TOOLS | _SHELL_TOOLS:
        return found
    cwd = str(payload.get("cwd") or "")
    return (rules.deny_reason([r for r in policy if rules.parse(r["rule"])[0] == "Bash"], tool, tool_input, cwd, None)
            or rules.deny_reason([r for r in policy if rules.parse(r["rule"])[0] == "Edit"], tool, tool_input, cwd,
                                 _workspace_folders()))


def load_policy(path: str | None) -> list[dict]:
    """The organization's deny rules the build packaged (policy.json). Unreadable rules are an error, which the
    tool-call hook's onFailure turns into a block."""
    if not path:
        return []
    with open(path, encoding="utf-8") as handle:
        policy = json.load(handle).get("deny", [])
    errors = rules.problems(policy)
    if errors:
        raise ValueError("eunomai-business: the packaged deny rules are invalid: " + "; ".join(errors))
    return policy


def _refuse_the_cloud(event: str | None) -> None:
    if event == "UserPromptSubmit":
        print(json.dumps({"decision": "block", "reason": f"eunomai-business: {CLOUD}."}))
    elif event == "SessionStart":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": f"eunomai-business: {CLOUD}."}}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": f"eunomai-business: {CLOUD}."}}))
    sys.exit(0)


def main(argv: list[str] | None = None) -> None:
    """SessionStart, UserPromptSubmit and PreToolUse hook. In the cloud everything is refused. Otherwise only tool
    calls are checked, and input it cannot read is let through: version_save still holds for workspaces."""
    parser = argparse.ArgumentParser(description="eunomai-business's guard hook.")
    parser.add_argument("--policy", help="the organization's deny rules (policy.json in the plugin)")
    arguments = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = None
    event = payload.get("hook_event_name") if isinstance(payload, dict) else None
    if in_the_cloud():
        _refuse_the_cloud(event)
    if not isinstance(payload, dict) or event not in (None, "PreToolUse"):
        sys.exit(0)
    found = decide(payload, load_policy(arguments.policy))
    if found:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": f"eunomai-business: {found}."}}))
    sys.exit(0)
