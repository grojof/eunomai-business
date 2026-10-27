"""The project's hook: denies its protected paths in its own workspaces, and nothing else."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from eunomai_project import guard, rules


@pytest.fixture(autouse=True)
def on_the_users_computer(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_REMOTE_SESSION_ID", raising=False)


def test_the_template_carries_the_connectors_rules_unchanged():
    connector = Path(__file__).parents[4] / "connector" / "src" / "eunomai_business" / "rules.py"
    assert Path(rules.__file__).read_bytes() == connector.read_bytes()


def write(path, tool: str = "Write") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": str(path), "content": "x"}}


def shell(command: str, cwd: str = "/sessions/x/mnt/Ventas", tool: str = "Bash") -> dict:
    return {"tool_name": tool, "cwd": cwd, "tool_input": {"command": command}}


@pytest.mark.parametrize("make, denied", [
    (lambda root: write(root / "Ventas" / "data" / "raw" / "a.csv"), True),
    (lambda root: write(str(root / "VENTAS" / "Data" / "raw" / "a.csv").replace("\\", "/"), "Edit"), True),
    (lambda root: write(root / "ventas-copia" / "uv.lock", "MultiEdit"), True),
    (lambda root: write("/sessions/x/mnt/ventas/data/raw/a.csv"), True),
    (lambda root: write(f"/sessions/x/mnt/{root.name}/Ventas/data/raw/a.csv"), True),
    (lambda root: write("/sessions/x/mnt/Ventas/data/raw/a.csv."), True),
    (lambda root: write("/sessions/x/mnt/Ventas/data/raw/a.csv. :$DATA"), True),
    (lambda root: write("/sessions/x/mnt/Ventas/data/tmp/../raw/a.csv"), True),
    (lambda root: write("/sessions/x/mnt/Ventas/DATA~1/raw/a.csv"), True),
    (lambda root: {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/sessions/x/mnt/Ventas/data/raw/n.ipynb"}},
     True),
    (lambda root: write(root / "Ventas" / "data" / "clean" / "a.csv"), False),
    (lambda root: write(root / "otra" / "data" / "raw" / "a.csv"), False),
    (lambda root: write(root / "suelta" / "data" / "raw" / "a.csv"), False),
    (lambda root: write("C:/Users/me/Downloads/Ventas/data/raw/a.csv"), False),
    (lambda root: write("/sessions/x/mnt/outputs/Ventas/data/raw/a.csv"), False),
    (lambda root: {"tool_name": "Read", "tool_input": {"file_path": "/sessions/x/mnt/Ventas/data/raw/a.csv"}}, False),
    (lambda root: shell("echo x > data/raw/a.csv"), True),
    (lambda root: shell("rm data/raw/a.csv"), True),
    (lambda root: shell("cp a.csv /sessions/x/mnt/ventas/data/raw/a.csv", cwd="/tmp", tool="mcp__workspace__bash"),
     True),
    (lambda root: shell("cat data/raw/a.csv"), False),
    (lambda root: shell("echo x > data/raw/a.csv", cwd="/sessions/x/mnt/otra"), False),
    (lambda root: shell("echo x > /tmp/uv.lock"), False),
])
def test_the_hook_denies_only_protected_paths_in_the_projects_workspaces(config, make, denied):
    assert (guard.decide(make(config["_root"]), config) is not None) == denied


def test_a_workspace_named_like_the_users_profile_is_still_found(config, tmp_path, monkeypatch):
    root = tmp_path / "Ventas" / "eunomai-business-workspaces"  # C:/Users/ventas/...
    (root / "Ventas").mkdir(parents=True)
    registry = {str(root / "Ventas"): {"origin": config["repositories"][0], "main_branch": "main"}}
    data = tmp_path / "data2"
    (data / "eunomai-business").mkdir(parents=True)
    (data / "eunomai-business" / "workspaces.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(data))
    assert guard.decide(write(root / "Ventas" / "data" / "raw" / "a.csv"), config) is not None


def test_without_rules_nothing_is_denied(config):
    assert guard.decide(write(config["_root"] / "Ventas" / "data" / "raw" / "a.csv"), dict(config, deny=[])) is None


def run_hook(monkeypatch, capsys, tmp_path, config, payload) -> dict | None:
    path = tmp_path / "project.json"
    path.write_text(json.dumps({k: v for k, v in config.items() if k != "_root"}), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload if isinstance(payload, str) else json.dumps(payload)))
    with pytest.raises(SystemExit) as done:
        guard.main(["--config", str(path)])
    assert done.value.code == 0
    out = capsys.readouterr().out
    return json.loads(out) if out.strip() else None


def test_the_hook_only_ever_denies(monkeypatch, capsys, tmp_path, config):
    answer = run_hook(monkeypatch, capsys, tmp_path, config, write("/sessions/x/mnt/Ventas/data/raw/a.csv"))
    assert answer["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "Example project: the project keeps these as they are (data/raw/a.csv)."}
    for payload in (write("/sessions/x/mnt/Ventas/app.py"), "not json", "[1]"):
        assert run_hook(monkeypatch, capsys, tmp_path, config, payload) is None


def test_a_task_in_the_cloud_is_refused_whatever_it_does(monkeypatch, capsys, tmp_path, config):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    for payload in (write("/sessions/x/mnt/Ventas/app.py"), {"tool_name": "mcp__plugin_example_example__ask"}):
        reason = run_hook(monkeypatch, capsys, tmp_path, config, payload)["hookSpecificOutput"]
        assert "in the cloud" in reason["permissionDecisionReason"]
    assert guard.decide(write("/sessions/x/mnt/Ventas/app.py"), dict(config, deny=[])) is not None


def test_the_hook_covers_the_projects_tools_and_nothing_else():
    import re
    text = (Path(__file__).parents[2] / "plugin" / "hooks" / "hooks.json.template").read_text(encoding="utf-8")
    matcher = json.loads(text.replace("{{NAME}}", "data"))["hooks"]["PreToolUse"][0]["matcher"]
    for tool in ("Write", "mcp__workspace__bash", "mcp__data__ask", "mcp__plugin_data_data__ask"):
        assert re.search(matcher, tool), tool
    for tool in ("TodoWrite", "mcp__plugin_other_db__export_data", "mcp__plugin_data-x_y__z", "mcp__database__q"):
        assert not re.search(matcher, tool), tool


def test_an_unreadable_configuration_fails_so_the_hook_blocks(monkeypatch, tmp_path):
    (tmp_path / "project.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    with pytest.raises(ValueError):
        guard.main(["--config", str(tmp_path / "project.json")])


def test_the_hook_runs_with_the_standard_library_only(tmp_path, config):
    """hook.py, as uv starts it: a plain Python without the server's environment (-I: no site packages)."""
    path = tmp_path / "project.json"
    path.write_text(json.dumps({k: v for k, v in config.items() if k != "_root"}), encoding="utf-8")
    hook = Path(__file__).resolve().parents[1] / "hook.py"
    done = subprocess.run([sys.executable, "-I", "-S", str(hook), "--config", str(path)],
                          input=json.dumps(write("/sessions/x/mnt/Ventas/data/raw/a.csv")), capture_output=True,
                          text=True, env={"LOCALAPPDATA": str(Path(str(config["_root"])).parent / "localappdata"),
                                          "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
