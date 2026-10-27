"""The project's PreToolUse hook: applies the project's deny rules (rules.py) in the project's own workspaces only.
It never allows and never rewrites a call: eunomai-business's guard runs on the same call, and a deny from either
one stops it.

A path is in a workspace when it is under the workspace's folder on the computer, or under its folder as Claude's
sandbox mounts it (.../mnt/<workspace>/...). The file tools are checked always; the sandbox shell best effort, since
a command is only text. Standard library only (see hook.py).
"""

import argparse
import json
import os
import re
import sys

from . import project, rules

# An 8.3 short name (DATABA~1) can stand for a protected folder on Windows.
_SHORT_NAME = re.compile(r"^[^~]{1,6}~[0-9]+(\.[^.]{0,3})?$")
_SHORT_NAME_REASON = "short (8.3) names are not used in this project's workspaces; use the full name"

# The project's server and its internal systems are on the user's computer and its network, which a Cowork task in
# the cloud cannot reach: such a task is refused outright (CLAUDE_CODE_REMOTE is set in cloud sessions).
CLOUD = ("this Cowork task runs in the cloud, and this project only works with tasks on the user's computer. Ask "
         "the user to start a new task on this computer; if Cowork offers no way to, IT has to turn off running "
         "tasks in the cloud for the organization")


def in_the_cloud() -> bool:
    return (os.environ.get("CLAUDE_CODE_REMOTE", "").strip().lower() == "true"
            or bool(os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID", "").strip()))


def decide(payload: dict, config: dict) -> str | None:
    """Why the call may not run, or None."""
    if in_the_cloud():
        return CLOUD
    deny = config.get("deny") or []
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not deny or tool not in rules.WRITE_TOOLS | rules.SHELL_TOOLS:
        return None
    folders = [item["path"] for item in project.workspaces(config)]
    if not folders:
        return None
    cwd = str(payload.get("cwd") or "")
    if tool in rules.WRITE_TOOLS:
        target = rules.relative(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""), folders)
        targets = [target] if target else []
    else:
        here = rules.relative(cwd, folders)
        targets = []
        for _verb, path in rules.shell_writes(str(tool_input.get("command") or "")):
            inside = rules.relative(path, folders)
            if inside is None and here is not None and not re.match(r"^([\\/~]|[A-Za-z]:)", path):
                inside = "/".join(rules.parts("/".join(filter(None, [here, path]))))
            if inside:
                targets.append(inside)
    for target in targets:
        if any(_SHORT_NAME.match(part) for part in target.split("/")):
            return f"{_SHORT_NAME_REASON} ({target})"
    return rules.deny_reason(deny, tool, tool_input, cwd, folders)


def main(argv: list[str] | None = None) -> None:
    """PreToolUse hook. Input it cannot read is let through; a configuration it cannot read is an error, which
    the hook's onFailure turns into a block."""
    parser = argparse.ArgumentParser(description="The project's PreToolUse hook.")
    parser.add_argument("--config", required=True)
    config = project.load(parser.parse_args(argv).config)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {} if in_the_cloud() else None
    found = decide(payload, config) if payload is not None else None
    if found:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": f"{config.get('display_name') or config['name']}: {found}."}}))
    sys.exit(0)
