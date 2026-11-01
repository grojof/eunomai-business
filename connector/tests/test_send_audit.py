"""The audit decides the send: nothing goes to the server, to review or to the test environment unless the dependency
audit of what is saved says `allowed`. In the first real test the specialist got `blocked`, explained it away and sent
the pull request anyway."""

import json
import time
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


@pytest.mark.parametrize("text", [
    b"[development\ncode = true\n", b"[development]\ncod = true\n", b'[development]\ncode = "yes"\n',
    b"[development]\ncode = false\n", b'[test]\nbranch = "pruebas"\n', None])
def test_the_audit_does_not_depend_on_what_the_project_declares(signed_in, workspaces, monkeypatch, text):
    """A declaration that allows nothing is not a reason to send what nobody audited."""
    name, _ = project(signed_in, text)
    calls = audit_answers(monkeypatch, BLOCKED)
    assert tools.version_send(name)["status"] == "audit_refused" and len(calls) == 1
    assert not on_server(signed_in, name)
    assert tools.version_propose(name, "Change", "Summary")["status"] in ("audit_refused", "not_sent")
    assert signed_in.pulls == [] or all(p["repo"] != name for p in signed_in.pulls)


def test_a_version_with_no_packages_needs_no_network(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in, None)

    def no_network(*args, **kwargs):
        raise AssertionError("the audit asked the network about a version with no packages")

    for call in ("_get", "_vulnerabilities", "_exists"):
        monkeypatch.setattr(deps, call, no_network)
    monkeypatch.setattr(deps, "_vulnerable", lambda queries: no_network() if queries else {})
    assert tools.version_send(name)["pushed"] and on_server(signed_in, name)
    assert tools.version_propose(name, "Change", "Summary")["created"]
    assert "Dependency audit: **allowed**" in signed_in.pulls[-1]["body"]


# --- what the server holds ---------------------------------------------------------------------------------------

def test_a_proposal_says_which_commit_was_audited(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    tools.version_propose(name, "Change", "Summary")
    head = gitops.saved_head(name)
    assert head == signed_in.repos[name].refs[b"refs/heads/draft/work"].decode()
    assert f"`{head[:12]}`" in signed_in.pulls[-1]["body"]


def test_a_version_never_sent_cannot_be_proposed_and_says_so(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_propose(name, "Change", "Summary")
    assert answer["status"] == "not_sent" and "sent" in answer["user_message"] and not signed_in.pulls_of(name)


def test_what_is_proposed_is_what_the_server_holds_not_a_clean_save_nobody_sent(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    (ws / "bad.txt").write_bytes(b"bad\n")
    gitops.save(name, "Bad")
    gitops.push(name, gitops.project_files(name)["tip"])  # sent before the gate, or by a colleague with Git
    (ws / "bad.txt").unlink()
    gitops.save(name, "Clean, never sent")
    calls = audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_propose(name, "Change", "Summary")
    assert answer["status"] == "not_sent" and calls == [] and not signed_in.pulls_of(name)


def test_a_blocked_save_after_a_send_cannot_reach_review_behind_the_commit_that_was_sent(signed_in, workspaces,
                                                                                         monkeypatch):
    """Send C1, save a blocked C2, propose: the proposal waits, and the send is where the audit answers."""
    name, ws = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    assert tools.version_send(name)["pushed"]
    sent = signed_in.repos[name].refs[b"refs/heads/draft/work"]
    (ws / "more.md").write_bytes(b"More.\n")
    gitops.save(name, "A blocked package")
    audit_answers(monkeypatch, BLOCKED)
    assert tools.version_propose(name, "Change", "Summary")["status"] == "not_sent"
    assert tools.version_send(name)["status"] == "audit_refused"
    assert signed_in.repos[name].refs[b"refs/heads/draft/work"] == sent and not signed_in.pulls_of(name)
    audit_answers(monkeypatch, ALLOWED)
    gitops._audits.clear()
    assert tools.version_send(name)["pushed"] and tools.version_propose(name, "Change", "Summary")["created"]


def test_what_was_audited_is_what_goes_even_if_the_reference_moves_during_the_send(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    good = gitops.saved_head(name)
    (ws / "bad.txt").write_bytes(b"bad\n")
    gitops.save(name, "Bad")
    bad = gitops.saved_head(name)
    ref = ws / ".git" / "refs" / "heads" / "draft" / "work"
    ref.write_bytes(good.encode() + b"\n")  # the sandbox can write this
    audit_answers(monkeypatch, ALLOWED)
    real = gitops._send_commit

    def the_sandbox_moves_it(*args):  # the moment of the send
        ref.write_bytes(bad.encode() + b"\n")
        return real(*args)

    monkeypatch.setattr(gitops, "_send_commit", the_sandbox_moves_it)
    tools.version_send(name)
    assert signed_in.repos[name].refs[b"refs/heads/draft/work"].decode() == good


def test_a_send_still_never_forces(signed_in, workspaces, monkeypatch):
    from eunomai_business.support import NeedsIT

    name, ws = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    gitops.push(name, gitops.project_files(name)["tip"])
    signed_in.server_commit(name, "draft/work", {"other.md": b"Changed elsewhere.\n"})
    (ws / "more.md").write_bytes(b"More.\n")
    gitops.save(name, "More")
    server_head = signed_in.repos[name].refs[b"refs/heads/draft/work"]
    with pytest.raises(NeedsIT, match="server has changes"):
        gitops.push(name, gitops.project_files(name)["tip"])
    assert signed_in.repos[name].refs[b"refs/heads/draft/work"] == server_head


# --- the test environment ----------------------------------------------------------------------------------------

TEST = b'[test]\nbranch = "pruebas"\n'


def test_a_blocked_audit_stops_the_test_environment_too(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in, TEST)
    audit_answers(monkeypatch, BLOCKED)
    assert tools.version_to_test(name)["status"] == "audit_refused"
    assert b"refs/heads/pruebas" not in signed_in.repos[name].refs


def test_an_audit_that_cannot_run_stops_the_test_environment_too(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in, TEST)
    audit_answers(monkeypatch, support.Unreachable())
    assert tools.version_to_test(name)["status"] == "audit_unavailable"
    assert b"refs/heads/pruebas" not in signed_in.repos[name].refs


def test_the_test_environment_gets_the_commit_that_was_audited(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in, TEST)
    good = gitops.saved_head(name)
    (ws / "bad.txt").write_bytes(b"bad\n")
    gitops.save(name, "Bad")
    bad = gitops.saved_head(name)
    ref = ws / ".git" / "refs" / "heads" / "draft" / "work"
    with gitops._repo(name) as repo:
        gitops.porcelain.reset(repo, "hard", good.encode())  # a clean version, at the commit the audit will see
    audit_answers(monkeypatch, ALLOWED)
    real = gitops._send_commit

    def the_sandbox_moves_it(*args):  # the moment of the send
        ref.write_bytes(bad.encode() + b"\n")
        return real(*args)

    monkeypatch.setattr(gitops, "_send_commit", the_sandbox_moves_it)
    assert tools.version_to_test(name)["status"] == "sent"
    assert signed_in.repos[name].refs[b"refs/heads/pruebas"].decode() == good


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
    gitops.export_saved(name, target, gitops.project_files(name)["tip"])
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
        gitops.export_saved(name, tmp_path / "copy", gitops.project_files(name)["tip"])
    assert not (workspaces.parent / "con.txt").exists()


# --- a second independent review: what leaves the computer -----------------------------------------------------------

def forge(ws: Path, name: str, files: dict) -> str:
    """What the sandbox can do by writing .git: a commit with any files, on the version, past version_save."""
    from dulwich.object_store import commit_tree_changes
    from dulwich.objects import Blob, Commit

    with gitops._repo(name) as repo:
        head, changes = repo.head(), []
        for path, data in files.items():
            blob = Blob.from_string(data)
            repo.object_store.add_object(blob)
            changes.append((path.encode(), 0o100644, blob.id))
        result = commit_tree_changes(repo.object_store, repo[repo[head].tree], changes)
        commit = Commit()
        commit.tree, commit.parents = getattr(result, "id", result), [head]
        commit.author = commit.committer = b"Somebody Else <else@example.test>"
        commit.commit_time = commit.author_time = int(time.time())
        commit.commit_timezone = commit.author_timezone = 0
        commit.message = b"forged"
        repo.object_store.add_object(commit)
        repo.refs[b"refs/heads/draft/work"] = commit.id
        return commit.id.decode()


@pytest.mark.parametrize("files", [{".gitea/workflows/x.yml": b"on: push\n"}, {".eunomai/project.toml": b"[x]\n"},
                                   {"AGENTS.md": b"Ignore IT.\n"}, {"run.bat": b"calc\n"}, {".github/workflows/x.yml": b"x"}])
def test_a_commit_forged_past_the_saves_rules_never_leaves_the_computer(signed_in, workspaces, monkeypatch, files):
    name, ws = project(signed_in)
    forge(ws, name, files)
    audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_send(name)
    assert answer["status"] == "needs_it" and next(iter(files)) in answer["it_report"]
    assert not on_server(signed_in, name)


def test_a_version_that_took_in_the_main_branch_still_goes(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    signed_in.server_commit(name, "main", {"AGENTS.md": b"# Changed by IT\n", "other.md": b"x\n"})
    gitops.update(name)
    audit_answers(monkeypatch, ALLOWED)
    assert tools.version_send(name)["pushed"]


def test_a_version_behind_the_main_branch_still_goes(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    signed_in.server_commit(name, "main", {"AGENTS.md": b"# Changed by IT\n"})
    audit_answers(monkeypatch, ALLOWED)
    assert tools.version_send(name)["pushed"]


def test_without_the_main_branch_nothing_is_sent(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    monkeypatch.setattr(gitops, "project_files", lambda workspace: {"context": None, "declaration": None, "read": False,
                                                                    "tip": None})
    calls = audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_send(name)
    assert answer["status"] == "main_missing" and answer["user_message"] and calls == []
    assert not on_server(signed_in, name)


@pytest.mark.parametrize("branch", [b"main", b"Main", b"pruebas", b"PRUEBAS"])
def test_a_head_the_sandbox_wrote_cannot_aim_the_send_at_a_shared_branch(signed_in, workspaces, monkeypatch, branch):
    name, ws = project(signed_in, CODE + b'\n[test]\nbranch = "pruebas"\n')
    signed_in.repos[name].refs[b"refs/heads/pruebas"] = signed_in.repos[name].refs[b"refs/heads/main"]
    before = {ref: signed_in.repos[name].refs[ref] for ref in (b"refs/heads/main", b"refs/heads/pruebas")}
    saved = gitops.saved_head(name)
    (ws / ".git" / "refs" / "heads" / branch.decode()).write_bytes(saved.encode() + b"\n")
    (ws / ".git" / "HEAD").write_bytes(b"ref: refs/heads/" + branch + b"\n")
    audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_send(name)
    assert "pushed" not in answer
    assert {ref: signed_in.repos[name].refs[ref] for ref in before} == before


@pytest.mark.parametrize("planted", ["info/grafts", "shallow", "objects/info/alternates"])
def test_a_repository_that_rewrites_its_own_history_stops(signed_in, workspaces, monkeypatch, planted):
    """Grafts made the merge base the forged commit, so the check above found nothing to refuse."""
    name, ws = project(signed_in)
    forged = forge(ws, name, {"AGENTS.md": b"x\n"})
    main = signed_in.repos[name].refs[b"refs/heads/main"].decode()
    file = ws / ".git" / planted
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(f"{main} {forged}\n{forged}\n" if planted == "info/grafts" else f"{forged}\n")
    audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_send(name)
    assert answer["status"] == "needs_it" and not on_server(signed_in, name)


def test_a_server_that_refuses_the_update_is_told_plainly(signed_in, workspaces, monkeypatch):
    """The fake server cannot reject a reference, so the answer is stubbed; this is unproved against a real Gitea."""
    from types import SimpleNamespace

    name, _ = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    monkeypatch.setattr(gitops, "_send_commit", lambda *args: SimpleNamespace(
        ref_status={b"refs/heads/draft/work": "failed to update ref"}))
    answer = tools.version_send(name)
    assert answer["status"] == "needs_it" and "did not accept" in answer["user_message"]


def test_a_proposal_audits_the_commit_it_compared_not_one_read_later(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    held = signed_in.repos[name].refs[b"refs/heads/draft/work"].decode()
    (ws / "more.md").write_bytes(b"More.\n")
    gitops.save(name, "Saved, never sent")
    other = gitops.saved_head(name)
    ref = ws / ".git" / "refs" / "heads" / "draft" / "work"
    ref.write_bytes(held.encode() + b"\n")
    real = gitops.saved_head

    def moved_after_the_comparison(workspace):
        value = real(workspace)
        ref.write_bytes(other.encode() + b"\n")
        return value

    monkeypatch.setattr(gitops, "saved_head", moved_after_the_comparison)
    gitops._audits.clear()
    assert tools.version_propose(name, "Change", "Summary")["created"]
    assert f"`{held[:12]}`" in signed_in.pulls_of(name)[-1]["body"]


# --- a third review: what `.git` can make history look like --------------------------------------------------------

def write_commit_graph(ws: Path, entries: list) -> None:
    from dulwich.commit_graph import CommitGraph, CommitGraphEntry
    from dulwich.object_format import DEFAULT_OBJECT_FORMAT

    graph = CommitGraph(object_format=DEFAULT_OBJECT_FORMAT)
    for commit, tree, parents, generation, when in entries:
        graph.entries.append(CommitGraphEntry(commit, tree, parents, generation, when))
    graph.entries.sort(key=lambda entry: entry.commit_id)
    for index, entry in enumerate(graph.entries):
        graph._oid_to_index[bytes.fromhex(entry.commit_id.decode())] = index
    path = ws / ".git" / "objects" / "info" / "commit-graph"
    path.parent.mkdir(exist_ok=True)
    with open(path, "wb") as file:
        graph.write_to_file(file)


def a_graph_that_hides(name: str, ws: Path, signed_in, forged: str) -> None:
    """main's tip made a child of the forged commit: the merge base would be the forged commit itself."""
    main = signed_in.repos[name].refs[b"refs/heads/main"]
    with gitops._repo(name) as repo:
        parent, when = repo[main].parents[0], repo[main].commit_time
        write_commit_graph(ws, [(main, repo[main].tree, [parent, forged.encode()], 5, when),
                                (forged.encode(), repo[forged.encode()].tree, [parent], 4, when)])


def test_a_commit_graph_does_not_hide_a_forged_commit(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    forged = forge(ws, name, {".gitea/workflows/x.yml": b"on: push\n", "run.bat": b"calc\n", "AGENTS.md": b"x\n"})
    a_graph_that_hides(name, ws, signed_in, forged)
    audit_answers(monkeypatch, ALLOWED)
    assert tools.version_send(name)["status"] == "needs_it" and not on_server(signed_in, name)


def test_history_is_read_from_the_commits_whatever_dulwich_would_believe(signed_in, workspaces):
    """This fails if an upgrade of dulwich starts reading parents some other way: the first assert shows the file would
    fool it, and the others that the connector's repository does not listen."""
    from dulwich.graph import find_merge_base
    from dulwich.repo import Repo

    name, ws = project(signed_in)
    forged = forge(ws, name, {"AGENTS.md": b"x\n"})
    a_graph_that_hides(name, ws, signed_in, forged)
    main = signed_in.repos[name].refs[b"refs/heads/main"]
    with Repo(str(ws)) as plain:
        assert find_merge_base(plain, [main, forged.encode()]) == [forged.encode()]
    with gitops._repo(name) as repo:
        assert find_merge_base(repo, [main, forged.encode()]) != [forged.encode()]
        assert repo.object_store.get_commit_graph() is None
        assert repo.get_parents(main) == repo[main].parents


@pytest.mark.parametrize("planted", ["objects/info/commit-graphs/graph-0.graph", "objects/info/commit-graphs/commit-graph-chain",
                                     "objects/pack/multi-pack-index"])
def test_what_else_can_describe_history_changes_nothing(signed_in, workspaces, monkeypatch, planted):
    name, ws = project(signed_in)
    forge(ws, name, {"AGENTS.md": b"x\n"})
    file = ws / ".git" / planted
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"not what it says it is\n")
    audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    assert not on_server(signed_in, name)


def test_a_replacement_reference_is_not_followed(signed_in, workspaces, monkeypatch):
    from dulwich.objects import Commit

    name, ws = project(signed_in)
    forged = forge(ws, name, {"AGENTS.md": b"x\n"})
    main = signed_in.repos[name].refs[b"refs/heads/main"]
    with gitops._repo(name) as repo:
        fake = repo[main].copy()
        fake.parents = [forged.encode()]
        repo.object_store.add_object(fake)
        repo.refs[b"refs/replace/" + main] = fake.id
    audit_answers(monkeypatch, ALLOWED)
    assert tools.version_send(name)["status"] == "needs_it" and not on_server(signed_in, name)


def test_an_object_that_is_not_what_its_name_says_stops(signed_in, workspaces):
    """A pack and index that call forged content by a real commit's name: every read by name hashes the content."""
    import hashlib
    import struct
    import zlib

    from dulwich.errors import ChecksumMismatch
    from dulwich.objects import Commit
    from dulwich.pack import write_pack_index

    name, ws = project(signed_in)
    main = signed_in.repos[name].refs[b"refs/heads/main"]
    with gitops._repo(name) as repo:
        fake = repo[main].copy()
    fake.parents = []
    raw = fake.as_raw_string()
    size, head = len(raw), bytearray()
    byte = (1 << 4) | (size & 15)
    size >>= 4
    while size:
        head.append(byte | 0x80)
        byte = size & 0x7f
        size >>= 7
    head.append(byte)
    body = bytes(head) + zlib.compress(raw)
    content = b"PACK" + struct.pack(">II", 2, 1) + body
    content += hashlib.sha1(content).digest()
    packs = ws / ".git" / "objects" / "pack"
    for real in list(packs.glob("pack-*")):
        real.rename(ws / ".git" / real.name)  # out of the folder: any *.pack in it is read
    (packs / "pack-forged.pack").write_bytes(content)
    with open(packs / "pack-forged.idx", "wb") as file:
        write_pack_index(file, [(bytes.fromhex(main.decode()), 12, zlib.crc32(body))], content[-20:])
    with gitops._repo(name) as repo:
        with pytest.raises(ChecksumMismatch):
            repo[main]


# --- which branch: HEAD is the sandbox's -----------------------------------------------------------------------------

def test_head_moved_during_the_audit_does_not_choose_the_target(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in, CODE + b'\n[test]\nbranch = "pruebas"\n')
    main = signed_in.repos[name].refs[b"refs/heads/main"]
    signed_in.repos[name].refs[b"refs/heads/pruebas"] = main
    (ws / ".git" / "refs" / "heads" / "pruebas").write_bytes(gitops.saved_head(name).encode() + b"\n")
    real = gitops.audit_saved

    def moved(*args):
        (ws / ".git" / "HEAD").write_bytes(b"ref: refs/heads/pruebas\n")
        return real(*args)

    monkeypatch.setattr(gitops, "audit_saved", moved)
    audit_answers(monkeypatch, ALLOWED)
    assert "pushed" not in tools.version_send(name)
    assert signed_in.repos[name].refs[b"refs/heads/pruebas"] == main


def test_head_moved_after_the_check_does_not_choose_the_target(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    main = signed_in.repos[name].refs[b"refs/heads/main"]
    signed_in.repos[name].refs[b"refs/heads/release"] = main
    (ws / ".git" / "refs" / "heads" / "release").write_bytes(gitops.saved_head(name).encode() + b"\n")
    real = gitops._send_commit

    def moved(*args):
        (ws / ".git" / "HEAD").write_bytes(b"ref: refs/heads/release\n")
        return real(*args)

    monkeypatch.setattr(gitops, "_send_commit", moved)
    audit_answers(monkeypatch, ALLOWED)
    assert tools.version_send(name)["pushed"]
    assert signed_in.repos[name].refs[b"refs/heads/release"] == main and on_server(signed_in, name)


def test_a_branch_of_the_server_the_connector_never_made_is_not_sent(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    main = signed_in.repos[name].refs[b"refs/heads/main"]
    signed_in.repos[name].refs[b"refs/heads/release"] = main
    (ws / ".git" / "refs" / "heads" / "release").write_bytes(gitops.saved_head(name).encode() + b"\n")
    (ws / ".git" / "HEAD").write_bytes(b"ref: refs/heads/release\n")
    audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_send(name)
    assert answer["status"] == "needs_it" and "email_link" in answer or "it_report" in answer
    assert signed_in.repos[name].refs[b"refs/heads/release"] == main


def unrecorded(name: str) -> None:
    """A workspace from before the connector kept its versions."""
    registry = gitops._registry()
    for entry in registry.values():
        entry.pop("versions", None)
    (gitops.data_dir() / "workspaces.json").write_text(json.dumps(registry), encoding="utf-8")


def test_an_older_workspace_keeps_working_with_a_version_not_on_the_server_yet(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    unrecorded(name)
    audit_answers(monkeypatch, ALLOWED)
    assert tools.version_send(name)["pushed"]
    assert "draft/work" in gitops._registry()[gitops.key(name)]["versions"]


def test_an_older_workspace_keeps_working_with_a_version_already_proposed(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    tools.version_propose(name, "Change", "Summary")
    unrecorded(name)
    (ws / "more.md").write_bytes(b"More.\n")
    gitops.save(name, "More")
    assert tools.version_send(name)["pushed"]


def test_a_retired_version_is_no_longer_a_version(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    audit_answers(monkeypatch, ALLOWED)
    tools.version_send(name)
    tools.version_propose(name, "Change", "Summary")
    signed_in.accept(name, "draft/work")
    gitops.update(name)
    assert "draft/work" not in gitops._registry()[gitops.key(name)].get("versions", [])


def test_push_needs_the_main_branch(signed_in, workspaces):
    with pytest.raises(TypeError):
        gitops.push("anything")


# --- what the server no longer has ---------------------------------------------------------------------------------

def test_a_main_branch_renamed_on_the_server_says_so_not_check_the_network(signed_in, workspaces, monkeypatch):
    name, _ = project(signed_in)
    repo = signed_in.repos[name]
    repo.refs[b"refs/heads/trunk"] = repo.refs[b"refs/heads/main"]
    del repo.refs[b"refs/heads/main"]
    audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_send(name)
    assert answer["status"] == "main_missing" and "network" not in answer["user_message"].lower()
    assert "it_report" in answer and not on_server(signed_in, name)


def test_a_history_rewritten_on_the_server_is_told_as_such(signed_in, workspaces, monkeypatch):
    from dulwich.objects import Commit

    name, _ = project(signed_in)
    repo = signed_in.repos[name]
    tip = repo[repo.refs[b"refs/heads/main"]]
    fresh = Commit()
    fresh.tree, fresh.parents = tip.tree, []
    fresh.author = fresh.committer = b"IT <it@example.test>"
    fresh.commit_time = fresh.author_time = int(time.time())
    fresh.commit_timezone = fresh.author_timezone = 0
    fresh.message = b"squashed history"
    repo.object_store.add_object(fresh)
    repo.refs[b"refs/heads/main"] = fresh.id
    audit_answers(monkeypatch, ALLOWED)
    answer = tools.version_send(name)
    assert answer["status"] == "needs_it" and "no common history" in answer["it_report"]
    assert "history" in answer["user_message"] and not on_server(signed_in, name)
