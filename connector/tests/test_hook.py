"""The diagnostic hook: what it logs, and the two ways it denies the guard-test markers (H9)."""

import json
import os
import subprocess
import sys

RUN = "from eunomai_business.hook import main; main()"


def run_hook(payload: dict, tmp_path) -> subprocess.CompletedProcess:
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path))
    return subprocess.run([sys.executable, "-c", RUN], input=json.dumps(payload), env=env, capture_output=True,
                          text=True)


def logged(tmp_path) -> dict:
    lines = (tmp_path / "eunomai-business" / "hooks.log").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_ordinary_tool_use_passes_and_logs_names_not_values(tmp_path):
    result = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Read",
                       "tool_input": {"file_path": "C:/private/notes.md"}}, tmp_path)
    assert result.returncode == 0 and result.stdout == ""
    entry = logged(tmp_path)
    assert entry["input_keys"] == ["file_path"] and entry["guard"] is None
    assert "notes.md" not in json.dumps(entry)


def test_json_marker_is_denied_with_a_json_answer(tmp_path):
    result = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Read",
                       "tool_input": {"file_path": "eunomai-guard-test-json.txt"}}, tmp_path)
    answer = json.loads(result.stdout)["hookSpecificOutput"]
    assert result.returncode == 0 and answer["permissionDecision"] == "deny"
    assert logged(tmp_path)["guard"] == "json"


def test_exit2_marker_is_denied_with_exit_code_2(tmp_path):
    result = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": "cat eunomai-guard-test-exit2.txt"}}, tmp_path)
    assert result.returncode == 2 and "guard test" in result.stderr
    assert logged(tmp_path)["guard"] == "exit2"


def test_markers_only_matter_before_a_tool_runs(tmp_path):
    result = run_hook({"hook_event_name": "SessionStart", "tool_input": {"x": "eunomai-guard-test-exit2"}}, tmp_path)
    assert result.returncode == 0 and "SessionStart hook ran" in result.stdout
