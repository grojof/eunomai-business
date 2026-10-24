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


def test_without_diagnostics_no_hooks_and_no_validation_skills(tmp_path):
    archive = build.build(dict(EXAMPLE, diagnostics=False), tmp_path)
    names = zipfile.ZipFile(archive).namelist()
    assert not any(n.startswith("hooks/") for n in names)
    assert not any(n.startswith("skills/validate-") for n in names)
    assert not any("/tests/" in n for n in names)
    mcp = json.loads((tmp_path / "eunomai-business" / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["eunomai-business"]["env"]["EUNOMAI_DIAGNOSTICS"] == "0"


def hook_command(cfg: dict, tmp_path) -> str:
    build.build(cfg, tmp_path)
    hooks = json.loads((tmp_path / "eunomai-business" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_hook_command_is_bare_so_every_shell_runs_it(tmp_path):
    assert hook_command(dict(EXAMPLE, diagnostics=True), tmp_path).startswith("uvx --from ")
    assert (tmp_path / "eunomai-business" / "skills" / "validate-setup" / "SKILL.md").exists()


def test_a_uvx_path_with_spaces_is_quoted(tmp_path):
    cfg = dict(EXAMPLE, diagnostics=True, uvx=r"C:\Users\Some One\.local\bin\uvx.exe")
    assert hook_command(cfg, tmp_path).startswith('"C:/Users/Some One/.local/bin/uvx.exe" --from ')


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
])
def test_configuration_errors_are_reported(change, message):
    cfg = copy.deepcopy(EXAMPLE)
    change(cfg)
    assert any(message in error for error in build.validate(cfg)), build.validate(cfg)
