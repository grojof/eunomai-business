"""Which workspaces are the project's, and the tools that act on them."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from eunomai_project import project, server


def test_the_projects_workspaces_are_the_ones_eunomai_business_registered_from_its_repositories(config):
    found = project.workspaces(config)
    assert [item["workspace"] for item in found] == ["Ventas", "ventas-copia"]  # never .git/config, never "gone"


@pytest.mark.parametrize("registry", [None, "{", "[1]", '{"C:/x": "https://x"}'])
def test_without_a_readable_register_there_are_no_workspaces(config, registry):
    path = project.registry_file()
    if registry is None:
        path.unlink()
    else:
        path.write_text(registry, encoding="utf-8")
    assert project.workspaces(config) == []


def test_tools_act_only_on_the_projects_workspaces(config):
    assert project.own_workspace(config, "ventas").name == "Ventas"
    with pytest.raises(PermissionError, match="not a workspace of Example project"):
        project.own_workspace(config, "otra")
    with pytest.raises(PermissionError):
        project.own_workspace(config, "../otra")


def call(mcp, name: str, arguments: dict | None = None):
    result = asyncio.run(mcp.call_tool(name, arguments or {}))
    return result


def test_the_server_offers_the_templates_tools(config):
    mcp = server.build(config)
    tools = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert {"project_workspaces", "project_rules", "project_example"} <= tools
    rules = call(mcp, "project_rules")
    assert "the project keeps these as they are" in json.dumps(rules.model_dump(mode="json"))


def test_the_example_tool_enforces_its_own_limits(config):
    root = project.own_workspace(config, "Ventas")
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text("x")
    mcp = server.build(config)
    listed = call(mcp, "project_example", {"workspace": "Ventas"}).model_dump(mode="json")
    assert "docs/a.md" in json.dumps(listed)
    with pytest.raises(ToolError, match="must stay inside the workspace"):  # Claude gets the reason
        call(server.build(dict(config, settings={"example_folder": "../otra"})), "project_example",
             {"workspace": "Ventas"})
    with pytest.raises(ToolError, match="not a workspace of Example project"):
        call(mcp, "project_example", {"workspace": "otra"})


def test_async_tools_are_awaited_and_their_limits_reach_claude(config, monkeypatch):
    from eunomai_project import project_tools

    def register(tool, config):
        @tool
        async def project_async(workspace: str) -> dict:
            """An async tool."""
            return {"folder": project.own_workspace(config, workspace).name}

    monkeypatch.setattr(project_tools, "register", register)
    mcp = server.build(config)
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "project_async")
    assert tool.input_schema["required"] == ["workspace"]
    assert "Ventas" in json.dumps(call(mcp, "project_async", {"workspace": "ventas"}).model_dump(mode="json"))
    with pytest.raises(ToolError, match="not a workspace"):
        call(mcp, "project_async", {"workspace": "otra"})


def test_a_failure_that_is_no_limit_keeps_its_details_on_the_computer(config, monkeypatch):
    mcp = server.build(config)
    monkeypatch.setattr(project, "workspaces", lambda config: 1 / 0)
    with pytest.raises(UnexpectedToolError) as failed:
        call(mcp, "project_workspaces")
    assert "division" not in str(failed.value)
