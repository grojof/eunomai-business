"""Workspaces, versions, save points and pull requests against the fake git server, and the barriers around them."""

import shutil
import uuid
from pathlib import Path

import pytest
from dulwich.object_store import tree_lookup_path
from dulwich.repo import Repo

from eunomai_business import gitops
from eunomai_business.support import NeedsIT


def initialize(server, name: str, default_branch: str = "main") -> Repo:
    return server.initialize(name, default_branch)


def test_empty_repository_is_cloned_but_refuses_versions(signed_in, workspaces):
    signed_in.new_repo("empty")
    cloned = gitops.clone(f"{signed_in.url}/me/empty.git")
    assert cloned["empty_repository"] is True and cloned["remote_branches"] == []
    with pytest.raises(PermissionError, match="no main branch yet"):
        gitops.branch("empty", "first")


def test_user_joins_saves_sends_and_proposes(signed_in, workspaces):
    bare = initialize(signed_in, "joined")
    cloned = gitops.clone(f"{signed_in.url}/me/joined.git")
    ws = Path(cloned["path"])
    assert cloned["remote_branches"] == ["main"] and cloned["main_branch"] == "main"
    # the machine's configuration says autocrlf=true (conftest); the checkout must still be LF
    assert b"\r\n" not in (ws / "README.md").read_bytes()
    assert "autocrlf = false" in (ws / ".git" / "config").read_text()

    gitops.branch("joined", "ana/first")
    with open(ws / "README.md", "ab") as readme:
        readme.write("Línea añadida: canción, pingüino.\n".encode())
    (ws / "notes").mkdir()
    (ws / "notes" / "hello.md").write_bytes(b"hello\n")
    status = gitops.status("joined")
    assert status["unstaged"] == ["README.md"] and status["untracked"] == ["notes/hello.md"]
    assert status["crlf_in_changed_files"] == []

    saved = gitops.save("joined", "First save point")
    assert saved["saved"] and saved["files"] == ["README.md", "notes/hello.md"]
    assert gitops.save("joined", "again") == {"workspace": "joined", "saved": False, "reason": "nothing changed"}

    with pytest.raises(Exception, match="404"):
        gitops.pull_request("joined", "Proposal")  # not sent yet
    sent = gitops.push("joined")
    assert sent["pushed"]

    proposal = gitops.pull_request("joined", "Proposal", "Made in Cowork")
    assert proposal["created"] and proposal["base"] == "main" and proposal["head"] == "ana/first"
    assert gitops.pull_request("joined", "Proposal")["created"] is False

    head = bare[bare.refs[b"refs/heads/ana/first"]]
    _, sha = tree_lookup_path(bare.__getitem__, head.tree, b"README.md")
    assert "canción, pingüino" in bare[sha].data.decode("utf-8")
    assert head.parents == [bare.refs[b"refs/heads/main"]]
    assert head.author == b"Test User <tester@example.test>"
    assert "token-" not in (ws / ".git" / "config").read_text()
    assert set(signed_in.git_auth) == {("tester", True)}


def test_crlf_in_changed_files_is_reported(signed_in, workspaces):
    initialize(signed_in, "crlf")
    ws = Path(gitops.clone(f"{signed_in.url}/me/crlf.git")["path"])
    (ws / "windows.txt").write_bytes(b"a\r\nb\r\n")
    assert gitops.status("crlf")["crlf_in_changed_files"] == ["windows.txt"]


def test_main_branch_is_protected_whatever_its_name(signed_in, workspaces):
    initialize(signed_in, "develop-main", default_branch="develop")
    cloned = gitops.clone(f"{signed_in.url}/me/develop-main.git")
    assert cloned["branch"] == "develop" and cloned["main_branch"] == "develop"
    (Path(cloned["path"]) / "x.md").write_bytes(b"x\n")
    with pytest.raises(PermissionError, match="main branch"):
        gitops.save("develop-main", "straight to develop")
    with pytest.raises(PermissionError):
        gitops.push("develop-main")
    with pytest.raises(PermissionError):
        gitops.pull_request("develop-main", "from develop")
    for name in ("main", "master", "develop"):
        with pytest.raises((PermissionError, FileExistsError)):
            gitops.branch("develop-main", name)


def test_protection_does_not_depend_on_anything_inside_git(signed_in, workspaces):
    initialize(signed_in, "tamper", default_branch="develop")
    ws = Path(gitops.clone(f"{signed_in.url}/me/tamper.git")["path"])
    shutil.rmtree(ws / ".git" / "refs" / "remotes", ignore_errors=True)  # what the sandbox could do
    (ws / ".git" / "packed-refs").unlink(missing_ok=True)
    (ws / "x.md").write_bytes(b"x\n")
    with pytest.raises(PermissionError, match="main branch"):
        gitops.save("tamper", "straight to develop")


def test_workspace_list_survives_a_workspace_without_origin(signed_in, workspaces):
    initialize(signed_in, "no-origin")
    ws = Path(gitops.clone(f"{signed_in.url}/me/no-origin.git")["path"])
    config = (ws / ".git" / "config").read_text(encoding="utf-8")
    (ws / ".git" / "config").write_text(config.split('[remote "origin"]')[0], encoding="utf-8")
    listed = {w["workspace"]: w for w in gitops.workspaces()["workspaces"]}
    assert listed["no-origin"]["origin"] is None


def test_token_goes_only_to_the_git_server(signed_in, workspaces):
    other_host = signed_in.url.replace("127.0.0.1", "localhost")
    with pytest.raises(PermissionError, match="not the signed-in git server"):
        gitops.clone(f"{other_host}/me/x.git")
    with pytest.raises(ValueError, match="credentials"):
        gitops.clone(signed_in.url.replace("http://", "http://u:p@") + "/me/x.git")
    with pytest.raises(ValueError, match="not HTTPS"):
        gitops.clone("http://git.example.test/me/x.git")


@pytest.mark.parametrize("name", ["../evil", "a/b", "", "-x", "x" * 65])
def test_workspace_names_are_plain_folders(workspaces, name):
    with pytest.raises(ValueError):
        gitops._folder(name)


@pytest.mark.parametrize("name", ["a..b", ".hidden", "a/.x", "a//b", "a/", "x.lock", "end.", "-dash", "sp ace"])
def test_version_names_git_would_reject_are_refused(signed_in, workspaces, name):
    repo = f"names-{uuid.uuid4().hex[:8]}"
    initialize(signed_in, repo)
    workspace = gitops.clone(f"{signed_in.url}/me/{repo}.git")["workspace"]
    with pytest.raises(ValueError, match="version name"):
        gitops.branch(workspace, name)


def test_hooks_written_from_the_sandbox_never_run(signed_in, workspaces, monkeypatch):
    initialize(signed_in, "hooks")
    ws = Path(gitops.clone(f"{signed_in.url}/me/hooks.git")["path"])
    for hook in ("pre-commit", "commit-msg", "post-commit"):
        (ws / ".git" / "hooks" / hook).write_text("#!/bin/sh\nexit 0\n")
    import dulwich.hooks
    import subprocess

    def refuse(*args, **kwargs):
        raise AssertionError(f"a hook tried to run: {args}")

    monkeypatch.setattr(dulwich.hooks.subprocess, "call", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    gitops.branch("hooks", "with-hooks")
    (ws / "a.md").write_bytes(b"a\n")
    assert gitops.save("hooks", "hooks are planted")["saved"]


@pytest.mark.parametrize("entry", ['[filter "evil"]\n\tclean = exit 1\n', "[core]\n\thooksPath = elsewhere\n",
                                   "[core]\n\tfsmonitor = true\n", "[include]\n\tpath = other\n"])
def test_unexpected_git_config_stops_every_operation(signed_in, workspaces, entry):
    name = f"config-{uuid.uuid4().hex[:8]}"
    initialize(signed_in, name)
    ws = Path(gitops.clone(f"{signed_in.url}/me/{name}.git")["path"])
    with open(ws / ".git" / "config", "a", encoding="utf-8") as config:
        config.write(entry)
    with pytest.raises(NeedsIT, match="unexpected entry in .git/config"):
        gitops.status(name)
