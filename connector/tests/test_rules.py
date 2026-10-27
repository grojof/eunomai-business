"""Deny rules in the syntax of Claude Code's permission rules. The first command cases are the examples in Anthropic's
documentation (https://code.claude.com/docs/en/permissions#wildcard-patterns); the rest show that a deny rule errs
on the side of denying, so no quoting, loop or wrapper hides a command."""

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
    # compound commands, substitutions, loops, wrappers and assignments, as Claude Code checks them
    ("npm *", "cd app && npm ci", True), ("npm *", "echo $(npm view x)", True), ("npm *", "echo `npm ls`", True),
    ("npm *", "echo $( (npm ci) )", True), ("npm *", "cat <(npm ci)", True),
    ("git clean *", "for f in a; do git clean -f; done", True), ("npm *", "if true; then npm ci; fi", True),
    ("npm *", "while npm ci; do :; done", True), ("npm *", "! npm ci", True),
    ("npm test *", "timeout 30 npm test", True), ("npm *", "timeout -s KILL 30 npm ci", True),
    ("npm *", "time -p npm ci", True), ("npm *", "stdbuf -o L npm ci", True), ("npm *", "nice -n 5 npm ci", True),
    ("npm test *", "NODE_ENV=test npm test", True), ("rm *", "FOO=bar rm -rf tmp/", True),
    ("grep *", "xargs grep pattern", True), ("grep *", "xargs -n1 grep pattern", False),
    ("xargs *", "xargs -n1 rm x", True), ("timeout *", "timeout 30 npm test", True),
    ("npm ci", "npm\tci", True),
    # quotes, escapes, comments and heredocs never hide a command; a deny may then also catch a mention of one
    ("rm *", "echo \\' ; rm -rf x", True), ("rm *", "echo hi # don't\nrm -rf x", True),
    ("rm *", "cat > a.md <<EOF\ndon't\nEOF\nrm -rf x", True), ("npm *", "sh -c 'npm ci'", True),
    ("npm *", "echo 'a && npm ci'", True),
    ("npm *", "uv run pytest | tee out.txt", False), ("npm *", "npmx install", False),
])
def test_commands_are_found_wherever_they_can_run(spec, command, matches):
    assert rules.command_matches(spec, command) == matches


def test_a_bare_bash_rule_matches_every_command():
    assert rules.parse("Bash") == ("Bash", None) and rules.command_matches(None, "anything at all")


@pytest.mark.parametrize("spec, path, matches", [
    ("/data/raw/**", "data/raw/a.csv", True), ("/data/raw/**", "data/raw/2026/a.csv", True),
    ("/data/raw/**", "docs/data/raw/a.md", False), ("/data/raw/**", "DATA/Raw/a.csv", True),
    ("data/raw/**", "data/raw/a.csv", True), ("data/raw/**", "x/data/raw/a.csv", False),
    ("secrets/**", "secrets/a", True), ("secrets/**", "app/secrets/a", True),  # one folder: at any depth
    ("secrets/", "app/secrets/a", True), ("/data/", "data/a.csv", True),
    (".env", ".env", True), (".env", "app/.env", True), ("*.lock", "server/uv.lock", True),
    ("/*.lock", "uv.lock", True), ("/*.lock", "server/uv.lock", False),
    ("**/src/**", "vendor/pkg/src/lib.js", True), ("docs/?.md", "docs/a.md", True), ("docs/?.md", "docs/ab.md", False),
    ("data", "data/raw/a.csv", True),
])
def test_paths_match_as_gitignore_patterns_relative_to_the_workspace(spec, path, matches):
    assert rules.path_matches(spec, path) == matches


@pytest.mark.parametrize("rule", ["Read(x)", "Write(a/**)", "Bash(", "Edit", "Edit(//etc/x)", "Edit(~/x)", "", "npm",
                                  "Edit(data\\raw\\**)", "Edit(a/../b)", "Edit( data/** )", "Edit(!x)",
                                  "Edit(a/./b)"])
def test_rules_that_would_deny_nothing_or_reach_outside_are_refused(rule):
    with pytest.raises(ValueError):
        rules.parse(rule)


NPM = {"rule": "Bash(npm *)", "reason": "Node packages are not used here"}
RAW = {"rule": "Edit(/data/raw/**)", "reason": "raw data comes from the import"}
FOLDERS = ["C:/Users/me/eunomai-business-workspaces/Ventas"]
VENTAS = "/sessions/x/mnt/Ventas"


@pytest.mark.parametrize("tool, tool_input, cwd, folders, denied", [
    ("Bash", {"command": "npm install x"}, "/tmp", None, NPM["reason"]),
    ("mcp__workspace__bash", {"command": "cd a && npm ci"}, "/tmp", None, NPM["reason"]),
    ("Bash", {"command": "uv run pytest"}, "/tmp", None, None),
    ("Write", {"file_path": VENTAS + "/data/raw/a.csv"}, "", FOLDERS, RAW["reason"]),
    ("NotebookEdit", {"notebook_path": FOLDERS[0] + "/data/raw/n.ipynb"}, "", FOLDERS, RAW["reason"]),
    ("Edit", {"file_path": "/sessions/x/mnt/Otra/data/raw/a.csv"}, "", FOLDERS, None),
    ("Read", {"file_path": VENTAS + "/data/raw/a.csv"}, "", FOLDERS, None),
    ("Bash", {"command": "npm ci"}, "/sessions/x/mnt/Otra", FOLDERS, None),  # a project's rules, in its workspaces
    # the shell, best effort: what a command writes, moves or removes
    ("Bash", {"command": "echo x > data/raw/a.csv"}, VENTAS, FOLDERS, RAW["reason"]),
    ("Bash", {"command": "rm -rf data/raw"}, VENTAS, FOLDERS, RAW["reason"]),
    ("Bash", {"command": "rm -rf data"}, VENTAS, FOLDERS, RAW["reason"]),
    ("Bash", {"command": "mv data/raw old"}, VENTAS, FOLDERS, RAW["reason"]),
    ("Bash", {"command": "cp a.csv data/raw/a.csv"}, VENTAS, FOLDERS, RAW["reason"]),
    ("Bash", {"command": "cat data/raw/a.csv"}, VENTAS, FOLDERS, None),
    ("Bash", {"command": "python analiza.py data/raw/v.csv > informe.txt"}, VENTAS, FOLDERS, None),
    ("Bash", {"command": "cp data/raw/a.csv data/clean/"}, VENTAS, FOLDERS, None),
    ("Bash", {"command": "tar -tf data/raw/x.tar 2>/dev/null"}, VENTAS, FOLDERS, None),
])
def test_the_first_rule_that_matches_gives_its_reason(tool, tool_input, cwd, folders, denied):
    found = rules.deny_reason([NPM, RAW], tool, tool_input, cwd, folders)
    assert (found.split(" (")[0] if found else None) == denied


@pytest.mark.parametrize("deny, problem", [
    ([{"rule": "Bash(npm *)"}], "must have rule and reason"), ({"rule": "x"}, "must be a list"),
    ([{"paths": ["data/raw/**"], "reason": "r"}], "the old form"),
    ([{"rule": "Glob(x)", "reason": "r"}], "is not Bash"),
    ([{"rule": "Bash(npm *)", "reason": "two\nlines"}], "one line"),
    ([{"rule": "Bash(npm *)", "reason": "r", "examples": {"denied": ["pnpm i"]}}], "does not deny its example"),
    ([{"rule": "Bash(npm *)", "reason": "r", "examples": {"allowed": ["npm ci"]}}], "which its examples allow"),
    ([{"rule": "Edit(/data/**)", "reason": "r", "examples": {"denied": ["docs/a.md"]}}], "does not deny"),
    ([{"rule": "Bash(npm *)", "reason": "r", "examples": ["npm"]}], "examples must be"),
])
def test_the_build_refuses_rules_that_do_not_do_what_they_say(deny, problem):
    assert any(problem in found for found in rules.problems(deny))


def test_well_written_rules_pass_and_examples_are_a_build_time_check():
    assert rules.problems([dict(NPM, examples={"denied": ["npm ci"], "allowed": ["uv sync"]}), RAW]) == []
    wrong = [dict(NPM, examples={"denied": ["pnpm i"]})]
    assert rules.problems(wrong) and rules.problems(wrong, examples=False) == []
