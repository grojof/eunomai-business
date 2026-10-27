"""The project's test environment: a version tried there without waiting for IT, where the git server allows it."""

import uuid
from pathlib import Path

import pytest
from dulwich.errors import HookError

from eunomai_business import gitops, server as tools, settings
from eunomai_business.support import NeedsIT

DECLARED = b'[development]\ncode = true\n\n[test]\nbranch = "pruebas"\nurl = "https://app-test.example.test"\n'


def declared(text: str) -> dict:
    return {"file": ".eunomai/project.toml", "from": "the main branch on the server", "text": text}


@pytest.mark.parametrize("text, expected", [
    ("", None),
    ('[test]\nbranch = "pruebas"\n', {"branch": "pruebas", "url": ""}),
    ('[test]\nbranch = "test/env"\nurl = "https://t.example.test"\n', {"branch": "test/env",
                                                                      "url": "https://t.example.test"}),
])
def test_a_project_declares_its_test_environment(text, expected):
    assert settings.test(declared(text)) == expected
    assert settings.test(None) is None


@pytest.mark.parametrize("text, reason", [
    ('[test]\nbranch = "main"\n', "other than the main one"),
    ('[test]\nbranch = "a..b"\n', "other than the main one"),
    ('[test]\nbranch = "-x"\n', "other than the main one"),
    ('[test]\nbranch = "Master"\n', "other than the main one"),
    ('[test]\nbranch = "HEAD"\n', "other than the main one"),
    ('[test]\nbranch = "refs/heads/x"\n', "other than the main one"),
    ('[test]\nbranch = "pruebas.lock"\n', "other than the main one"),
    ('[test]\nbranch = "a/.b"\n', "other than the main one"),
    ('[test]\nbranch = "a b"\n', "other than the main one"),
    ('[test]\nbranch = "pruebas"\nurl = "https:foo"\n', "url must be an https"),
    ("[test]\nbranch = 1\n", "other than the main one"),
    ('[test]\nbranch = "pruebas"\nurl = "http://t"\n', "url must be an https"),
    ('[test]\nbranch = "pruebas"\nbranches = ["a"]\n', "takes branch and url only"),
    ("[test\n", "not valid TOML"),
])
def test_a_test_environment_it_cannot_have_meant_is_refused(text, reason):
    assert reason in settings.test(declared(text))["invalid"]


class Refuse:
    """The git server's protection of the test branch, refusing with one of Gitea's reasons."""

    def __init__(self, reason: str = "Not allowed to push to protected branch pruebas"):
        self.reason = reason

    def execute(self, ref, old, new):
        if ref == b"refs/heads/pruebas":
            raise HookError(self.reason)
        return None, None


def version(server, declaration: bytes = DECLARED) -> tuple[str, Path]:
    name = f"try-{uuid.uuid4().hex[:8]}"
    server.initialize(name)
    server.server_commit(name, "main", {".eunomai/project.toml": declaration, "AGENTS.md": b"# Project\n"})
    ws = Path(gitops.clone(f"{server.url}/me/{name}.git")["path"])
    gitops.branch(name, "draft/work")
    (ws / "app.py").write_bytes(b"print('hola')\n")
    gitops.save(name, "Work")
    return name, ws


def test_a_saved_version_replaces_what_the_test_branch_had(signed_in, workspaces):
    name, ws = version(signed_in)
    signed_in.server_commit(name, "main", {"other.md": b"x"})  # someone else's work...
    gitops.update(name)  # ...brought in
    signed_in.repos[name].refs[b"refs/heads/pruebas"] = signed_in.repos[name].refs[b"refs/heads/main"]
    result = tools._to_test(name)
    assert result["status"] == "sent" and result["branch"] == "pruebas"
    assert result["url"] == "https://app-test.example.test"
    with gitops._repo(name) as repo:
        head = repo.head()
    assert signed_in.repos[name].refs[b"refs/heads/pruebas"] == head
    assert signed_in.repos[name].refs[b"refs/heads/main"] != head  # main changes only through a pull request


def test_the_specialist_learns_of_the_test_environment(signed_in, workspaces):
    name, _ = version(signed_in)
    assert tools._specialist_settings(name)["test"] == {"branch": "pruebas", "url": "https://app-test.example.test"}


def test_unsaved_work_is_saved_first(signed_in, workspaces):
    name, ws = version(signed_in)
    (ws / "app.py").write_bytes(b"print('adios')\n")
    assert tools._to_test(name)["status"] == "not_saved"
    assert b"refs/heads/pruebas" not in signed_in.repos[name].refs


def test_a_version_behind_main_would_drop_others_work(signed_in, workspaces):
    name, _ = version(signed_in)
    signed_in.server_commit(name, "main", {"other.md": b"x"})
    assert tools._to_test(name)["status"] == "behind_main"
    assert b"refs/heads/pruebas" not in signed_in.repos[name].refs


@pytest.mark.parametrize("reason, status, told", [
    ("Not allowed to push to protected branch pruebas", "not_allowed", "Your profile does not update"),
    ("branch pruebas is protected from force push", "refused", "not set to take a new version over the last one"),
    ("branch pruebas is protected from changing file .gitea/workflows/test.yml", "refused",
     "changes a file the project protects"),
    ("pre-receive hook declined", "refused", "The server did not accept"),
])
def test_the_git_server_decides_who_may_and_its_reason_is_told(signed_in, workspaces, reason, status, told):
    name, _ = version(signed_in)
    signed_in.repos[name].hooks["update"] = Refuse(reason)
    result = tools._to_test(name)
    assert result["status"] == status and told in result["user_message"]
    assert "IT's review as usual" in result["user_message"] and reason in result["refs"]["refs/heads/pruebas"]
    assert b"refs/heads/pruebas" not in signed_in.repos[name].refs


def test_a_version_forged_in_git_with_a_protected_file_is_not_sent(signed_in, workspaces):
    from dulwich.objects import Blob, Commit
    from dulwich.object_store import commit_tree_changes
    from dulwich.repo import Repo

    name, ws = version(signed_in)
    with Repo(str(ws)) as repo:  # the sandbox writes a commit and moves the version's ref, skipping the save
        blob = Blob.from_string(b"on: push\n")
        repo.object_store.add_object(blob)
        head = repo[repo.head()]
        tree = commit_tree_changes(repo.object_store, repo[head.tree], [(b".gitea/workflows/x.yml", 0o100644, blob.id)])
        commit = Commit()
        commit.tree, commit.parents = getattr(tree, "id", tree), [head.id]
        commit.author = commit.committer = b"x <x@x>"
        commit.commit_time = commit.author_time = 0
        commit.commit_timezone = commit.author_timezone = 0
        commit.message = b"forged"
        repo.object_store.add_object(commit)
        repo.refs[b"refs/heads/draft/work"] = commit.id
        repo.get_worktree().reset_index() if hasattr(repo, "get_worktree") else repo.reset_index()
    with pytest.raises(NeedsIT, match="protected or executable file") as stopped:
        tools._to_test(name)
    assert stopped.value.details["Paths"] == ".gitea/workflows/x.yml"
    assert b"refs/heads/pruebas" not in signed_in.repos[name].refs


@pytest.mark.parametrize("declaration, reason", [
    (b"[development]\ncode = true\n", "declares no test environment"),
    (b'[test]\nbranch = "main"\n', "other than the main one"),
])
def test_without_a_test_environment_nothing_is_sent(signed_in, workspaces, declaration, reason):
    name, _ = version(signed_in, declaration)
    result = tools._to_test(name)
    assert result["status"] == "no_test_environment" and reason in result["reason"]


def test_never_the_main_branch_nor_onto_it(signed_in, workspaces):
    name, _ = version(signed_in)
    for branch in ("main", "draft/work"):
        with pytest.raises(PermissionError, match="cannot be the project's test branch"):
            gitops.to_test(name, branch)
    plain = f"plain-{uuid.uuid4().hex[:8]}"
    signed_in.initialize(plain)
    gitops.clone(f"{signed_in.url}/me/{plain}.git")  # still on main
    with pytest.raises(PermissionError, match="never the main branch"):
        gitops.to_test(plain, "pruebas")
