"""Several plugins built from eunomai-business on one computer: each keeps its own folder, sign-ins, workspaces,
requests and previews, named after the plugin the build named. Without a name, the original one."""

from pathlib import Path

import pytest

from eunomai_business import DEFAULT_PLUGIN, data_dir, gitops, plugin_name


def test_without_a_name_the_plugin_is_the_original_one(monkeypatch):
    monkeypatch.delenv("EUNOMAI_PLUGIN", raising=False)
    assert plugin_name() == DEFAULT_PLUGIN == "eunomai-business"
    assert data_dir().name == "eunomai-business"


@pytest.mark.parametrize("name", ["Acme", "../acme", "acme apps", "acme\\apps", "a" * 41, ""])
def test_a_name_that_is_not_plain_never_reaches_a_path(monkeypatch, name):
    monkeypatch.setenv("EUNOMAI_PLUGIN", name)
    assert plugin_name() == DEFAULT_PLUGIN


def test_two_plugins_never_share_a_folder(monkeypatch):
    monkeypatch.setenv("EUNOMAI_PLUGIN", "acme-crm")
    crm = data_dir()
    (crm / "workspaces.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EUNOMAI_PLUGIN", "acme-shop")
    shop = data_dir()
    assert crm != shop and crm.parent == shop.parent and (crm.name, shop.name) == ("acme-crm", "acme-shop")
    assert not (shop / "workspaces.json").exists()


def test_each_plugin_has_its_own_workspaces_folder_unless_one_is_set(monkeypatch):
    monkeypatch.delenv("EUNOMAI_WORKSPACES_ROOT", raising=False)
    monkeypatch.setenv("EUNOMAI_PLUGIN", "acme-web")
    assert gitops.root() == Path.home() / "acme-web-workspaces"
    monkeypatch.setenv("EUNOMAI_WORKSPACES_ROOT", str(Path.home() / "web"))
    assert gitops.root() == Path.home() / "web"


def test_a_plugins_sign_ins_are_its_own(monkeypatch):
    """Where sign-ins live: the plugin's folder on Windows, a keyring entry named after the plugin elsewhere."""
    import importlib

    from eunomai_business import store

    monkeypatch.setenv("EUNOMAI_PLUGIN", "acme-web")
    try:
        reloaded = importlib.reload(store)
        assert reloaded._SERVICE == "acme-web"
    finally:
        monkeypatch.delenv("EUNOMAI_PLUGIN")
        importlib.reload(store)


def test_a_request_and_a_report_are_named_after_the_plugin(monkeypatch):
    from eunomai_business import project_request

    monkeypatch.setenv("EUNOMAI_PLUGIN", "acme-apps")
    fields = {"name": "orders", "request": "orders", "requester": "", "created": "2026-11-04T10:00:00+0100",
              "language": "en", "purpose": "p", "users": "u", "today": "t", "first_version": "f",
              "out_of_scope": "", "open_questions": []}
    subject, _ = project_request.message(fields)
    assert subject == "acme-apps: new project request: orders"
