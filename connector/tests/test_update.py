"""Bringing the latest changes: autonomous when it is safe, stopped and reported to IT when it is not.

Every scenario checks the same promise: nothing the user did is ever lost.
"""

from pathlib import Path
from urllib.parse import unquote

import pytest

from eunomai_business import gitops, server as tools
from eunomai_business.support import NeedsIT


def joined(server, name: str) -> Path:
    """A user who joined the repository: a clone of the main branch."""
    server.initialize(name)
    return Path(gitops.clone(f"{server.url}/me/{name}.git")["path"])


def proposed(server, name: str, version: str, files: dict) -> Path:
    """A user who made a version with some files, sent it and proposed it."""
    ws = joined(server, name)
    gitops.branch(name, version)
    for path, data in files.items():
        (ws / path).parent.mkdir(parents=True, exist_ok=True)
        (ws / path).write_bytes(data)
    gitops.save(name, "My change")
    gitops.push(name)
    gitops.pull_request(name, "My change")
    return ws


def local_branches(ws: Path) -> set[str]:
    with gitops._open(str(ws)) as repo:
        return {ref.decode() for ref in repo.refs.keys(base=b"refs/heads/")}


def backups(ws: Path) -> list[str]:
    with gitops._open(str(ws)) as repo:
        return [ref.decode() for ref in repo.refs.keys(base=b"refs/eunomai/backup/")]


def test_nothing_new_means_nothing_changes(signed_in, workspaces):
    ws = joined(signed_in, "quiet")
    result = gitops.update("quiet")
    assert result["status"] == "up_to_date" and result["user_message"] == "Everything is up to date."
    assert backups(ws) == []  # nothing moved, nothing to keep


def test_on_the_main_branch_the_latest_changes_arrive(signed_in, workspaces):
    ws = joined(signed_in, "ff")
    signed_in.server_commit("ff", "main", {"news.md": b"from a colleague\n"})
    result = gitops.update("ff")
    assert result["status"] == "updated" and result["branch"] == "main"
    assert (ws / "news.md").read_bytes() == b"from a colleague\n"


@pytest.mark.parametrize("squash", [False, True], ids=["merge-commit", "squash"])
def test_accepted_proposal_returns_to_the_main_branch(signed_in, workspaces, squash):
    name = f"accepted-{'squash' if squash else 'merge'}"
    ws = proposed(signed_in, name, "ana/report", {"report.md": b"quarterly report\n"})
    signed_in.accept(name, "ana/report", squash=squash)
    result = gitops.update(name)
    assert result["status"] == "updated" and result["branch"] == "main"
    assert result["retired_version"] == "ana/report" and local_branches(ws) == {"main"}
    assert (ws / "report.md").read_bytes() == b"quarterly report\n"
    assert "accepted" in result["user_message"]
    assert any(ref.endswith("/ana/report") for ref in backups(ws))  # the retired version can still be recovered


def test_unsaved_changes_are_saved_before_anything_else(signed_in, workspaces):
    ws = joined(signed_in, "unsaved")
    gitops.branch("unsaved", "ana/draft")
    (ws / "draft.md").write_bytes(b"not saved yet\n")
    signed_in.server_commit("unsaved", "main", {"news.md": b"news\n"})
    result = gitops.update("unsaved")
    assert result["user_message"].startswith("Your unsaved changes were saved first.")
    assert (ws / "draft.md").read_bytes() == b"not saved yet\n" and (ws / "news.md").exists()
    assert gitops.status("unsaved")["untracked"] == []


def test_edits_made_on_the_main_branch_go_to_a_new_version(signed_in, workspaces):
    ws = joined(signed_in, "on-main")
    (ws / "idea.md").write_bytes(b"an idea\n")
    result = gitops.update("on-main")
    assert result["branch"].startswith("work/")
    assert (ws / "idea.md").read_bytes() == b"an idea\n" and gitops.status("on-main")["untracked"] == []


def test_main_moved_on_and_combines_cleanly(signed_in, workspaces):
    ws = joined(signed_in, "combine")
    gitops.branch("combine", "ana/mine")
    (ws / "mine.md").write_bytes(b"mine\n")
    gitops.save("combine", "Mine")
    signed_in.server_commit("combine", "main", {"theirs.md": b"theirs\n"})
    result = gitops.update("combine")
    assert result["status"] == "updated" and result["branch"] == "ana/mine"
    assert (ws / "mine.md").read_bytes() == b"mine\n" and (ws / "theirs.md").read_bytes() == b"theirs\n"
    with gitops._open(str(ws)) as repo:
        assert len(repo[repo.head()].parents) == 2


def test_a_conflict_stops_without_touching_anything(signed_in, workspaces, monkeypatch):
    monkeypatch.setenv("EUNOMAI_SUPPORT_EMAIL", "it@example.test")
    ws = joined(signed_in, "conflict")
    gitops.branch("conflict", "ana/edit")
    (ws / "README.md").write_bytes(b"# Sandbox\n\nMy notes.\n")
    gitops.save("conflict", "Edit the README")
    signed_in.server_commit("conflict", "main", {"README.md": b"# Sandbox\n\nTheir notes.\n"})
    with gitops._open(str(ws)) as repo:
        before = repo.head()

    result = tools._safe(gitops.update, "conflict")
    assert result["status"] == "needs_it" and "Your work is safe" in result["user_message"]
    assert "README.md" in result["it_report"] and "token-" not in result["it_report"]
    assert result["email_link"].startswith("mailto:it@example.test?subject=")
    assert "changed the same files" in unquote(result["email_link"])
    assert (ws / "README.md").read_bytes() == b"# Sandbox\n\nMy notes.\n"
    with gitops._open(str(ws)) as repo:
        assert repo.head() == before


def test_edits_to_different_lines_of_the_same_file_are_not_combined(signed_in, workspaces):
    """No textual conflict, yet the same file: two edits can still break each other, so it goes to IT."""
    ws = joined(signed_in, "same-file")
    signed_in.server_commit("same-file", "main", {"list.md": b"one\ntwo\nthree\nfour\nfive\n"})
    gitops.update("same-file")
    gitops.branch("same-file", "ana/top")
    (ws / "list.md").write_bytes(b"ONE\ntwo\nthree\nfour\nfive\n")
    gitops.save("same-file", "Top line")
    signed_in.server_commit("same-file", "main", {"list.md": b"one\ntwo\nthree\nfour\nFIVE\n"})
    with pytest.raises(NeedsIT, match="changed the same files"):
        gitops.update("same-file")
    assert (ws / "list.md").read_bytes() == b"ONE\ntwo\nthree\nfour\nfive\n"


def test_identical_changes_on_both_sides_combine(signed_in, workspaces):
    ws = joined(signed_in, "identical")
    gitops.branch("identical", "ana/same")
    (ws / "shared.md").write_bytes(b"same text\n")
    gitops.save("identical", "Same file")
    signed_in.server_commit("identical", "main", {"shared.md": b"same text\n", "other.md": b"other\n"})
    assert gitops.update("identical")["status"] == "updated"
    assert (ws / "other.md").exists() and (ws / "shared.md").read_bytes() == b"same text\n"


def test_a_version_changed_elsewhere_stops(signed_in, workspaces):
    ws = proposed(signed_in, "elsewhere", "ana/shared", {"a.md": b"a\n"})
    signed_in.server_commit("elsewhere", "ana/shared", {"b.md": b"from another computer\n"})
    (ws / "c.md").write_bytes(b"c\n")
    gitops.save("elsewhere", "Local change")
    signed_in.server_commit("elsewhere", "main", {"news.md": b"news\n"})
    with pytest.raises(NeedsIT, match="diverged"):
        gitops.update("elsewhere")
    assert (ws / "c.md").exists()


def test_files_in_the_way_are_never_overwritten(signed_in, workspaces):
    ws = joined(signed_in, "in-the-way")
    (ws / ".git" / "info").mkdir(exist_ok=True)
    (ws / ".git" / "info" / "exclude").write_text("local.md\n", encoding="utf-8")  # ignored, so not auto-saved
    (ws / "local.md").write_bytes(b"mine, ignored\n")
    signed_in.server_commit("in-the-way", "main", {"local.md": b"theirs\n"})
    with pytest.raises(NeedsIT, match="untracked files in the way"):
        gitops.update("in-the-way")
    assert (ws / "local.md").read_bytes() == b"mine, ignored\n"


def test_an_unreachable_server_is_not_a_problem_for_it(signed_in, workspaces, monkeypatch):
    joined(signed_in, "offline")

    class Down:
        def fetch(self, *args, **kwargs):
            raise ConnectionRefusedError("no route")

    monkeypatch.setattr(gitops, "get_transport_and_path", lambda *a, **k: (Down(), "/me/offline.git"))
    result = tools._safe(gitops.update, "offline")
    assert result["status"] == "unreachable" and "VPN" in result["user_message"]


def test_an_unexpected_error_reaches_it_not_the_user(monkeypatch):
    monkeypatch.setenv("EUNOMAI_SUPPORT_EMAIL", "it@example.test")

    def broken():
        raise RuntimeError("something odd")

    result = tools._safe(broken)
    assert result["status"] == "needs_it" and "Traceback" not in result["user_message"]
    assert "RuntimeError: something odd" in result["it_report"]


def test_a_version_with_nothing_saved_just_moves_to_the_latest(signed_in, workspaces):
    ws = joined(signed_in, "empty-version")
    gitops.branch("empty-version", "ana/idea")
    signed_in.server_commit("empty-version", "main", {"news.md": b"news\n"})
    result = gitops.update("empty-version")
    assert result["status"] == "updated" and result["branch"] == "ana/idea" and "retired_version" not in result
    assert (ws / "news.md").exists() and "accepted" not in result["user_message"]


def test_versions_never_stack_on_another_version(signed_in, workspaces):
    joined(signed_in, "stack")
    gitops.branch("stack", "ana/one")
    with pytest.raises(PermissionError, match="start from the main branch"):
        gitops.branch("stack", "ana/two")


def test_the_status_shows_the_versions_proposal(signed_in, workspaces):
    proposed(signed_in, "with-proposal", "ana/x", {"x.md": b"x\n"})
    status = tools._safe(tools._status, "with-proposal")
    assert status["proposal"]["state"] == "open" and status["proposal"]["merged"] is False


def test_sending_never_overwrites_the_server(signed_in, workspaces):
    ws = proposed(signed_in, "no-force", "ana/v", {"a.md": b"a\n"})
    elsewhere = signed_in.server_commit("no-force", "ana/v", {"b.md": b"from another computer\n"})
    (ws / "c.md").write_bytes(b"c\n")
    gitops.save("no-force", "Local change")
    result = tools._safe(gitops.push, "no-force")
    assert result["status"] == "needs_it" and "changes this computer does not have" in result["it_report"]
    assert signed_in.repos["no-force"].refs[b"refs/heads/ana/v"] == elsewhere


def test_an_edit_during_the_update_is_never_overwritten(signed_in, workspaces, monkeypatch):
    ws = joined(signed_in, "during")
    signed_in.server_commit("during", "main", {"README.md": b"# Sandbox\n\nNewer notes.\n"})
    original = gitops._track

    def track_then_edit(repo, refs):  # Claude edits a file while the server's changes are being fetched
        original(repo, refs)
        (ws / "README.md").write_bytes(b"# Sandbox\n\nEdited meanwhile.\n")

    monkeypatch.setattr(gitops, "_track", track_then_edit)
    with pytest.raises(NeedsIT, match="changed during an update"):
        gitops.update("during")
    assert (ws / "README.md").read_bytes() == b"# Sandbox\n\nEdited meanwhile.\n"
