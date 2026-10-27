"""Deny rules in the syntax of Claude Code's permission rules. The command cases are the examples in Anthropic's
documentation (https://code.claude.com/docs/en/permissions#wildcard-patterns), so the guard reads a rule as
Claude Code would."""

import pytest

from eunomai_business import rules


@pytest.mark.parametrize("spec, command, matches", [
    # Anthropic's table: rule, commands it matches, nearby commands it does not
    ("npm run build", "npm run build", True), ("npm run build", "npm run build --watch", False),
    ("npm run *", "npm run build", True), ("npm run *", "npm run test --watch", True), ("npm run *", "npm run", True),
    ("npm run *", "npm install", False),
    ("git log * main", "git log --oneline main", True), ("git log * main", "git log -5 main", True),
    ("git log * main", "git log main", False), ("git log * main", "git push origin main", False),
    ("git * main", "git merge main", True), ("git * main", "git push origin main", True),
    ("git * main", "git log", False),
    ("* --version", "node --version", True), ("* --version", "node -v", False),
    ("ls *", "ls -la", True), ("ls *", "ls", True), ("ls *", "lsof", False),
    ("ls*", "ls -la", True), ("ls*", "lsof", True),
    ("* --help *", "npm --help x", True), ("* --help *", "npm --help", False),
    ("ls:*", "ls -la", True), ("ls:*", "lsof", False),
    # compound commands, substitutions, wrappers and assignments, as Claude Code splits and strips them
    ("npm *", "cd app && npm ci", True), ("npm *", "echo $(npm view x)", True), ("npm *", "echo `npm ls`", True),
    ("npm *", "uv run pytest | tee out.txt", False), ("npm *", "echo 'a && npm ci'", False),
    ("npm test *", "timeout 30 npm test", True), ("npm test *", "NODE_ENV=test npm test", True),
    ("rm *", "FOO=bar rm -rf tmp/", True), ("grep *", "xargs grep pattern", True),
    ("grep *", "xargs -n1 grep pattern", False),
])
def test_commands_match_as_claude_code_matches_them(spec, command, matches):
    assert rules.command_matches(spec, command) == matches


def test_a_bare_bash_rule_matches_every_command():
    assert rules.parse("Bash") == ("Bash", None) and rules.command_matches(None, "anything at all")


@pytest.mark.parametrize("spec, path, matches", [
    ("/data/raw/**", "data/raw/a.csv", True), ("/data/raw/**", "data/raw/2026/a.csv", True),
    ("/data/raw/**", "docs/data/raw/a.md", False), ("/data/raw/**", "DATA/Raw/a.csv", True),
    ("data/raw/**", "data/raw/a.csv", True), ("data/raw/**", "x/data/raw/a.csv", False),
    ("secrets/**", "secrets/a", True), ("secrets/**", "app/secrets/a", True),  # one folder: at any depth
    (".env", ".env", True), (".env", "app/.env", True), ("*.lock", "server/uv.lock", True),
    ("/*.lock", "uv.lock", True), ("/*.lock", "server/uv.lock", False),
    ("**/src/**", "vendor/pkg/src/lib.js", True), ("docs/?.md", "docs/a.md", True), ("docs/?.md", "docs/ab.md", False),
    ("a+b/[x].txt", "a+b/[x].txt", True), ("data", "data/raw/a.csv", True),
])
def test_paths_match_as_gitignore_patterns_relative_to_the_workspace(spec, path, matches):
    assert rules.path_matches(spec, path) == matches


@pytest.mark.parametrize("rule", ["Read(x)", "Write(a/**)", "Bash(", "Edit", "Edit(//etc/x)", "Edit(~/x)", "", "npm"])
def test_only_bash_and_edit_rules_relative_to_the_workspace(rule):
    with pytest.raises(ValueError):
        rules.parse(rule)


NPM = {"rule": "Bash(npm *)", "reason": "Node packages are not used here"}
RAW = {"rule": "Edit(/data/raw/**)", "reason": "raw data comes from the import"}
FOLDERS = ["C:/Users/me/eunomai-business-workspaces/Ventas"]


@pytest.mark.parametrize("tool, tool_input, cwd, folders, denied", [
    ("Bash", {"command": "npm install x"}, "/tmp", None, "Node packages are not used here"),
    ("mcp__workspace__bash", {"command": "cd a && npm ci"}, "/tmp", None, "Node packages are not used here"),
    ("Bash", {"command": "uv run pytest"}, "/tmp", None, None),
    ("Write", {"file_path": "/sessions/x/mnt/Ventas/data/raw/a.csv"}, "", FOLDERS, "raw data comes from the import"),
    ("NotebookEdit", {"notebook_path": "C:/Users/me/eunomai-business-workspaces/Ventas/data/raw/n.ipynb"}, "",
     FOLDERS, "raw data comes from the import"),
    ("Edit", {"file_path": "/sessions/x/mnt/Otra/data/raw/a.csv"}, "", FOLDERS, None),
    ("Bash", {"command": "echo x > data/raw/a.csv"}, "/sessions/x/mnt/Ventas", FOLDERS,
     "raw data comes from the import"),
    ("Bash", {"command": "cat data/raw/a.csv"}, "/sessions/x/mnt/Ventas", FOLDERS, None),
    ("Bash", {"command": "npm ci"}, "/sessions/x/mnt/Otra", FOLDERS, None),  # a project's rules, in its workspaces
    ("Read", {"file_path": "/sessions/x/mnt/Ventas/data/raw/a.csv"}, "", FOLDERS, None),
])
def test_the_first_rule_that_matches_gives_its_reason(tool, tool_input, cwd, folders, denied):
    found = rules.deny_reason([NPM, RAW], tool, tool_input, cwd, folders)
    assert (found.split(" (")[0] if found else None) == denied


@pytest.mark.parametrize("deny, problem", [
    ([{"rule": "Bash(npm *)"}], "must have rule and reason"), ({"rule": "x"}, "must be a list"),
    ([{"rule": "Glob(x)", "reason": "r"}], "is not Bash"),
    ([{"rule": "Bash(npm *)", "reason": "two\nlines"}], "one line"),
    ([{"rule": "Bash(npm *)", "reason": "r", "examples": {"denied": ["pnpm i"]}}], "does not deny its example"),
    ([{"rule": "Bash(npm *)", "reason": "r", "examples": {"allowed": ["npm ci"]}}], "which its examples allow"),
    ([{"rule": "Edit(/data/**)", "reason": "r", "examples": {"denied": ["docs/a.md"]}}], "does not deny"),
    ([{"rule": "Bash(npm *)", "reason": "r", "examples": ["npm"]}], "examples must be"),
])
def test_the_build_refuses_rules_that_do_not_do_what_they_say(deny, problem):
    assert any(problem in found for found in rules.problems(deny))


def test_well_written_rules_pass():
    assert rules.problems([dict(NPM, examples={"denied": ["npm ci"], "allowed": ["uv sync"]}), RAW]) == []
