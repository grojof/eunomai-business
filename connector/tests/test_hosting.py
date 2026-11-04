"""The git hosting's API behind one interface: Gitea implements it, GitHub and GitLab are refused by the build and at
start-up until each has its class, and no call to a hosting's API is made anywhere else."""

import ast
import json
import sys
from pathlib import Path

import pytest

from eunomai_business import gitops, hosting, server

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "connector" / "src" / "eunomai_business"
sys.path.insert(0, str(ROOT / "tools"))
import build  # noqa: E402

EXAMPLE = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))


def test_gitea_is_the_default_and_works(monkeypatch):
    monkeypatch.delenv("EUNOMAI_PLATFORM", raising=False)
    assert hosting.platform_name() == "gitea" and hosting.refusal("gitea") is None
    made = hosting.for_origin("https://git.example.org/tools/acme/orders.git", "a-token")
    assert isinstance(made, hosting.Gitea)
    assert made.api == "https://git.example.org/tools/api/v1/repos/acme/orders", "a server under a sub-path"


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_a_platform_with_no_code_yet_is_refused_before_the_server_is_asked(monkeypatch, platform):
    monkeypatch.setenv("EUNOMAI_PLATFORM", platform)
    with pytest.raises(hosting.NotSupported, match=f"{platform} is not supported yet: it needs a "):
        hosting.for_origin("https://git.example.org/acme/orders.git", "a-token")


def test_an_unknown_platform_is_named_with_the_ones_there_are():
    assert "is not a hosting platform this connector knows: gitea, github, gitlab" in hosting.refusal("bitbucket")


@pytest.mark.parametrize("platform", ["github", "gitlab", "bitbucket"])
def test_the_connector_does_not_start_with_a_platform_it_has_no_code_for(monkeypatch, platform):
    monkeypatch.setenv("EUNOMAI_PLATFORM", platform)
    started = []
    monkeypatch.setattr(server.mcp, "run", lambda *arguments: started.append(arguments))
    with pytest.raises(SystemExit, match=platform):
        server.main()
    assert not started


def test_the_connector_starts_with_gitea(monkeypatch):
    monkeypatch.setenv("EUNOMAI_PLATFORM", "gitea")
    started = []
    monkeypatch.setattr(server.mcp, "run", lambda *arguments: started.append(arguments))
    server.main()
    assert started == [("stdio",)]


def test_the_interface_is_every_operation_the_connector_asks_of_a_hosting():
    """What gitops asks of `_hosting(...)` is the interface, all of it, so a new platform cannot forget one."""
    tree = ast.parse((SOURCE / "gitops.py").read_text(encoding="utf-8"))
    asked = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call)
             and isinstance(node.func.value.func, ast.Name) and node.func.value.func.id == "_hosting"}
    assert asked == set(hosting.Hosting.OPERATIONS)
    declared = {name for name, value in vars(hosting.Hosting).items() if callable(value) and not name.startswith("_")}
    assert declared == set(hosting.Hosting.OPERATIONS)
    for name, platform in hosting.PLATFORMS.items():
        missing = [operation for operation in hosting.Hosting.OPERATIONS
                   if getattr(platform, operation) is getattr(hosting.Hosting, operation)]
        assert not missing, f"{name} does not implement {missing}"
    assert not set(hosting.PLATFORMS) & set(hosting.NOT_YET)


def test_no_hosting_api_is_called_outside_its_class():
    """Plain git (clone, fetch, push) and sign-in stay where they are; a platform's REST API lives in hosting.py."""
    for path in SOURCE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name == "hosting.py":
            start, end = text.index("class Gitea(Hosting):"), text.index("PLATFORMS: dict")
            text = text[:start] + text[end:]
        assert "/api/v1" not in text and "/pulls" not in text and "/api/v4" not in text, path.name
    assert not hasattr(gitops, "_api") and not hasattr(gitops, "_review_of")


def test_the_build_refuses_the_same_platforms_with_the_same_words():
    assert build.PLATFORMS == tuple(hosting.PLATFORMS)
    assert build.NOT_YET == hosting.NOT_YET
    for platform in hosting.NOT_YET:
        errors = build.validate(dict(EXAMPLE, platform=platform))
        assert f"platform: {platform} is not supported yet: {hosting.NOT_YET[platform]}" in errors
    assert any(error.startswith("platform is one of") for error in build.validate(dict(EXAMPLE, platform="svn")))
    assert EXAMPLE["platform"] == "gitea" and build.validate(EXAMPLE) == []


def test_the_build_tells_the_connector_its_platform(tmp_path):
    build.build(dict(EXAMPLE), tmp_path)
    plugin = EXAMPLE.get("plugin_name") or build.DEFAULT_PLUGIN
    mcp = json.loads((tmp_path / plugin / ".mcp.json").read_text(encoding="utf-8"))
    [entry] = mcp["mcpServers"].values()
    assert entry["env"]["EUNOMAI_PLATFORM"] == "gitea"
