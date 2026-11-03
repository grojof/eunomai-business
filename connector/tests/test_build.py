"""The build tool: configuration checks, diagnostics on and off, quoting, line endings."""

import copy
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build  # noqa: E402

EXAMPLE = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))


def test_example_configuration_is_valid():
    assert build.validate(EXAMPLE) == []


def test_without_diagnostics_only_the_guard_and_no_validation_skills(tmp_path):
    archive = build.build(dict(EXAMPLE, diagnostics=False), tmp_path)
    names = zipfile.ZipFile(archive).namelist()
    assert [n for n in names if n.startswith("hooks/")] == ["hooks/hooks.json"]
    hooks = json.loads((tmp_path / "eunomai-business" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert list(hooks) == ["SessionStart", "UserPromptSubmit", "PreToolUse"]  # the guard alone, on three events
    assert all(len(entries) == 1 for entries in hooks.values())
    guard_command = 'eunomai-business-guard --policy "${CLAUDE_PLUGIN_ROOT}/policy.json"'
    assert all(e[0]["hooks"][0]["command"].endswith(guard_command) for e in hooks.values())
    guard = hooks["PreToolUse"][0]
    assert "Write" in guard["matcher"] and "mcp__workspace__bash" in guard["matcher"]
    assert guard["hooks"][0]["onFailure"] == "block"  # a guard that cannot run stops the write
    assert not any(n.startswith("skills/validate-") for n in names)
    assert "skills/specialist/SKILL.md" in names and "skills/specialist/references/specify.md" in names
    assert "skills/review-skills/SKILL.md" in names
    assert not any("/tests/" in n for n in names)
    mcp = json.loads((tmp_path / "eunomai-business" / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["eunomai-business"]["env"]["EUNOMAI_DIAGNOSTICS"] == "0"
    args = mcp["mcpServers"]["eunomai-business"]["args"]
    assert args[:2] == ["run", "--frozen"] and "--no-config" in args and "--system-certs" in args
    assert "--managed-python" in args  # uv's own Python, never whatever the computer has
    assert args[args.index("--project") + 1] == "${CLAUDE_PLUGIN_ROOT}/connector"
    assert "connector/uv.lock" in names and "connector/sbom.cdx.json" in names


def hook_command(cfg: dict, tmp_path) -> str:
    build.build(cfg, tmp_path)
    hooks = json.loads((tmp_path / "eunomai-business" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert {"SessionStart", "PreToolUse"} <= set(hooks["hooks"]) and len(hooks["hooks"]["PreToolUse"]) == 2
    assert not (tmp_path / "eunomai-business" / "hooks" / "diagnostics.json").exists()
    return hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_hook_command_is_bare_so_every_shell_runs_it(tmp_path):
    assert hook_command(dict(EXAMPLE, diagnostics=True), tmp_path).startswith("uv run --frozen ")
    assert (tmp_path / "eunomai-business" / "skills" / "validate-setup" / "SKILL.md").exists()


def test_a_uv_path_with_spaces_is_quoted(tmp_path):
    cfg = dict(EXAMPLE, diagnostics=True, uv=r"C:\Users\Some One\.local\bin\uv.exe")
    assert hook_command(cfg, tmp_path).startswith('"C:/Users/Some One/.local/bin/uv.exe" run --frozen ')


def test_built_text_files_use_lf(tmp_path):
    build.build(dict(EXAMPLE, diagnostics=True), tmp_path)
    for path in (tmp_path / "eunomai-business").rglob("*"):
        if path.is_file() and path.suffix in {".json", ".md", ".py", ".toml"}:
            assert b"\r" not in path.read_bytes(), path


@pytest.mark.parametrize("value", [False, True])
def test_app_preview_reaches_the_connector(tmp_path, value):
    build.build(dict(EXAMPLE, app_preview=value), tmp_path)
    mcp = json.loads((tmp_path / "eunomai-business" / ".mcp.json").read_text(encoding="utf-8"))
    assert json.loads(mcp["mcpServers"]["eunomai-business"]["env"]["EUNOMAI_SPECIALIST"])["app_preview"] is value


@pytest.mark.parametrize("value", [True, False])
def test_app_tests_reaches_the_connector_on_its_own(tmp_path, value):
    build.build(dict(EXAMPLE, app_tests=value), tmp_path)
    mcp = json.loads((tmp_path / "eunomai-business" / ".mcp.json").read_text(encoding="utf-8"))
    specialist = json.loads(mcp["mcpServers"]["eunomai-business"]["env"]["EUNOMAI_SPECIALIST"])
    assert specialist["app_tests"] is value and specialist["app_preview"] is False


def test_the_message_style_reaches_the_connector(tmp_path):
    style = {"accent": "#7a1f5c", "font": "Verdana, sans-serif"}
    build.build(dict(EXAMPLE, message_style=style), tmp_path)
    mcp = json.loads((tmp_path / "eunomai-business" / ".mcp.json").read_text(encoding="utf-8"))
    assert json.loads(mcp["mcpServers"]["eunomai-business"]["env"]["EUNOMAI_SPECIALIST"])["message_style"] == style


@pytest.mark.parametrize("style", [{"accent": "red"}, {"accent": "#7a1f5c;x"}, {"font": "x}body{display:none"},
                                   {"colour": "#7a1f5c"}, {"accent": 5}, "Verdana", None])
def test_a_message_style_that_is_not_a_colour_and_font_names_is_refused(style):
    assert any(error.startswith("message_style takes") for error in build.validate(dict(EXAMPLE, message_style=style)))


def test_app_tests_is_off_in_the_example_and_must_be_true_or_false():
    assert EXAMPLE["app_tests"] is False
    assert "app_tests must be true or false" in build.validate(dict(EXAMPLE, app_tests="yes"))


def test_app_preview_is_off_in_the_example_and_must_be_true_or_false():
    assert EXAMPLE["app_preview"] is False
    assert "app_preview must be true or false" in build.validate(dict(EXAMPLE, app_preview="yes"))


def test_the_organizations_deny_rules_are_packaged_for_the_guard(tmp_path):
    deny = [{"rule": "Bash(npm *)", "reason": "not here", "examples": {"denied": ["npm ci"]}}]
    build.build(dict(EXAMPLE, deny=deny), tmp_path)
    assert json.loads((tmp_path / "eunomai-business" / "policy.json").read_text(encoding="utf-8")) == {"deny": deny}
    build.build({k: v for k, v in EXAMPLE.items() if k != "deny"}, tmp_path / "none")
    assert json.loads((tmp_path / "none" / "eunomai-business" / "policy.json").read_text(encoding="utf-8")) == {
        "deny": []}


@pytest.mark.parametrize("change, message", [
    (lambda c: c.update(deny=[{"rule": "Read(./.env)", "reason": "r"}]), "is not Bash(<command>)"),
    (lambda c: c.update(deny=[{"rule": "Bash(npm *)", "reason": "r", "examples": {"allowed": ["npm ci"]}}]),
     "which its examples allow"),
    (lambda c: c.update(typo_setting=1), "unknown setting 'typo_setting'"),
    (lambda c: c.update(connector_source="bundle"), 'connector_source must be "bundled" or "path"'),
    (lambda c: c.update(diagnostics="yes"), "diagnostics must be true or false"),
    (lambda c: c["providers"].pop("git"), 'at least a "git" provider'),
    (lambda c: c["providers"]["git"].update(token_url="http://git.example.test/t"), "token_url must be https"),
    (lambda c: c["providers"]["git"].update(redirect_uri="https://example.test/cb"), "redirect_uri must be"),
    (lambda c: c["providers"]["git"].update(redirect_uri=c["providers"]["directory"]["redirect_uri"]),
     "same port"),
    (lambda c: c["providers"]["git"].pop("client_id"), "missing client_id"),
    (lambda c: c.update(docs_language="Spanish"), "docs_language must be a language code"),
    (lambda c: c.update(free_development="no"), "free_development must be true or false"),
    (lambda c: c.update(allowed_technologies="Python"), "allowed_technologies must be a list"),
    (lambda c: c.update(projects={}), "each project declares it in .eunomai/project.toml"),
    (lambda c: c.update(dependency_exceptions=[{"package": "pypi:six"}]), 'needs "package"'),
    (lambda c: c.update(organization_context=["text"]), "organization_context must be text"),
    (lambda c: c.update(organization_skills=[{"skill": "brand:web"}]), "organization_skills must be a list"),
])
def test_configuration_errors_are_reported(change, message):
    cfg = copy.deepcopy(EXAMPLE)
    change(cfg)
    assert any(message in error for error in build.validate(cfg)), build.validate(cfg)


# --- variants: one base configuration, several packages ------------------------------------------------------

def test_a_variant_changes_only_what_it_names():
    merged = build.overlay(EXAMPLE, {"diagnostics": True, "providers": {"git": {"client_id": "test-client"}}})
    assert merged["diagnostics"] is True and merged["providers"]["git"]["client_id"] == "test-client"
    assert merged["providers"]["git"]["token_url"] == EXAMPLE["providers"]["git"]["token_url"]
    assert merged["providers"]["directory"] == EXAMPLE["providers"]["directory"]
    assert EXAMPLE["diagnostics"] is False  # the base is untouched


def setup_variants(tmp_path, **variants) -> tuple[Path, Path]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps(EXAMPLE), encoding="utf-8")
    folder = tmp_path / "variants"
    folder.mkdir()
    for name, changes in variants.items():
        (folder / f"{name}.json").write_text(json.dumps(changes), encoding="utf-8")
    return config, folder


def test_every_variant_is_built_in_its_own_folder(tmp_path):
    config, folder = setup_variants(tmp_path, tests={"diagnostics": True}, otra={"support_email": "it@otra.test"})
    out = tmp_path / "dist"
    assert build.main(["--config", str(config), "--variants", str(folder), "--out", str(out), "--all"]) == 0
    assert (out / "eunomai-business.zip").exists()
    assert (out / "tests" / "eunomai-business.zip").exists() and (out / "otra" / "eunomai-business.zip").exists()
    with zipfile.ZipFile(out / "tests" / "eunomai-business.zip") as built:
        assert any(name.startswith("skills/validate-") for name in built.namelist())  # diagnostics on
    with zipfile.ZipFile(out / "eunomai-business.zip") as built:
        assert not any(name.startswith("skills/validate-") for name in built.namelist())


def test_one_variant_alone(tmp_path):
    config, folder = setup_variants(tmp_path, tests={"diagnostics": True})
    out = tmp_path / "dist"
    assert build.main(["--config", str(config), "--variants", str(folder), "--out", str(out), "--variant",
                       "tests"]) == 0
    assert (out / "tests" / "eunomai-business.zip").exists() and not (out / "eunomai-business.zip").exists()


@pytest.mark.parametrize("variants, argument, message", [
    ({"tests": {"diagnostics": "yes"}}, "--all", "in variant tests"),
    ({}, "--variant=missing", "cannot read"),
    ({}, "--variant=../x", "lowercase letters, digits and hyphens"),
    ({"tests": {"projects": {}}}, "--all", ".eunomai/project.toml"),
    ({"eunomai-business": {"diagnostics": True}}, "--all", "not eunomai-business"),
])
def test_a_wrong_variant_builds_nothing(tmp_path, capsys, variants, argument, message):
    config, folder = setup_variants(tmp_path, **variants)
    out = tmp_path / "dist"
    assert build.main(["--config", str(config), "--variants", str(folder), "--out", str(out), argument]) == 1
    assert message in capsys.readouterr().err and not out.exists()
