"""The audit decides the send: where a project declares code, nothing goes to the server or to review unless the
dependency audit of what is saved says `allowed`. In the first real test the specialist got `blocked`, explained it
away and sent the pull request anyway."""

import json
import uuid
from pathlib import Path

import pytest

from eunomai_business import deps, gitops, server as tools, support

CODE = b'[development]\ncode = true\n'
BLOCKED = {"verdict": "blocked", "files": ["uv.lock"], "packages": 1, "not_pinned": [], "without_hashes": [],
           "blocked": [{"ecosystem": "pypi", "package": "evil", "version": "1.0", "files": ["uv.lock"],
                        "reasons": ["known vulnerabilities: GHSA-xxxx"]}]}
ALLOWED = {"verdict": "allowed", "files": ["uv.lock"], "packages": 1, "not_pinned": [], "without_hashes": [],
           "blocked": []}


@pytest.fixture(autouse=True)
def fresh_audits():
    gitops._audits.clear()


def project(server, declaration: bytes | None = CODE) -> tuple[str, Path]:
    name = f"audit-{uuid.uuid4().hex[:8]}"
    server.initialize(name)
    if declaration is not None:
        server.server_commit(name, "main", {".eunomai/project.toml": declaration})
    ws = Path(gitops.clone(f"{server.url}/me/{name}.git")["path"])
    gitops.branch(name, "draft/work")
    (ws / "notes.md").write_bytes(b"Real work.\n")
    gitops.save(name, "Work")
    return name, ws


def on_server(server, name: str) -> bool:
    return b"refs/heads/draft/work" in server.repos[name].refs


def audit_answers(monkeypatch, *answers) -> list:
    """deps.audit answers in turn; the list records each folder it read, and what it found there."""
    calls = []

    def audit(folder):
        calls.append(sorted(p.name for p in Path(folder).iterdir()))
        answer = answers[min(len(calls) - 1, len(answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(deps, "audit", audit)
    return calls


def test_a_blocked_audit_stops_the_send_in_plain_words(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    audit_answers(monkeypatch, BLOCKED)
    result = tools.version_send(name)
    assert result["status"] == "audit_refused" and not on_server(signed_in, name)
    assert result["blocked"] == BLOCKED["blocked"]
    message = result["user_message"]
    assert "not sent" in message and "evil" in message and "security problem" in message
    assert "GHSA" not in message and "uv.lock" not in message and "audit" not in message.lower()


def test_an_allowed_audit_lets_the_send_through(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    assert tools.version_send(name)["pushed"] and on_server(signed_in, name)


def test_a_blocked_audit_stops_the_proposal(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    audit_answers(monkeypatch, ALLOWED, BLOCKED)
    tools.version_send(name)
    gitops._audits.clear()
    pulls = len(signed_in.pulls)
    assert tools.version_propose(name, "Change", "Summary")["status"] == "audit_refused"
    assert len(signed_in.pulls) == pulls


@pytest.mark.parametrize("failure", [support.Unreachable(), RuntimeError("the registry answered 500")])
def test_an_audit_that_cannot_run_stops_the_send_too(signed_in, workspaces, monkeypatch, failure):
    name, _ = project(signed_in)
    audit_answers(monkeypatch, failure)
    result = tools.version_send(name)
    assert result["status"] in ("audit_unavailable", "needs_it") and not on_server(signed_in, name)
    assert "not sent" in result["user_message"] or "unexpected" in result["user_message"]


def test_an_audit_that_cannot_run_stops_the_proposal_too(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    audit_answers(monkeypatch, ALLOWED, support.Unreachable())
    tools.version_send(name)
    gitops._audits.clear()
    pulls = len(signed_in.pulls)
    assert tools.version_propose(name, "Change", "Summary")["status"] == "audit_unavailable"
    assert len(signed_in.pulls) == pulls


def test_without_code_nothing_changes(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in, declaration=b"[development]\ncode = false\n")
    calls = audit_answers(monkeypatch, BLOCKED)
    assert tools.version_send(name)["pushed"] and calls == []
    proposed = tools.version_propose(name, "Change", "Summary")  # the connector's own checks are still appended
    assert proposed["created"] and "Dependency audit: **blocked**" in signed_in.pulls[-1]["body"]


def test_a_project_that_declares_nothing_follows_the_build(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in, declaration=None)
    audit_answers(monkeypatch, BLOCKED)
    assert tools.version_send(name)["pushed"]
    other, _ = project(signed_in, declaration=None)
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"free_development": True}))
    assert tools.version_send(other)["status"] == "audit_refused"


def test_a_main_branch_that_cannot_be_read_does_not_skip_the_audit(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    monkeypatch.setattr(gitops, "project_files", lambda workspace: {"context": None, "declaration": None, "read": False})
    audit_answers(monkeypatch, BLOCKED)
    assert tools.version_send(name)["status"] == "audit_refused"


def test_it_audits_what_is_saved_not_the_folder(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    (ws / "unsaved.txt").write_bytes(b"not in any save point\n")
    calls = audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    assert "notes.md" in calls[0] and "unsaved.txt" not in calls[0] and ".git" not in calls[0]


def test_a_real_audit_sees_a_blocked_list_that_was_saved_even_if_the_folder_no_longer_has_it(signed_in, workspaces,
                                                                                            monkeypatch):
    name, ws = project(signed_in)
    (ws / "requirements.txt").write_bytes(b"evil>=1\n")
    gitops.save(name, "Add a loose requirement")
    (ws / "requirements.txt").unlink()  # the folder looks clean; the version says otherwise
    monkeypatch.setattr(deps, "_get", lambda url: None)
    monkeypatch.setattr(deps, "_vulnerable", lambda queries: {})
    assert tools.version_send(name)["status"] == "audit_refused"


def test_send_and_proposal_of_the_same_save_run_one_audit(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    calls = audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    tools.version_propose(name, "Change", "Summary")
    assert len(calls) == 1
    assert "Dependency audit: **allowed**" in signed_in.pulls[-1]["body"]


def test_a_new_save_is_audited_again(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    calls = audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    (ws / "more.md").write_bytes(b"More.\n")
    gitops.save(name, "More")
    tools.version_send(name)
    assert len(calls) == 2


def test_an_allowed_audit_is_kept_only_for_a_while(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    calls = audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    monkeypatch.setattr(gitops, "_AUDIT_KEPT_SECONDS", 0)
    tools.version_send(name)
    assert len(calls) == 2


def test_a_blocked_audit_is_never_kept(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    calls = audit_answers(monkeypatch, BLOCKED, ALLOWED)  # a registry that did not answer, for example, comes back
    assert tools.version_send(name)["status"] == "audit_refused"
    assert tools.version_send(name)["pushed"] and len(calls) == 2


def test_a_version_that_moved_during_the_audit_is_not_sent(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)

    def moved_meanwhile(folder):
        (ws / "more.md").write_bytes(b"Saved while the audit ran.\n")
        gitops.save(name, "More")
        return ALLOWED

    monkeypatch.setattr(deps, "audit", moved_meanwhile)
    assert "error" in tools.version_send(name) and not on_server(signed_in, name)


def test_the_copy_it_audits_is_removed_and_stays_outside_the_workspace(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    seen = []

    def audit(folder):
        seen.append(Path(folder))
        return ALLOWED

    monkeypatch.setattr(deps, "audit", audit)
    tools.version_send(name)
    assert not seen[0].is_relative_to(ws) and not seen[0].exists()


def test_every_package_is_checked_at_once(monkeypatch, tmp_path):
    """The audit runs before every send: a tree of 50 packages took 38 seconds one by one."""
    import threading
    import time

    at_once, most, lock = [0], [0], threading.Lock()

    def slow(ecosystem_name):
        with lock:
            at_once[0] += 1
            most[0] = max(most[0], at_once[0])
        time.sleep(0.02)
        with lock:
            at_once[0] -= 1
        return None

    monkeypatch.setattr(deps, "_pypi", slow)
    monkeypatch.setattr(deps, "_get", lambda url: None)
    monkeypatch.setattr(deps, "_vulnerable", lambda queries: {})
    pins = "".join(f"package{n}==1.0\n" for n in range(16))
    (tmp_path / "requirements.txt").write_text(pins)
    assert deps.audit(tmp_path)["verdict"] == "blocked" and most[0] > 1


def test_a_saved_link_is_copied_as_a_plain_file_never_as_a_link(signed_in, workspaces, tmp_path):
    name, ws = project(signed_in)
    from dulwich.objects import Blob
    from dulwich.object_store import commit_tree_changes
    from dulwich.repo import Repo

    with Repo(str(ws)) as repo:
        blob = Blob.from_string(b"../../somewhere/secret")
        repo.object_store.add_object(blob)
        tree = commit_tree_changes(repo.object_store, repo[repo[repo.head()].tree], [(b"link", 0o120000, blob.id)])
        commit = repo[repo.head()]
        commit.tree = getattr(tree, "id", tree)
        repo.object_store.add_object(commit)
        repo.refs[b"refs/heads/draft/work"] = commit.id
    target = tmp_path / "copy"
    gitops.export_saved(name, target)
    assert not (target / "link").is_symlink() and (target / "link").read_bytes() == b"../../somewhere/secret"


def test_a_path_that_leaves_the_copy_stops_it(signed_in, workspaces, tmp_path):
    name, ws = project(signed_in)
    from dulwich.objects import Blob, Tree
    from dulwich.repo import Repo

    with Repo(str(ws)) as repo:  # the sandbox can write objects: a tree with a name no save would accept
        blob = Blob.from_string(b"x")
        evil = Tree()
        evil.add(b"..", 0o40000, Tree().id)
        evil.add(b"con.txt", 0o100644, blob.id)
        commit = repo[repo.head()]
        commit.tree = evil.id
        for item in (blob, Tree(), evil, commit):
            repo.object_store.add_object(item)
        repo.refs[b"refs/heads/draft/work"] = commit.id
    with pytest.raises(support.NeedsIT):
        gitops.export_saved(name, tmp_path / "copy")
    assert not (workspaces.parent / "con.txt").exists()
