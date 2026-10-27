"""The project's PreToolUse hook: denies writing the paths the project's rules protect, in the project's own
workspaces only. It never allows and never rewrites a call: eunomai-business's guard runs on the same call, and a
deny from either one stops it.

A path is in a workspace when it is under the workspace's folder on the computer, or under its folder as Claude's
sandbox mounts it (.../mnt/<workspace>/...). The file tools are checked always; the sandbox shell best effort, since
a command is only text. Rules are paths relative to the workspace, with * (inside one folder) and ** (any depth),
matched ignoring case. Standard library only (see hook.py).
"""

import argparse
import json
import re
import sys

from . import project

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "mcp__workspace__bash"}
# Commands that write, move or remove files: eunomai-business's list, plus removing and unpacking.
_WRITES = re.compile(r"(?:>|\btee\b|\bcp\b|\bmv\b|\bln\b|\btouch\b|\bmkdir\b|sed\s+-i|Set-Content|Add-Content"
                     r"|Out-File|New-Item|\brm\b|\brmdir\b|\btruncate\b|\bdd\b|\bunzip\b|\btar\b|Remove-Item)",
                     re.IGNORECASE)
_TOKENS = re.compile(r"""[^\s'"<>|;&]+""")
# An 8.3 short name (DATABA~1) can stand for a protected folder on Windows.
_SHORT_NAME = re.compile(r"^[^~]{1,6}~[0-9]+(\.[^.]{0,3})?$")
_SHORT_NAME_REASON = "short (8.3) names are not used in this project's workspaces; use the full name"


def _parts(path: str) -> list[str]:
    """A path's names, with .. resolved. An alternate data stream (x.csv:s) is still x.csv, and Windows ignores
    trailing dots and spaces."""
    raw = [part for part in re.split(r"[\\/]+", path or "") if part]
    if raw and ":" in raw[-1] and not re.fullmatch(r"[A-Za-z]:", raw[-1]):
        raw[-1] = raw[-1].split(":")[0]
    parts = []
    for part in raw:
        if part == "..":
            parts = parts[:-1]
        elif part.rstrip(". "):
            parts.append(part.rstrip(". "))
    return parts


def pattern(glob: str) -> re.Pattern:
    """A rule's path as a regular expression over a workspace-relative path with / separators."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + r"\Z", re.IGNORECASE)


def _relative(path: str, workspaces: list[dict]) -> str | None:
    """The part of a path inside one of the project's workspaces, or None if it is in none of them."""
    parts = [part.lower() for part in _parts(path)]
    original = _parts(path)
    for item in workspaces:
        folder = [part.lower() for part in _parts(item["path"])]
        if parts[:len(folder)] == folder:  # on the computer
            return "/".join(original[len(folder):])
        name, parent = folder[-1], folder[-2] if len(folder) > 1 else ""
        for index, part in enumerate(parts[:-1]):  # in the sandbox: .../mnt/<workspace>/ or .../mnt/<root>/<workspace>/
            if part != "mnt":
                continue
            if parts[index + 1] == name:
                return "/".join(original[index + 2:])
            if parent and parts[index + 1] == parent and parts[index + 2:index + 3] == [name]:
                return "/".join(original[index + 3:])
    return None


def _why(relative: str, rules: list[dict]) -> str | None:
    if any(_SHORT_NAME.match(part) for part in relative.split("/")):
        return _SHORT_NAME_REASON
    for rule in rules:
        if any(pattern(glob).match(relative) for glob in rule["paths"]):
            return rule["reason"]
    return None


def decide(payload: dict, config: dict) -> str | None:
    """Why the call may not run, or None."""
    rules = config.get("deny") or []
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not rules or tool not in WRITE_TOOLS | SHELL_TOOLS:
        return None
    workspaces = project.workspaces(config)
    if not workspaces:
        return None
    candidates = []
    if tool in WRITE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        candidates.append(_relative(path, workspaces))
    else:
        command = str(tool_input.get("command") or "")
        if not _WRITES.search(command):
            return None
        here = _relative(str(payload.get("cwd") or ""), workspaces)
        for token in _TOKENS.findall(command):
            inside = _relative(token, workspaces)
            if inside is None and here is not None and not re.match(r"^([\\/~]|[A-Za-z]:)", token):
                inside = "/".join(_parts("/".join(filter(None, [here, token]))))
            candidates.append(inside)
    for relative in filter(None, candidates):
        reason = _why(relative, rules)
        if reason:
            return f"{reason} ({relative})"
    return None


def main(argv: list[str] | None = None) -> None:
    """PreToolUse hook. Input it cannot read is let through; a configuration it cannot read is an error, which
    the hook's onFailure turns into a block."""
    parser = argparse.ArgumentParser(description="The project's PreToolUse hook.")
    parser.add_argument("--config", required=True)
    config = project.load(parser.parse_args(argv).config)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    found = decide(payload, config) if isinstance(payload, dict) else None
    if found:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": f"{config.get('display_name') or config['name']}: {found}."}}))
    sys.exit(0)
