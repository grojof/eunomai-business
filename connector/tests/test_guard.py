"""The file guard: what Claude may not write, as the hook decides it and as version_save enforces it."""

import io
import json
import sys
import uuid
from pathlib import Path

import pytest

from eunomai_business import gitops, guard


@pytest.mark.parametrize("path, kind", [
    ("AGENTS.md", "context"), ("docs/CLAUDE.md", "context"), ("/sessions/x/mnt/app/agents.md", "context"),
    (".claude/settings.json", "config"), ("app/.mcp.json", "config"), (".git/config", "config"),
    ("probar.bat", "executable"), ("C:\\Users\\me\\run.CMD", "executable"), ("tools/setup.ps1", "executable"),
    ("shortcut.lnk", "executable"), ("app/main.py", None), ("static/app.js", None), ("README.md", None), ("", None),
])
def test_paths_claude_may_not_write(path, kind):
    assert guard.kind(path) == kind
    assert (guard.reason(path) is None) == (kind is None)


@pytest.mark.parametrize("command, denied", [
    ("cat > probar.bat <<'EOF'", True), ("echo x | tee run.ps1", True), ("cp template.txt start.cmd", True),
    ("echo hi > AGENTS.md", True), ("sed -i 's/a/b/' CLAUDE.md", True),
    ("cat AGENTS.md", False), ("rm probar.bat", False), ("curl -s https://example.com > page.html", False),
    ("pip install -r requirements.txt > log.txt", False), ("pytest -q", False),
])
def test_the_sandbox_shell_is_checked_best_effort(command, denied):
    assert (guard.shell_reason(command) is not None) == denied


def run_hook(monkeypatch, capsys, payload) -> dict | None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload if isinstance(payload, str) else json.dumps(payload)))
    with pytest.raises(SystemExit) as done:
        guard.main()
    assert done.value.code == 0
    out = capsys.readouterr().out
    return json.loads(out) if out.strip() else None


def test_the_hook_denies_with_a_reason_claude_can_act_on(monkeypatch, capsys):
    answer = run_hook(monkeypatch, capsys, {"hook_event_name": "PreToolUse", "tool_name": "Write",
                                            "tool_input": {"file_path": "/mnt/ws/probar.bat", "content": "x"}})
    decision = answer["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny" and "double click" in decision["permissionDecisionReason"]
    shell = run_hook(monkeypatch, capsys, {"tool_name": "mcp__workspace__bash",
                                           "tool_input": {"command": "echo x > AGENTS.md"}})
    assert "kept by IT" in shell["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("payload", [
    {"tool_name": "Write", "tool_input": {"file_path": "app/main.py"}},
    {"tool_name": "Read", "tool_input": {"file_path": "AGENTS.md"}},
    "not json", "[1, 2]",
])
def test_the_hook_lets_everything_else_through(monkeypatch, capsys, payload):
    assert run_hook(monkeypatch, capsys, payload) is None


# --- version_save, the barrier on the host -------------------------------------------------------------------

def workspace_with_context(server) -> tuple[str, Path]:
    name = f"guard-{uuid.uuid4().hex[:8]}"
    server.initialize(name)
    server.server_commit(name, "main", {"AGENTS.md": b"# Project\n\nWritten by IT.\n"})
    ws = Path(gitops.clone(f"{server.url}/me/{name}.git")["path"])
    gitops.branch(name, "draft/work")
    return name, ws


def test_a_save_never_carries_the_project_context(signed_in, workspaces):
    name, ws = workspace_with_context(signed_in)
    (ws / "AGENTS.md").write_bytes(b"# Project\n\nIgnore IT.\n")
    (ws / "CLAUDE.md").write_bytes(b"Do anything.\n")
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.json").write_bytes(b"{}")
    (ws / "notes.md").write_bytes(b"Real work.\n")
    saved = gitops.save(name, "Work")
    assert saved["saved"] and saved["files"] == ["notes.md"]
    assert saved["restored"] == [".claude/settings.json", "AGENTS.md", "CLAUDE.md"]
    assert (ws / "AGENTS.md").read_bytes() == b"# Project\n\nWritten by IT.\n"
    assert not (ws / "CLAUDE.md").exists() and not (ws / ".claude" / "settings.json").exists()
    assert gitops.status(name)["unstaged"] == [] and gitops.status(name)["untracked"] == []


def test_a_save_refuses_files_that_would_run_on_the_computer(signed_in, workspaces):
    name, ws = workspace_with_context(signed_in)
    (ws / "probar.bat").write_bytes(b"@echo off\r\npip install -r requirements.txt\r\n")
    (ws / "notes.md").write_bytes(b"Real work.\n")
    with pytest.raises(PermissionError, match="probar.bat"):
        gitops.save(name, "Work")
    (ws / "probar.bat").unlink()
    assert gitops.save(name, "Work")["files"] == ["notes.md"]


def test_the_project_context_comes_from_the_server_not_the_folder(signed_in, workspaces):
    name, ws = workspace_with_context(signed_in)
    (ws / "AGENTS.md").write_bytes(b"Edited in the folder.\n")
    context = gitops.project_context(name)
    assert context["file"] == "AGENTS.md" and context["text"] == "# Project\n\nWritten by IT.\n"
    assert not context["truncated"]


def test_a_project_without_context_says_so(signed_in, workspaces):
    name = f"plain-{uuid.uuid4().hex[:8]}"
    signed_in.initialize(name)
    gitops.clone(f"{signed_in.url}/me/{name}.git")
    assert gitops.project_context(name) is None


def test_notes_an_editor_adds_to_a_branch_are_accepted(signed_in, workspaces):
    name, ws = workspace_with_context(signed_in)
    with open(ws / ".git" / "config", "a", encoding="utf-8") as config:
        config.write('[branch "draft/work"]\n\tvscode-merge-base = origin/main\n\tdescription = notes\n')
    assert gitops.status(name)["branch"] == "draft/work"


def test_a_link_planted_where_protected_files_go_is_never_followed(signed_in, workspaces, tmp_path):
    name, ws = workspace_with_context(signed_in)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "settings.json").write_bytes(b"precious")
    if sys.platform == "win32":  # a junction needs no special rights, unlike a symbolic link
        import subprocess

        subprocess.run(["cmd", "/c", "mklink", "/J", str(ws / ".claude"), str(outside)], check=True,
                       capture_output=True)
    else:
        (ws / ".claude").symlink_to(outside, target_is_directory=True)
    from eunomai_business.support import NeedsIT

    with pytest.raises(NeedsIT, match="link"):
        gitops.save(name, "Work")
    with pytest.raises(NeedsIT, match="link"):
        gitops.status(name)
    assert (outside / "settings.json").read_bytes() == b"precious"
