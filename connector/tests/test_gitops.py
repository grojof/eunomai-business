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

    gitops.branch("joined", "draft/first")
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
    sent = gitops.push("joined", gitops.project_files("joined")["tip"])
    assert sent["pushed"]

    proposal = gitops.pull_request("joined", "Proposal", "Made in Cowork")
    assert proposal["created"] and proposal["base"] == "main" and proposal["head"] == "draft/first"
    assert gitops.pull_request("joined", "Proposal")["created"] is False

    head = bare[bare.refs[b"refs/heads/draft/first"]]
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
        gitops.push("develop-main", gitops.project_files("develop-main")["tip"])
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


def test_the_repository_address_comes_from_the_connector_not_from_git(signed_in, workspaces):
    """The sandbox rewrites the origin to send the user's work elsewhere on the same server: nothing goes there."""
    initialize(signed_in, "redirected")
    ws = Path(gitops.clone(f"{signed_in.url}/me/redirected.git")["path"])
    config = (ws / ".git" / "config").read_text(encoding="utf-8")
    (ws / ".git" / "config").write_text(config.replace("/me/redirected.git", "/me/attacker.git"), encoding="utf-8")
    listed = {w["workspace"]: w for w in gitops.workspaces()["workspaces"]}
    assert listed["redirected"]["origin"].endswith("/me/redirected.git")
    with pytest.raises(NeedsIT, match="address in .git/config changed"):
        gitops.status("redirected")


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


def test_config_written_during_an_operation_never_runs_a_command(signed_in, workspaces, monkeypatch, tmp_path):
    """The sandbox writes a filter into .git/config after the connector checked it: the filter must not run."""
    import sys

    initialize(signed_in, "race")
    ws = Path(gitops.clone(f"{signed_in.url}/me/race.git")["path"])
    gitops.branch("race", "draft/race")
    marker = tmp_path / "filter-ran"
    script = tmp_path / "evil.py"
    script.write_text(f"import sys\nopen(r'{marker}', 'w').write('ran')\nsys.stdout.write(sys.stdin.read())\n")
    original_status = gitops.status

    def status_then_attack(workspace):
        result = original_status(workspace)
        with open(ws / ".git" / "config", "a", encoding="utf-8") as config:
            config.write(f'[filter "x"]\n\tclean = "{Path(sys.executable).as_posix()}" "{script.as_posix()}"\n')
        (ws / ".gitattributes").write_text("*.txt filter=x\n")
        return result

    monkeypatch.setattr(gitops, "status", status_then_attack)
    (ws / "note.txt").write_bytes(b"hello\n")
    gitops.save("race", "With a planted filter")
    assert not marker.exists(), "a filter written after the check ran on the host"


@pytest.mark.parametrize("name", ["Main", "MASTER"])
def test_version_names_differing_only_in_case_from_main_are_refused(signed_in, workspaces, name):
    repo = f"case-{uuid.uuid4().hex[:8]}"
    initialize(signed_in, repo)
    gitops.clone(f"{signed_in.url}/me/{repo}.git")
    with pytest.raises(PermissionError, match="main branch"):
        gitops.branch(repo, name)


@pytest.mark.parametrize("planted", ["commondir", "objects/info/alternates"])
def test_a_repository_pointing_elsewhere_is_refused(signed_in, workspaces, planted):
    repo = f"elsewhere-{uuid.uuid4().hex[:8]}"
    initialize(signed_in, repo)
    ws = Path(gitops.clone(f"{signed_in.url}/me/{repo}.git")["path"])
    target = ws / ".git" / planted
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(workspaces), encoding="utf-8")
    with pytest.raises(NeedsIT, match="another folder"):
        gitops.status(repo)


@pytest.mark.parametrize("name", ["con", "NUL", "com1", "lpt9.txt"])
def test_windows_reserved_names_are_not_workspaces(workspaces, name):
    with pytest.raises(ValueError):
        gitops._folder(name)


def test_empty_credentials_in_the_address_are_refused(signed_in, workspaces):
    with pytest.raises(ValueError, match="credentials"):
        gitops.clone(signed_in.url.replace("http://", "http://:token@") + "/me/x.git")


def test_one_operation_at_a_time_per_workspace(signed_in, workspaces, monkeypatch):
    initialize(signed_in, "busy")
    gitops.clone(f"{signed_in.url}/me/busy.git")
    import threading

    started, release = threading.Event(), threading.Event()

    def hold():
        with gitops._exclusive("workspace:busy"):
            started.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    started.wait(5)
    try:
        with pytest.raises(PermissionError, match="still running"):
            with gitops._exclusive("workspace:busy", wait=0.3):
                pass
    finally:
        release.set()
        holder.join()
