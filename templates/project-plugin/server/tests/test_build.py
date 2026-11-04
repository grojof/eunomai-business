"""The template's build: what IT configures, and the plugin it makes."""

import copy
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("project_build", HERE / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
EXAMPLE = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))


def test_the_example_configuration_is_valid():
    assert build.validate(EXAMPLE) == []


@pytest.mark.parametrize("change, message", [
    (lambda c: c.update(typo=1), "unknown setting 'typo'"),
    (lambda c: c.update(name="Example Project"), "name must be lowercase"),
    (lambda c: c.update(name="eunomai-business"), "not eunomai-business"),
    (lambda c: c.update(display_name="Example: project"), "display_name must be"),
    (lambda c: c.update(version="1.0"), "version must be"),
    (lambda c: c.update(repositories=[]), "repositories must list"),
    (lambda c: c.update(repositories=["http://git.example.test/a"]), "https address"),
    (lambda c: c.update(repositories=["https://me:pw@git.example.test/a"]), "without credentials"),
    (lambda c: c.update(deny=[{"rule": "Edit(//etc/x)", "reason": "r"}]), "relative to the workspace"),
    (lambda c: c.update(deny=[{"rule": "Edit(a/../../b)", "reason": "r"}]), "relative to the workspace"),
    (lambda c: c.update(deny=[{"rule": "Edit(data\\raw\\**)", "reason": "r"}]), "relative to the workspace"),
    (lambda c: c.update(deny=[{"paths": ["data/raw/**"], "reason": "r"}]), "the old form"),
    (lambda c: c.update(deny=[{"rule": "Read(x)", "reason": "r"}]), "is not Bash"),
    (lambda c: c.update(deny=[{"rule": "Bash(npm *)", "reason": "r", "examples": {"denied": ["pip x"]}}]),
     "does not deny its example"),
    (lambda c: c.update(uv='uv" & calc & "'), "uv must be a plain path"),
    (lambda c: c.update(repositories=["https://ghp_abc@git.example.test/a"]), "without credentials"),
    (lambda c: c["settings"].update(dsn="postgresql://u:p/w@db.example.test/x"), "looks like a secret"),
    (lambda c: c["settings"].update(header="Bearer abc"), "looks like a secret"),
    (lambda c: c["settings"].update(db_pwd="x"), "looks like a secret"),
    (lambda c: c["settings"].update(access_key="x"), "looks like a secret"),
    (lambda c: c.update(deny=[{"rule": "Edit(a)", "reason": "r", "allow": True}]), "must have rule and reason"),
    (lambda c: c.update(deny=[{"rule": "Edit(a)", "reason": ""}]), "reason must be one line"),
    (lambda c: c["settings"].update(db_password="x"), "looks like a secret"),
    (lambda c: c["settings"].update(api_url="https://u:p@api.example.test"), "looks like a secret"),
    (lambda c: c["settings"].update(hosts=["a"]), "must be text, a number"),
])
def test_configuration_errors_are_reported(change, message):
    cfg = copy.deepcopy(EXAMPLE)
    change(cfg)
    assert any(message in error for error in build.validate(cfg)), build.validate(cfg)


def test_the_plugin_depends_on_eunomai_business_and_carries_no_tests(tmp_path):
    cfg = dict(copy.deepcopy(EXAMPLE), uv="C:\\Program Files\\uv\\uv.exe")
    archive = build.build(cfg, tmp_path)
    with zipfile.ZipFile(archive) as built:
        names = set(built.namelist())
        manifest = json.loads(built.read(".claude-plugin/plugin.json"))
        assert manifest == {"name": "example-project", "version": "0.1.0", "description": EXAMPLE["description"],
                            "dependencies": ["eunomai-business"]}
        hooks = json.loads(built.read("hooks/hooks.json"))
        command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert command.startswith('"C:/Program Files/uv/uv.exe" run --no-project ') and "server/hook.py" in command
        servers = json.loads(built.read(".mcp.json"))["mcpServers"]
        assert list(servers) == ["example-project"] and servers["example-project"]["command"].endswith("uv.exe")
        assert json.loads(built.read("project.json"))["deny"] == EXAMPLE["deny"]
        skill = built.read("skills/project/SKILL.md").decode()
        assert "{{" not in skill and "Example project" in skill
        assert "server/uv.lock" in names and "server/src/eunomai_project/guard.py" in names
        assert not any("tests/" in name or name.endswith(".template") or "__pycache__" in name for name in names)
        for name in names:
            if name.endswith((".json", ".md", ".py", ".toml")):
                assert b"\r" not in built.read(name), name


def test_a_project_plugin_depends_on_the_organizations_base_plugin_by_its_name(tmp_path):
    cfg = dict(copy.deepcopy(EXAMPLE), base_plugin="acme-apps")
    archive = build.build(cfg, tmp_path)
    with zipfile.ZipFile(archive) as built:
        assert json.loads(built.read(".claude-plugin/plugin.json"))["dependencies"] == ["acme-apps"]
        assert json.loads(built.read("project.json"))["base_plugin"] == "acme-apps"


@pytest.mark.parametrize("base", ["Acme", "acme apps", "../acme", "", 5])
def test_a_base_plugin_that_is_not_a_plugins_name_is_refused(base):
    errors = build.validate(dict(copy.deepcopy(EXAMPLE), base_plugin=base))
    assert any(error.startswith("base_plugin:") for error in errors)


def test_a_project_plugin_cannot_take_its_base_plugins_name():
    errors = build.validate(dict(copy.deepcopy(EXAMPLE), base_plugin="acme-apps", name="acme-apps"))
    assert any("and not acme-apps" in error for error in errors)

