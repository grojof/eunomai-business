"""The project plugin's own PreToolUse hook: denies one marker file name, and records every consultation with the
plugin it came from, so the test can tell whether this hook and eunomai-business's guard both run on the same call."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MARKER = "eunomai-project-spike-guard.txt"


def log_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "eunomai-project-spike" / "guard.log"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    payload = payload if isinstance(payload, dict) else {}
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("command") or "")
    denied = MARKER in target.lower()
    try:
        log_file().parent.mkdir(parents=True, exist_ok=True)
        with log_file().open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                  "plugin": os.environ.get("CLAUDE_PLUGIN_ROOT"), "tool": payload.get("tool_name"),
                                  "target": target[:200], "denied": denied}) + "\n")
    except OSError:
        pass
    if denied:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "eunomai-project-spike: this file name is reserved by the project plugin."}}))
    sys.exit(0)
