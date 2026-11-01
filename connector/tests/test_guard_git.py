"""Git from the sandbox shell in a workspace: Cowork's sandbox can create files there but not delete them, so a git
command that touches .git leaves a lock or temporary objects behind, and the next save stops."""

import io
import json
import sys

import pytest

from eunomai_business import guard

SANDBOX = "mcp__workspace__bash"
WS = "/sessions/brave-owl/mnt/ws"


@pytest.fixture(autouse=True)
def one_workspace(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_REMOTE_SESSION_ID", raising=False)
    monkeypatch.setattr(guard, "_workspace_folders", lambda: ["C:/Users/me/eunomai-business-workspaces/ws"])


def denied(command: str, cwd: str = WS, tool: str = SANDBOX) -> str | None:
    return guard.decide({"tool_name": tool, "cwd": cwd, "tool_input": {"command": command}})


@pytest.mark.parametrize("command", [
    "git status", "git status --short", "git stash", "git stash list", "git add .", "git commit -m x", "git fetch",
    "git pull", "git checkout -b x", "git switch main", "git reset --hard", "git merge x", "git rebase main", "git gc",
    "git init", "git clean -fd", "git branch x", "git tag v1", "git config user.name x", "git update-index --refresh",
    "git rm a.txt", "git mv a b", "git restore a.txt", "git worktree add ../x", "git maintenance run",
    # measured: these refresh the index when files look changed, and every file does between Windows and the sandbox
    "git diff", "git diff --stat", "git diff HEAD", "git diff main", "git diff a.txt b.txt", "git diff -- a.txt",
    "git describe --dirty", "git --no-optional-locks diff", "git --no-optional-locks status",
])
def test_a_git_command_that_can_write_is_denied_in_a_workspace(command):
    reason = denied(command)
    assert reason and "workspace_status" in reason


@pytest.mark.parametrize("command", [
    "cd /sessions/brave-owl/mnt/ws && git status", "cd /sessions/brave-owl/mnt/ws; git stash",
    "git -C /sessions/brave-owl/mnt/ws status --short", "git -C /sessions/brave-owl/mnt/eunomai-business-workspaces/ws add .",
    "git -C /sessions/brave-owl/mnt/ws/app status", "git --git-dir=/sessions/brave-owl/mnt/ws/.git status",
    "git --git-dir /sessions/brave-owl/mnt/ws/.git status", "git --work-tree=/sessions/brave-owl/mnt/ws status",
    "GIT_DIR=/sessions/brave-owl/mnt/ws/.git git status",
    "/usr/bin/git status", '"git" status', "'git' status", 'g"i"t status', "\\git status", "git\tstatus",
    "git  status", "git.exe status", "command git status", "builtin git status", "env git status", "env -i git status",
    "env A=1 git status", "exec git status", "eval git status", "GIT_PAGER=cat git status", "A=1 B=2 git stash",
    "timeout 5 git status", "timeout -k 1 5 git status", "nice -n 5 git status", "nohup git status", "time git status",
    "sudo git status", "sh -c 'git status'", 'bash -lc "git status"', "sh -c 'cd /sessions/brave-owl/mnt/ws && git status'",
    "(git status)", "{ git status; }", "echo $(git status)", "echo `git status`", "cat <(git status)",
    "for f in a; do git add $f; done", "while true; do git fetch; done", "if true; then git status; fi",
    "git log && git status", "git log; git stash", "git log | head; git stash", "true || git stash", "ls & git status",
    "ls\ngit status", "find . -name x -exec git add {} \\;", "find . -execdir git add {} +", "ls | xargs git add",
    "ls | xargs -0 git add", "ls | xargs -n 1 git add",
    "git --no-pager status", "git -p status", "git -c core.pager=cat log", "git -c alias.x=status x",
    "git --exec-path=/tmp/x log", "git --unknown-option log", "git frobnicate",
    "git log --output=/tmp/x", "git log --output /tmp/x", "git show --output=x HEAD", "git diff --cached --output=x",
    "git grep -O foo", "git grep --open-files-in-pager=vi foo", "git log --ext-diff", "git reflog expire --all",
])
def test_the_usual_ways_of_writing_a_command_do_not_hide_it(command):
    assert denied(command), command


@pytest.mark.parametrize("command", [
    "git log --oneline -5", "git log -p -- app/main.py", "git log --all --graph", "git show HEAD",
    "git show HEAD:app/main.py", "git --no-pager log", "git --no-pager show HEAD", "git -P log",
    "git diff --cached", "git diff --staged --stat", "git diff --cached -- a.txt", "git diff main..HEAD",
    "git diff HEAD~1...HEAD -- app", "git diff --no-index /tmp/a /tmp/b", "git blame app/main.py", "git ls-files",
    "git ls-tree HEAD", "git cat-file -p HEAD", "git rev-parse HEAD", "git rev-list HEAD", "git shortlog -s HEAD",
    "git grep foo", "git merge-base main HEAD", "git show-ref", "git for-each-ref", "git name-rev HEAD",
    "git version", "git --version", "git help log", "git reflog", "git reflog show", "git log | head -5",
    "cd /sessions/brave-owl/mnt/ws && git log", "git -C /sessions/brave-owl/mnt/ws log --oneline",
    "git log --oneline > /tmp/log.txt", "timeout 5 git log", "A=1 git log", "sh -c 'git log'",
])
def test_what_truly_never_writes_stays_allowed_in_a_workspace(command):
    assert denied(command) is None, command


@pytest.mark.parametrize("command", [
    "git -C /tmp/copy status", "git -C /tmp/copy add .", "git -C /tmp/copy commit -m x", "git -C /tmp/copy stash",
    "git -C /tmp/copy diff", "git -C '/tmp/my copy' status", 'git -C "/tmp/copy" status', "git -C/tmp/copy status",
    "cd /tmp/copy && git status", "cd /tmp/copy; git stash", "cd /tmp && cd copy && git status",
    "git --git-dir=/tmp/copy/.git status", "git --git-dir=/tmp/copy/.git --work-tree=/tmp/copy add .",
    "GIT_DIR=/tmp/copy/.git git status", "(cd /tmp/copy && git status)", "sh -c 'cd /tmp/copy && git status'",
    "cp -r /sessions/brave-owl/mnt/ws /tmp/ws && git -C /tmp/ws status",  # a copy named like the workspace
    "cp -r /sessions/brave-owl/mnt/ws /tmp/ws && cd /tmp/ws && git status",
    "git -C /tmp/copy -C sub status",
])
def test_a_copy_elsewhere_stays_allowed(command):
    assert denied(command) is None, command


@pytest.mark.parametrize("command", [
    "pytest -q", "ls -la", "ls .git", "cat .gitignore", "cat .git/HEAD", "digit status", "echo legit status",
    "legit status", "grep -rn foo .", "echo ok > .gitignore", "which git", "command -v git", "uv run pytest",
])
def test_everything_else_is_left_alone(command):
    assert denied(command) is None, command


def test_a_workspace_in_the_folder_the_hook_receives_counts_with_any_shell():
    assert denied("git status", cwd=WS, tool="Bash")
    assert denied("git status", cwd=WS + "/app", tool="Bash")
    assert denied("cd app && git status", cwd=WS, tool="Bash")


def test_outside_workspaces_the_computers_own_shell_is_left_alone():
    assert denied("git status", cwd="/home/me/other", tool="Bash") is None
    assert denied("git commit -m x", cwd="/home/me/other", tool="Bash") is None


def test_the_sandbox_shell_keeps_its_folder_from_an_earlier_call_so_a_bare_command_counts_as_inside():
    # a `cd` in an earlier call is not in this command, and the hook does not see where the shell stands (H19)
    assert denied("git status", cwd="C:/Users/me/AppData/Roaming/Claude/session")
    assert denied("git status", cwd="")
    assert denied("cd app && git status", cwd="")


def test_without_workspaces_on_the_computer_nothing_is_denied(monkeypatch):
    monkeypatch.setattr(guard, "_workspace_folders", lambda: [])
    assert denied("git status", cwd="") is None
    assert denied("rm -f .git/index.lock", cwd="") is None


@pytest.mark.parametrize("command", [
    "rm .git/index.lock", "rm -f .git/index.lock", "rm -rf .git", "rm -rf .git/", "rm -rf ./.git/objects/tmp_obj_1",
    "rm -f /sessions/brave-owl/mnt/ws/.git/index.lock", "unlink .git/index.lock", "rmdir .git/refs/stash",
    "mv .git/index.lock /tmp/x", "mv .git /tmp/x", "cd .git && rm index.lock", "cd .git/objects; rm -rf tmp_1",
    "cd /sessions/brave-owl/mnt/ws/.git && rm index.lock", "find .git -name '*.lock' -delete",
    "find .git -name '*.lock' -exec rm {} \\;", "find /sessions/brave-owl/mnt/ws/.git -type f -delete",
    "python -c \"import os; os.remove('.git/index.lock')\"", "python3 -c 'import shutil; shutil.rmtree(\".git\")'",
    "touch .git/index.lock", "truncate -s 0 .git/index", "echo x > .git/config", "echo x >> .git/hooks/post-commit",
    "cp a .git/hooks/post-commit", "sed -i s/a/b/ .git/config", "tee .git/config", "ln -s /x .git/hooks",
    "mkdir .git/refs/x", "sh -c 'rm -f .git/index.lock'", "timeout 5 rm .git/index.lock",
])
def test_writing_or_deleting_inside_a_workspaces_repository_is_denied(command):
    assert denied(command), command


@pytest.mark.parametrize("command", [
    "rm -rf /tmp/copy/.git", "rm -f /tmp/copy/.git/index.lock", "echo x > /tmp/copy/.git/config",
    "cd /tmp/copy && rm .git/index.lock", "cd /tmp/copy/.git && rm index.lock", "find /tmp/copy/.git -delete",
    "rm .gitignore", "rm -rf build", "rm -f app/.gitkeep",
])
def test_a_repository_elsewhere_and_files_with_similar_names_are_left_alone(command):
    assert denied(command) is None, command


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_the_file_tools_cannot_write_into_a_workspaces_repository(tool):
    found = guard.decide({"tool_name": tool, "tool_input": {"file_path": WS + "/.git/index.lock"}})
    assert found and "only IT changes it" in found


def test_the_rule_is_built_in_whatever_the_organization_configures(monkeypatch, capsys, tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text('{"deny": []}')
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "hook_event_name": "PreToolUse", "tool_name": SANDBOX, "tool_input": {"command": "git status"}})))
    with pytest.raises(SystemExit):
        guard.main(["--policy", str(policy)])
    decision = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny" and "workspace_status" in decision["permissionDecisionReason"]
