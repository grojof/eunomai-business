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
    assert list(hooks) == ["PreToolUse"] and len(hooks["PreToolUse"]) == 1
    guard = hooks["PreToolUse"][0]
    assert "Write" in guard["matcher"] and "mcp__workspace__bash" in guard["matcher"]
    assert guard["hooks"][0]["command"].endswith("eunomai-business-guard")
    assert guard["hooks"][0]["onFailure"] == "continue"
    assert not any(n.startswith("skills/validate-") for n in names)
    assert "skills/specialist/SKILL.md" in names and "skills/specialist/references/specify.md" in names
    assert "skills/review-skills/SKILL.md" in names
    assert not any("/tests/" in n for n in names)
    mcp = json.loads((tmp_path / "eunomai-business" / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["eunomai-business"]["env"]["EUNOMAI_DIAGNOSTICS"] == "0"
    args = mcp["mcpServers"]["eunomai-business"]["args"]
    assert args[:2] == ["run", "--frozen"] and "--no-config" in args and "--native-tls" in args
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


@pytest.mark.parametrize("change, message", [
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
    (lambda c: c.update(projects={"http://git.example.test/a": {"technologies": []}}), "must be an https"),
    (lambda c: c.update(dependency_exceptions=[{"package": "pypi:six"}]), 'needs "package"'),
    (lambda c: c.update(organization_context=["text"]), "organization_context must be text"),
    (lambda c: c.update(organization_skills=[{"skill": "brand:web"}]), "organization_skills must be a list"),
])
def test_configuration_errors_are_reported(change, message):
    cfg = copy.deepcopy(EXAMPLE)
    change(cfg)
    assert any(message in error for error in build.validate(cfg)), build.validate(cfg)
