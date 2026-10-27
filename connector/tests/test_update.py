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
    ws = proposed(signed_in, name, "draft/report", {"report.md": b"quarterly report\n"})
    signed_in.accept(name, "draft/report", squash=squash)
    result = gitops.update(name)
    assert result["status"] == "updated" and result["branch"] == "main"
    assert result["retired_version"] == "draft/report" and local_branches(ws) == {"main"}
    assert (ws / "report.md").read_bytes() == b"quarterly report\n"
    assert "accepted" in result["user_message"]
    assert any(ref.endswith("/draft/report") for ref in backups(ws))  # the retired version can still be recovered


def test_unsaved_changes_are_saved_before_anything_else(signed_in, workspaces):
    ws = joined(signed_in, "unsaved")
    gitops.branch("unsaved", "draft/draft")
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
    gitops.branch("combine", "draft/mine")
    (ws / "mine.md").write_bytes(b"mine\n")
    gitops.save("combine", "Mine")
    signed_in.server_commit("combine", "main", {"theirs.md": b"theirs\n"})
    result = gitops.update("combine")
    assert result["status"] == "updated" and result["branch"] == "draft/mine"
    assert (ws / "mine.md").read_bytes() == b"mine\n" and (ws / "theirs.md").read_bytes() == b"theirs\n"
    with gitops._open(str(ws)) as repo:
        assert len(repo[repo.head()].parents) == 2


def test_a_conflict_stops_without_touching_anything(signed_in, workspaces, monkeypatch):
    monkeypatch.setenv("EUNOMAI_SUPPORT_EMAIL", "it@example.test")
    ws = joined(signed_in, "conflict")
    gitops.branch("conflict", "draft/edit")
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
    gitops.branch("same-file", "draft/top")
    (ws / "list.md").write_bytes(b"ONE\ntwo\nthree\nfour\nfive\n")
    gitops.save("same-file", "Top line")
    signed_in.server_commit("same-file", "main", {"list.md": b"one\ntwo\nthree\nfour\nFIVE\n"})
    with pytest.raises(NeedsIT, match="changed the same files"):
        gitops.update("same-file")
    assert (ws / "list.md").read_bytes() == b"ONE\ntwo\nthree\nfour\nfive\n"


def test_identical_changes_on_both_sides_combine(signed_in, workspaces):
    ws = joined(signed_in, "identical")
    gitops.branch("identical", "draft/same")
    (ws / "shared.md").write_bytes(b"same text\n")
    gitops.save("identical", "Same file")
    signed_in.server_commit("identical", "main", {"shared.md": b"same text\n", "other.md": b"other\n"})
    assert gitops.update("identical")["status"] == "updated"
    assert (ws / "other.md").exists() and (ws / "shared.md").read_bytes() == b"same text\n"


def test_a_version_changed_elsewhere_stops(signed_in, workspaces):
    ws = proposed(signed_in, "elsewhere", "draft/shared", {"a.md": b"a\n"})
    signed_in.server_commit("elsewhere", "draft/shared", {"b.md": b"from another computer\n"})
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
    gitops.branch("empty-version", "draft/idea")
    signed_in.server_commit("empty-version", "main", {"news.md": b"news\n"})
    result = gitops.update("empty-version")
    assert result["status"] == "updated" and result["branch"] == "draft/idea" and "retired_version" not in result
    assert (ws / "news.md").exists() and "accepted" not in result["user_message"]


def test_versions_never_stack_on_another_version(signed_in, workspaces):
    joined(signed_in, "stack")
    gitops.branch("stack", "draft/one")
    with pytest.raises(PermissionError, match="start from the main branch"):
        gitops.branch("stack", "draft/two")


def test_the_status_shows_the_versions_proposal(signed_in, workspaces):
    proposed(signed_in, "with-proposal", "draft/x", {"x.md": b"x\n"})
    status = tools._safe(tools._status, "with-proposal")
    assert status["proposal"]["state"] == "open" and status["proposal"]["merged"] is False
    assert status["proposal"]["review"] == {"decision": "none", "complete": True, "requests": []}


def review(id, who, state, body="", at="2026-10-26T10:00:00Z", **more):
    return {"id": id, "user": {"login": who}, "state": state, "body": body, "submitted_at": at,
            "comments_count": len(more.get("inline", [])), **more}


def line_comment(who, body, path, position, at, resolved=False):
    return {"user": {"login": who}, "body": body, "path": path, "position": position, "created_at": at,
            "resolver": {"login": who} if resolved else None}


def review_of(server, name, reviews, comments=()):
    """The review `workspace_status` reports once the fake server holds these reviews and comments."""
    if name not in server.repos:
        proposed(server, name, f"draft/{name}", {"x.md": b"x\n"})
    pull = next(p for p in server.pulls if p["repo"] == name)
    pull["reviews"], pull["comments"] = list(reviews), list(comments)
    return tools._safe(tools._status, name)["proposal"]["review"]


def test_the_status_brings_the_changes_reviewers_ask_for(signed_in, workspaces):
    result = review_of(signed_in, "reviewed", [
        review(1, "it-one", "APPROVED"),
        review(2, "it-two", "REQUEST_CHANGES", "Production must be the default.", "2026-10-26T11:00:00Z", official=True,
               inline=[line_comment("it-two", "No one approves their own request.", "app/x.py", 12,
                                    "2026-10-26T11:00:01Z"),
                       line_comment("it-two", "Already fixed.", "app/y.py", 3, "2026-10-26T11:00:02Z", True)]),
        review(3, "it-three", "REQUEST_CHANGES", "Old remark", "2026-10-26T09:00:00Z", dismissed=True)],
        [{"user": {"login": "it-one"}, "body": "x" * 3000, "created_at": "2026-10-26T12:00:00Z"},
         {"user": {"login": "tester"}, "body": "I am the author", "created_at": "2026-10-26T12:30:00Z"}])
    assert result["decision"] == "changes_requested" and result["complete"] is True
    texts = [r["text"] for r in result["requests"]]
    assert texts[:2] == ["Production must be the default.", "No one approves their own request."]
    assert "Old remark" not in texts and "Already fixed." not in texts  # dismissed and resolved are not asked
    assert "I am the author" not in texts  # the author's own comments are not requests
    assert result["requests"][0]["official"] is True and result["requests"][0]["earlier_version"] is False
    assert result["requests"][1]["file"] == "app/x.py" and result["requests"][1]["line"] == 12
    assert len(texts[2]) == 2000 and result["requests"][2]["truncated"] is True


def test_a_long_review_note_reaches_the_specialist_whole(signed_in, workspaces):
    note = "Point. " * 1200  # a long review, as IT writes them
    result = review_of(signed_in, "long-note", [review(1, "it", "REQUEST_CHANGES", note)])
    assert result["requests"][0]["text"] == note[:10_000] and len(note) > 8_000


def test_each_reviewers_latest_decision_counts(signed_in, workspaces):
    asked_then_approved = [review(1, "it", "REQUEST_CHANGES", "Fix A"), review(2, "it", "APPROVED", "Thanks")]
    assert review_of(signed_in, "approved-later", asked_then_approved)["decision"] == "approved"
    asked_then_commented = [review(1, "it", "REQUEST_CHANGES", "Fix A"), review(2, "it", "COMMENT", "Also B")]
    result = review_of(signed_in, "commented-later", asked_then_commented)
    assert result["decision"] == "changes_requested"  # a plain comment does not undo a request for changes
    assert [r["text"] for r in result["requests"]] == ["Also B"]  # only each reviewer's latest note
    only_dismissed = [review(1, "it", "REQUEST_CHANGES", "Fix A", dismissed=True,
                             inline=[line_comment("it", "Line remark", "a.py", 1, "2026-10-26T10:00:01Z")])]
    result = review_of(signed_in, "dismissed", only_dismissed)
    assert result["decision"] == "none" and result["requests"] == []  # nor its line comments


def test_line_comments_the_same_reviewer_approved_afterwards_are_settled(signed_in, workspaces):
    result = review_of(signed_in, "approved-lines", [
        review(1, "it", "REQUEST_CHANGES", "", inline=[line_comment("it", "Fix this line", "a.py", 1,
                                                                    "2026-10-26T10:00:01Z")]),
        review(2, "it", "APPROVED", "", "2026-10-26T11:00:00Z")])
    assert result == {"decision": "approved", "complete": True, "requests": []}


def test_requests_made_before_the_version_was_sent_again_wait_for_a_new_review(signed_in, workspaces):
    result = review_of(signed_in, "sent-again", [review(1, "it", "REQUEST_CHANGES", "Fix A", commit_id="0" * 40)])
    assert result["decision"] == "updated_since_requests" and result["requests"][0]["earlier_version"] is True
    pull = next(p for p in signed_in.pulls if p["repo"] == "sent-again")
    marked_stale = [review(1, "it", "REQUEST_CHANGES", "Fix A", commit_id=pull["head"]["sha"], stale=True)]
    assert review_of(signed_in, "sent-again", marked_stale)["decision"] == "updated_since_requests"


def test_a_review_read_in_part_says_so(signed_in, workspaces):
    result = review_of(signed_in, "partial", [review(1, "it", "REQUEST_CHANGES", "See lines", inline_status="500 Error",
                                                     inline=[line_comment("it", "x", "a.py", 1, "2026-10-26T10:00:01Z")])])
    assert result["complete"] is False and result["decision"] == "changes_requested"


def test_a_closed_proposal_has_no_review(signed_in, workspaces):
    proposed(signed_in, "closed-one", "draft/c", {"x.md": b"x\n"})
    next(p for p in signed_in.pulls if p["repo"] == "closed-one")["state"] = "closed"
    assert "review" not in tools._safe(tools._status, "closed-one")["proposal"]


def test_sending_never_overwrites_the_server(signed_in, workspaces):
    ws = proposed(signed_in, "no-force", "draft/v", {"a.md": b"a\n"})
    elsewhere = signed_in.server_commit("no-force", "draft/v", {"b.md": b"from another computer\n"})
    (ws / "c.md").write_bytes(b"c\n")
    gitops.save("no-force", "Local change")
    result = tools._safe(gitops.push, "no-force")
    assert result["status"] == "needs_it" and "changes this computer does not have" in result["it_report"]
    assert signed_in.repos["no-force"].refs[b"refs/heads/draft/v"] == elsewhere


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
