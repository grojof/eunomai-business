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


@pytest.mark.parametrize("folder", [
    "C:/Users/me/eunomai-business-workspaces/ws",  # the computer's path, which Cowork's file tools use
    "/sessions/brave-owl/mnt/ws",  # mounted by name
    "/sessions/brave-owl/mnt/eunomai-business-workspaces/ws",  # mounted under its parent
    "/sessions/brave-owl/mnt/.requested/abc/ws",  # how a folder granted during a task is mounted has not been seen
])
def test_a_folder_granted_during_the_task_is_still_a_workspace(folder):
    """mcp__cowork__request_cowork_directory mounts a folder the task was not opened with."""
    assert denied(f"git -C {folder} status") and denied(f"cd {folder} && git stash")
    assert denied(f"rm -f {folder}/.git/index.lock")
    assert denied("git status", cwd=folder, tool="Bash")
    assert guard.decide({"tool_name": "Write", "tool_input": {"file_path": f"{folder}/AGENTS.md"}})
    assert guard.decide({"tool_name": "Edit", "tool_input": {"file_path": f"{folder}/.eunomai/project.toml"}})


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


# --- found by an independent review -----------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "echo x > $WS/.git/config", 'cp x "$WS/.git/hooks/pre-commit"', "cp x ~/eunomai-business-workspaces/ws/.git/config",
    "Set-Content .git/config x", "Add-Content .git/config x", "New-Item .git/hooks/x",
    "Set-Content /sessions/brave-owl/mnt/ws/.git/config x", "tee $WS/.git/config", "touch $WORKSPACE/.git/config",
    'echo x > "$WS/.git/config"', "echo x 2>> .git/config",
])
@pytest.mark.parametrize("cwd", [WS, "/sessions/brave-owl"])
def test_a_place_that_cannot_be_computed_counts_as_inside_when_it_names_the_repository(command, cwd):
    assert denied(command, cwd=cwd), command


def test_the_same_with_the_computers_own_shell_standing_in_a_workspace():
    assert denied("echo x > $WS/.git/config", cwd=WS, tool="Bash")
    assert denied("echo x > $WS/.git/config", cwd="/home/me/other", tool="Bash") is None


@pytest.mark.parametrize("command", [
    "env -u FOO git commit -am x", "env -C /sessions/brave-owl/mnt/ws -u A git commit -am x", "sudo -u root git add .",
    "sudo -E git add .",
    "setsid git add .", "ionice git add .", "ionice -c 3 git add .", "flock /tmp/l git add .",
    "flock -w 5 /tmp/l git add .", "flock /tmp/l -c 'git add .'", "coproc git add .", "case x in x) git add . ;; esac",
    "(cd /tmp/copy); git add .", "pushd /tmp/copy; popd; git add .", "if false; then cd /tmp/copy; fi; git add .",
    "false || cd /tmp/copy; git add .", "for d in a; do cd /tmp/copy; done; git add .",
    "cd /sessions/brave-owl/mnt/ws && (cd /tmp/copy); git add .",
    "cd /sessions/brave-owl/mnt/ws && pushd /tmp/copy; popd; git add .",
    "export GIT_DIR=/sessions/brave-owl/mnt/ws/.git; cd /tmp/copy; git add .",
    "GIT_DIR=/sessions/brave-owl/mnt/ws/.git; git --version; cd /tmp/copy; git add .",
    "cd /sessions/brave-owl/mnt/ws && git --work-tree=/tmp/x add .",
    "cd /sessions/brave-owl/mnt/ws && GIT_WORK_TREE=/tmp/x git add .",
    "cd /sessions/brave-owl/mnt/ws && git --work-tree=/tmp/x commit -m x", "git --work-tree=/tmp/x add .",
    "git diff -- --cached", "git diff -- --cached a.txt", "git diff -- a.txt b..c", "git diff -- a..b",
    "git grep --open-files-in=touch x", "git grep --op=touch x", "git grep --open=touch x",
    "git diff HEAD a.txt", "git diff main app", "git diff a.txt b.txt", "git diff a b c",
    'echo "$(git status)"', 'echo "`git stash`"', "bash -c 'cd /tmp; git status; cd -; git add .'",
    "sh <<EOF\ngit status\nEOF", "bash <<'EOF'\ngit add .\nEOF",
])
def test_what_changes_a_workspaces_repository_does_not_get_through(command):
    assert denied(command, cwd="/sessions/brave-owl"), command


@pytest.mark.parametrize("command", [
    'echo "git add"', "echo 'git status'", 'grep -r "git status" docs', "grep -rn 'git add' .", 'git log --grep="git add"',
    "cat > README.md <<EOF\n# Setup\ngit clone x\nEOF", "cat > notes.md <<'EOF'\ngit stash\ngit add .\nEOF\n",
    "cat <<-EOF\n\tgit push\n\tEOF", """python3 -c "print('git push')\"""", "# git status\nls", "ls # git add .",
    "git diff HEAD~1 HEAD", "git diff main HEAD", "git diff HEAD~3 HEAD~1", "git diff main~2 HEAD -- app",
    "git diff --stat main HEAD", "git diff 1a2b3c4 HEAD", "git diff HEAD^ HEAD",
    "git log --output-indicator-new=+ -p", "git show --output-indicator-old=- HEAD",
    "git --no-replace-objects log", "git --literal-pathspecs log -- a.txt",
    "git -C /sessions/brave-owl/mnt/outputs/ws add .", "git -C /sessions/brave-owl/mnt/uploads/ws status",
    "cd /sessions/brave-owl/mnt/outputs/ws && git stash",
    "git -C copy add .", "git -C copy status",
])
def test_what_a_model_writes_every_day_is_not_refused(command):
    assert denied(command, cwd="/sessions/brave-owl") is None, command


def test_env_C_moves_the_command_like_a_cd():
    assert denied("env -C /tmp/copy git commit -am x", cwd="/sessions/brave-owl") is None


def test_a_relative_git_C_counts_inside_when_the_folder_is_known_to_be_a_workspace():
    assert denied("git -C app status", cwd=WS)
    assert denied("cd /sessions/brave-owl/mnt/ws && git -C app add .", cwd="")


@pytest.mark.parametrize("command", ["git log --output=x", "git log --output x", "git diff --cached --output=x"])
def test_the_exact_output_option_is_still_refused(command):
    assert denied(command)


def test_the_parser_never_stops_a_hook_whatever_it_reads():
    for command in ['echo "unterminated', "echo 'unterminated", "cat <<EOF", "$(", "`", "(((", ")))", "\\", "<<", "x <(",
                    "a >", "cd", "pushd", "popd", "git -C", "git --git-dir", "find", "sh -c", "eval", "env -u", "for", "fi"]:
        guard.decide({"tool_name": SANDBOX, "cwd": WS, "tool_input": {"command": command}})


# --- a second review: this rule helps against mistakes; the barrier is the connector -------------------------------

@pytest.mark.parametrize("command", [
    "git -C mnt/ws add .", "git -C ../mnt/ws add .", "git -C . add .", "git -C ../copy commit -m x", "git -C ws/app add .",
    "cd /tmp/copy | cat; git add .", "cd /tmp/copy & git add .", "cd /tmp/copy &\ngit add .", "true | cd /tmp/copy; git add .",
    "echo 'git add .' | sh", "echo 'git add .' | bash", "printf 'git stash' | /bin/sh", "bash <<< 'git add .'",
    "sh <<< 'git stash'", "git grep -nO'touch .git/p' two", "git grep -hO'x' two", "git grep -O x",
])
def test_what_a_mistake_reaches_is_refused(command):
    assert denied(command, cwd="/sessions/brave-owl"), command


@pytest.mark.parametrize("command", ["echo x >& .git/config", "echo x &> .git/config", "echo x &>> .git/config"])
def test_a_redirection_into_the_repository_is_seen(command):
    assert denied(command), command


@pytest.mark.parametrize("command", ["ls 2>&1 | head", "ls >&2", "ls 2>&-"])
def test_a_redirection_to_a_stream_is_no_file(command):
    assert denied(command) is None, command


@pytest.mark.parametrize("command", [
    "cp x ~/eunomai-business-workspaces/ws/.git/config", "echo x > ~/eunomai-business-workspaces/ws/.git/hooks/p",
    r'echo x > "C:\Users\me\eunomai-business-workspaces\ws\.git\config"',
])
def test_the_computers_own_shell_outside_a_workspace_is_refused_a_path_that_names_one(command):
    assert denied(command, cwd="C:/Users/me/other", tool="Bash"), command


@pytest.mark.parametrize("command", [
    r'git -C "C:\Users\me\eunomai-business-workspaces\ws" add .',
    r"git -C 'C:\Users\me\eunomai-business-workspaces\ws' add .",
    r'cd "C:\Users\me\eunomai-business-workspaces\ws" && git add .',
])
def test_a_windows_path_reads_the_same_in_either_quote(command):
    assert denied(command, cwd="C:/Users/me", tool="Bash"), command


@pytest.mark.parametrize("command", [
    r'echo "a\"b"; git log', r'echo "cost: \$5" > /tmp/x', "git clone /sessions/brave-owl/mnt/ws /tmp/c",
    "rm -rf /tmp/c && git clone /sessions/brave-owl/mnt/ws /tmp/c", "git clone mnt/ws /tmp/c",
    "git clone --depth 1 /sessions/brave-owl/mnt/ws /tmp/c",
    "mkdir -p /tmp/copy && cd /tmp/copy\ngit init\ngit add .", "cd /tmp/copy && ls\ngit status", "cd /tmp/copy\ngit status",
    "cat > /tmp/n.md <<\\EOF\ngit clone x\nEOF", "cat > /tmp/n.md << 'END OF TEXT'\ngit clone x\nEND OF TEXT",
    'cat > /tmp/n.md << "END OF TEXT"\ngit stash\nEND OF TEXT',
    "git branch --show-current", "git branch", "git branch -a", "git branch -r", "git branch -vv", "git branch --list",
    "git remote", "git remote -v", "git tag", "git tag -l", "git tag --list 'v*'", "git config --get user.name",
    "git config --get-all remote.origin.url", "git config --list", "git --exec-path",
])
def test_daily_commands_that_real_git_shows_do_not_write_pass(command):
    assert denied(command, cwd="/sessions/brave-owl") is None, command


@pytest.mark.parametrize("command", [
    "git branch new", "git branch -d old", "git branch -D old", "git branch -m a b", "git branch -u origin/x",
    "git tag v1", "git tag -d v1", "git tag -a v1 -m x", "git remote add o x", "git remote remove o",
    "git config user.name x", "git config --unset user.name", "git config --add a.b c", "git clone x", "git clone x y",
    "git clone /tmp/src /sessions/brave-owl/mnt/ws/sub", "git --exec-path=/tmp/x log",
])
def test_their_writing_forms_stay_refused(command):
    assert denied(command, cwd="/sessions/brave-owl"), command
