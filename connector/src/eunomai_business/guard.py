"""Files Claude never writes or saves: the project's context and the repository's configuration, which only IT
changes, and anything Windows runs or opens as a program on a double click, since the workspace folder lives on
the user's computer.

The same rules serve two barriers. The PreToolUse hook denies a write as it is attempted (the file tools always; the
sandbox shell best effort, since it sees a command as text), so Claude learns at once and nothing dangerous lands
on the computer. `version_save` enforces them on the host, where the sandbox cannot reach: context and
configuration files are put back as the last save point has them, and an executable stops the save.

Executables are refused everywhere Claude writes. Context and configuration rules apply inside workspaces only, so
the plugin does not get in the way of Cowork's own files elsewhere.

The hook also keeps the sandbox shell out of a workspace's repository: Cowork's sandbox can create files there but
not delete them, so a git command that touches .git leaves a lock or temporary objects behind, and the next save
stops. Like every rule on a shell command, this sees text and prevents mistakes; it is not a boundary.
"""

import argparse
import json
import os
import re
import sys
from typing import NamedTuple

from . import data_dir, rules

CONTEXT_FILES = {"agents.md", "claude.md"}
# Claude's configuration, the repository's, the project's declaration, and continuous integration, which runs on
# IT's servers.
CONFIG_FOLDERS = {".claude", ".eunomai", ".git", ".gitea", ".github", ".forgejo", ".circleci", ".woodpecker"}
CONFIG_FILES = {".mcp.json", ".gitlab-ci.yml", ".woodpecker.yml", ".drone.yml", "jenkinsfile", "azure-pipelines.yml",
                "bitbucket-pipelines.yml"}
# What Windows runs, installs or follows on a double click. Script sources that need an interpreter's file
# association (.js through Windows Script Host, .py through the Python launcher) cannot be refused without refusing
# every web application; turning those associations off is an operating-system control (docs/barriers.md).
HOST_EXECUTABLES = {".appinstaller", ".application", ".appref-ms", ".appx", ".bat", ".chm", ".cmd", ".com", ".cpl",
                    ".diagcab", ".exe", ".gadget", ".hta", ".jar", ".jse", ".library-ms", ".lnk", ".msc", ".msi",
                    ".msix", ".msp", ".pif", ".ps1", ".psd1", ".psm1", ".reg", ".scf", ".scr", ".search-ms",
                    ".settingcontent-ms", ".url", ".vbe", ".vbs", ".wsf", ".wsh", ".xll"}
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_SHELL_TOOLS = {"Bash", "mcp__workspace__bash"}
# In a command, extensions that also end host names (example.com) or common words are left to version_save.
_SHELL_EXTENSIONS = HOST_EXECUTABLES - {".com", ".cpl", ".msc", ".pif", ".scf", ".url"}
_WRITES = r"(?:>|\btee\b|\bcp\b|\bmv\b|\bln\b|\btouch\b|\bmkdir\b|sed\s+-i|Set-Content|Add-Content|Out-File|New-Item)" \
          r"[^|;&]*?"
_EXECUTABLE_WRITE = re.compile(
    _WRITES + r"([\w.-]+(?:" + "|".join(re.escape(e) for e in sorted(_SHELL_EXTENSIONS)) + r"))\b", re.IGNORECASE)
_FOLDERS = "|".join(re.escape(f) for f in sorted(CONFIG_FOLDERS))
_FILES = "|".join(re.escape(f) for f in sorted(CONFIG_FILES))
_PROTECTED_WRITE = re.compile(
    _WRITES + r"(?<![\w.-])((?:AGENTS|CLAUDE)\.md\b|[\w./\\-]*?(?:" + _FOLDERS + r")(?:[\\/]|\b(?![\w.-]))"
    r"|[\w./\\-]*?(?:" + _FILES + r")\b)", re.IGNORECASE)

# An 8.3 short name (AGENTS~1.MD, CLAUDE~1) can stand for a protected file or folder on Windows.
_SHORT_NAME = re.compile(r"^[^~]{1,6}~[0-9]+(\.[^.]{0,3})?$")

REASONS = {
    "context": "the project's context ({name}) is kept by IT; propose a change in the pull request summary instead",
    "config": "{name} configures Claude, the repository or its automation, and only IT changes it",
    "executable": "{name} would run on the user's computer with a double click; nothing that runs there is "
                  "written, the work is tried inside the sandbox",
    "git": "git from the sandbox shell leaves files in a workspace's .git that the sandbox cannot remove, and then "
           "saving stops. Use workspace_status to see what changed and the version tools to save. git log, git show "
           "and git diff --cached only read, and any git command works on a copy outside the workspace "
           "(git -C <copy>)",
    "repository": "a workspace's .git belongs to the connector: nothing in it is written or removed from the sandbox, "
                  "not even a leftover lock. If a save stops, show its message; the connector or IT resolves it",
}


def _parts(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", path or "") if p]


def kind(path: str, in_workspace: bool = True) -> str | None:
    """"context", "config" or "executable" for a path Claude may not write; None otherwise. Outside a workspace
    only executables count."""
    parts = [p.lower().rstrip(". ") for p in _parts(path)]  # Windows ignores trailing dots and spaces
    if not parts:
        return None
    name = parts[-1].split(":")[0]  # an alternate data stream (run.bat:x) is still run.bat
    if any(name.endswith(ext) for ext in HOST_EXECUTABLES):
        return "executable"
    if not in_workspace:
        return None
    if name in CONTEXT_FILES:
        return "context"
    # the folder itself counts too: on Linux a link named .claude is a single entry, not a folder
    if name in CONFIG_FILES or any(p in CONFIG_FOLDERS for p in parts[:-1] + [name]):
        return "config"
    if any(_SHORT_NAME.match(p) for p in parts):
        return "config"
    return None


def reason(path: str, in_workspace: bool = True) -> str | None:
    """Why a path may not be written, or None."""
    found = kind(path, in_workspace)
    return REASONS[found].format(name=_parts(path)[-1]) if found else None


def shell_reason(command: str, in_workspace: bool = True, folders: list[str] | None = None) -> str | None:
    """Best effort for the sandbox shell: a command that writes an executable, or a protected file in a workspace.
    Removing one is allowed, so Claude can clean up what version_save refused. With the workspaces' `folders`, a
    target elsewhere does not count, and .git is left to `_repository_reason`, which follows the command's folder."""
    match = _EXECUTABLE_WRITE.search(command or "")
    if match:
        return REASONS["executable"].format(name=match.group(1))
    for match in _PROTECTED_WRITE.finditer(command or "") if in_workspace else ():
        target = match.group(1)
        if folders and (_is_repository(target) or (_ABSOLUTE.match(target) and not _at_workspace(target, folders))):
            continue
        return REASONS["context" if target.lower().endswith(".md") else "config"].format(name=target)
    return None


# --- the sandbox shell and a workspace's repository ----------------------------------------------------------------

# Measured with git 2.55 on a repository whose files all look changed, as they do when the index was written on
# Windows and is read in the sandbox: only these leave .git as it was. `git status`, `git diff`, `git diff HEAD` and
# `git diff HEAD a.txt` rewrite the index, `git describe --dirty` too, and `--no-optional-locks` stops that for status
# but not for diff. A diff of two commits never reads the working tree.
_GIT_READS = {"log", "show", "blame", "ls-files", "ls-tree", "cat-file", "rev-parse", "rev-list", "shortlog", "grep",
              "merge-base", "show-ref", "for-each-ref", "name-rev", "version", "help"}
_GIT_PROGRAM = re.compile(r"(?:.*[\\/])?git(?:\.exe)?\Z", re.IGNORECASE)
_GIT_HARMLESS = {"--no-pager", "-P", "-p", "--paginate", "--no-optional-locks", "--no-replace-objects",
                 "--literal-pathspecs"}
_GIT_OTHER_OUTPUT = re.compile(r"--output(?:=|\Z)|--ext-diff\Z")
_GIT_RANGE = re.compile(r"\.\.\.?(?:[^./]|\Z)")  # main..HEAD, not ../file
# A word that cannot be a file. Two words with a file last compare the working tree: `git diff HEAD a.txt` writes.
_GIT_COMMIT = re.compile(r"(?:(?:FETCH_|ORIG_)?HEAD|[0-9a-f]{7,40}|[\w./-]+(?=[~^]))(?:[~^]\d*)*\Z")
_ABSOLUTE = re.compile(r"[\\/]|[A-Za-z]:")
_SCRIPTED_REMOVAL = re.compile(r"(?:\bos\.(?:remove|unlink|rmdir)|\bshutil\.rmtree|\.unlink\(|\.rmdir\(|\bunlinkSync\b"
                               r"|\brmSync\b).*?([\w./\\~-]*\.git)\b", re.IGNORECASE | re.DOTALL)
_FIND_REMOVERS = {"rm", "unlink", "rmdir", "mv", "shred"}
_POWERSHELL_WRITERS = {"set-content", "add-content", "clear-content", "out-file", "new-item", "remove-item",
                       "move-item", "copy-item"}
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
_HEREDOC = re.compile(r"""\s*(?:\\?([\w.-]+)|'([^'\n]*)'|"([^"\n]*)")""")
_STREAM = re.compile(r"\s*(?:\d+|-)(?:[\s;&|)]|\Z)")  # 2>&1 points at a stream, not a file
_GIT_LISTS = {"--show-current", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--list", "-l"}
_GIT_CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--list", "-l", "get", "list"}
_OPERATORS = ("&&", "||", ";;", "|&", ";", "&", "|", "(", ")")
_SEPARATORS = {";", ";;", "&", "\n"}
_KEYWORDS = {"if", "then", "elif", "else", "while", "until", "do", "!", "{", "}", "fi", "done", "esac"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
# What runs another command, with the options that take a value and the words between them and the command.
_WRAPPERS = {"command": ((), 0), "builtin": ((), 0), "noglob": ((), 0), "nohup": ((), 0), "setsid": ((), 0),
             "exec": (("-a",), 0), "coproc": ((), 0), "time": (("-f", "-o"), 0), "stdbuf": (("-i", "-o", "-e"), 0),
             "env": (("-u", "--unset", "-C", "--chdir", "-S"), 0), "nice": (("-n", "--adjustment"), 0),
             "sudo": (("-u", "-g", "-h", "-p", "-C", "-D", "-R", "-U", "-T", "-r", "-t"), 0),
             "ionice": (("-c", "-n", "-p", "-P", "-u", "--class", "--classdata"), 0),
             "timeout": (("-s", "-k", "--signal", "--kill-after"), 1), "flock": (("-w", "-E", "--timeout"), 1),
             "xargs": (("-I", "-E", "-d", "-L", "-n", "-P", "-s", "-a"), 0)}


class _Step(NamedTuple):
    spot: str | None  # the folder it runs in, as far as the text shows
    words: list[str]  # past keywords, assignments and wrappers
    writes: list[str]  # the targets of its redirections
    variables: dict[str, str]


def _closing(text: str, start: int) -> int:
    """Where the substitution that starts here ends."""
    if text[start] == "`":
        end = text.find("`", start + 1)
        return len(text) if end < 0 else end
    depth, index = 0, start
    while index < len(text):
        depth += (text[index] == "(") - (text[index] == ")")
        if not depth:
            return index
        index += 1
    return len(text)


def _tokens(text: str) -> list[tuple[str, str]]:
    """A command as a shell reads it: words without their quotes, operators, redirections, and apart, the text of each
    substitution and heredoc. A quoted word is data, so a mention is not a command; what runs is found again in
    `_walk`: the argument of `sh -c`, `eval`, a heredoc fed to a shell."""
    tokens, word, index, heredocs = [], None, 0, []

    def flush() -> None:
        nonlocal word
        if word is not None:
            tokens.append(("word", word))
        word = None

    def substitution() -> None:
        nonlocal word, index
        opened = 1 if text[index] == "`" else 2
        end = _closing(text, index + opened - 1)
        tokens.append(("inner", text[index + opened:end]))
        word = (word or "") + text[index:end + 1]
        index = end + 1

    while index < len(text):
        char = text[index]
        if char == "\\":
            if text[index + 1:index + 2] != "\n":
                word = (word or "") + text[index + 1:index + 2]
            index += 2
        elif char == "'":
            end = text.find("'", index + 1)
            end = len(text) if end < 0 else end
            word = (word or "") + text[index + 1:end]
            index = end + 1
        elif char == '"':
            word, index = word or "", index + 1
            while index < len(text) and text[index] != '"':
                if text[index] == "\\":  # as a shell does: `C:\\Users` keeps its backslash inside double quotes
                    following = text[index + 1:index + 2]
                    word += "" if following == "\n" else following if following in '$`"\\' else "\\" + following
                    index += 2
                elif text.startswith("$(", index) or text[index] == "`":
                    substitution()
                else:
                    word, index = word + text[index], index + 1
            index += 1
        elif text.startswith("$(", index) or char == "`":
            substitution()
        elif text.startswith(("<(", ">("), index):
            flush()
            end = _closing(text, index + 1)
            tokens.append(("inner", text[index + 2:end]))
            index = end + 1
        elif char == "#" and word is None:
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
        elif char == "\n":
            flush()
            tokens.append(("op", "\n"))
            index += 1
            for delimiter, tabs in heredocs:
                lines = text[index:].split("\n")
                body = next((n for n, line in enumerate(lines) if (line.lstrip("\t") if tabs else line) == delimiter),
                            len(lines))
                tokens.append(("body", "\n".join(lines[:body])))
                index += len("\n".join(lines[:body + 1])) + 1
            heredocs = []
        elif char.isspace():
            flush()
            index += 1
        elif text.startswith("<<", index) and not text.startswith("<<<", index):
            flush()
            tabs = text.startswith("<<-", index)
            index += 3 if tabs else 2
            found = _HEREDOC.match(text, index)
            if found:
                heredocs.append((next(group for group in found.groups() if group is not None), tabs))
                index = found.end()
        elif text.startswith("<<<", index):
            flush()
            tokens.append(("redirect", "<<<"))
            index += 3
        elif char in "<>" or text.startswith("&>", index):
            if word is not None and word.isdigit():
                word = None
            flush()
            index += 1 + (text.startswith("&>", index) or text[index + 1:index + 2] in (">", "|"))
            if text[index:index + 1] == "&":
                index += 1
                tokens.append(("redirect", ">" if char != "<" and not _STREAM.match(text, index) else "<"))
            else:
                tokens.append(("redirect", ">" if char != "<" else "<"))
        else:
            operator = next((op for op in _OPERATORS if text.startswith(op, index)), None)
            if operator:
                flush()
                tokens.append(("op", operator))
                index += len(operator)
            else:
                word, index = (word or "") + char, index + 1
    flush()
    return tokens


def _unwrap(words: list[str]) -> tuple[list[str], dict[str, str], str | None]:
    """A simple command past keywords, assignments and wrappers: its words, the variables it sets for itself, and a
    folder a wrapper moves it to."""
    variables, folder = {}, None
    while words:
        name = words[0].rsplit("/", 1)[-1]
        if words[0] in _KEYWORDS:
            words = words[1:]
        elif _ASSIGNMENT.match(words[0]):
            key, _, value = words[0].partition("=")
            variables[key] = value
            words = words[1:]
        elif name in _WRAPPERS:
            if name == "command" and words[1:2] and words[1] in ("-v", "-V"):
                return [], variables, folder  # only asks where a program is
            takes, between = _WRAPPERS[name]
            index = 1
            while index < len(words) and words[index].startswith("-") and words[index] != "--":
                if name == "env" and words[index] in ("-C", "--chdir"):
                    folder = words[index + 1] if index + 1 < len(words) else None
                index += 2 if words[index] in takes else 1
            index += words[index:index + 1] == ["--"]
            words = words[index + between:]
        else:
            break
    return words, variables, folder


def _join(base: str | None, path: str) -> str | None:
    """A folder as far as the text shows it: absolute, relative to a place not known, or None when a variable or the
    home folder makes it impossible to tell."""
    if not path or path[0] == "~" or "$" in path or "`" in path:
        return None
    return path if _ABSOLUTE.match(path) or base is None else f"{base}/{path}"


def _walk(text: str, spot: str | None, variables: dict[str, str], found: list[_Step], depth: int = 0) -> None:
    """Every simple command in `text`, in order, with the folder each runs in. A `cd` holds only as far as it surely
    ran: to the end of its bracket, not past a pipe or `&`, whose command runs apart, and past `||` or a block only until
    what follows no longer depends on it."""
    if depth > 8:
        return
    words, writes, target, brackets, pushed, fed = [], [], None, [], [], []
    blocks, either, unsure, piped, entered = 0, False, False, False, spot

    def run(raw: list[str]) -> None:
        nonlocal spot, unsure, blocks
        plain, own, folder = _unwrap(raw)
        if plain and plain[0] in ("cd", "pushd"):
            if plain[0] == "pushd":
                pushed.append(spot)
            spot = _join(spot, next((word for word in plain[1:] if not word.startswith("-")), ""))
            unsure = unsure or either or blocks > 0
            return
        if plain and plain[0] == "popd":
            spot = pushed.pop() if pushed else None
            return
        if plain and plain[0] == "export":
            variables.update(dict(word.split("=", 1) for word in plain[1:] if _ASSIGNMENT.match(word)))
            return
        if not plain and own:
            variables.update(own)
        where = _join(spot, folder) if folder else spot
        name = plain[0].rsplit("/", 1)[-1] if plain else ""
        found.append(_Step(where, plain, writes[:], {**variables, **own}))
        writes.clear()
        if name == "eval":
            _walk(" ".join(plain[1:]), where, dict(variables), found, depth + 1)
        elif name in _SHELLS or name == "flock" or (plain and plain[0] == "-c"):
            for index, word in enumerate(plain):
                if re.fullmatch(r"-\w*c\w*", word) and index + 1 < len(plain):
                    _walk(plain[index + 1], where, dict(variables), found, depth + 1)
            for text_fed in fed if name in _SHELLS else ():
                _walk(text_fed, where, dict(variables), found, depth + 1)
        elif name == "find":
            for index, word in enumerate(plain):
                if word in ("-exec", "-execdir", "-ok", "-okdir"):
                    end = next((n for n in range(index + 1, len(plain)) if plain[n] in (";", "+")), len(plain))
                    run(plain[index + 1:end])
        fed.clear()

    def finish() -> None:
        nonlocal blocks, words, unsure
        raw, words = words, []
        if raw[:1] and raw[0] in ("if", "while", "until", "for", "case"):
            blocks += 1
        elif raw[:1] and raw[0] in ("fi", "done", "esac"):
            blocks = max(0, blocks - 1)
        run([] if raw[:1] and raw[0] in ("for", "case") else raw)

    for kind, value in _tokens(text):
        if kind == "inner":
            _walk(value, spot, dict(variables), found, depth + 1)
        elif kind == "body":
            if found and found[-1].words[:1] and found[-1].words[0].rsplit("/", 1)[-1] in _SHELLS:
                _walk(value, found[-1].spot, dict(variables), found, depth + 1)
        elif kind == "redirect":
            target = value
        elif kind == "word":
            if target:
                if target == ">":
                    writes.append(value)
                elif target == "<<<":
                    fed.append(value)
                target = None
            else:
                words.append(value)
        else:
            finish()
            if value in ("|", "|&", "&") or piped:
                spot = entered
            if value == "(":
                brackets.append(spot)
            elif value == ")" and brackets:
                spot = brackets.pop()
            either, piped = value == "||", value in ("|", "|&")
            if piped and found and found[-1].words:
                fed.append(" ".join(found[-1].words[1:]))
            if value in _SEPARATORS and unsure and not blocks:
                spot, unsure = None, False
            entered = spot
    finish()


def _steps(command: str, here: str | None) -> list[_Step]:
    found: list[_Step] = []
    _walk(command, here, {}, found)
    return found


def _at_workspace(place: str | None, folders: list[str], unknown: bool = False) -> bool:
    """Whether a folder is a workspace or inside one, as the computer or the sandbox sees it. A copy that has the same
    name is not one, elsewhere or in the sandbox's own output folders; a place the text does not show is `unknown`."""
    if place is None or not _ABSOLUTE.match(place):
        return unknown
    names = [part.lower() for part in rules.parts(place)]
    workspaces = {rules.parts(folder)[-1].lower() for folder in folders if rules.parts(folder)}
    mounted = names[names.index("mnt") + 1:] if "mnt" in names else []
    if mounted[:1] in (["outputs"], ["uploads"]):
        mounted = []
    return rules.relative(place, folders) is not None or bool(workspaces.intersection(mounted))


def _is_repository(path: str | None) -> bool:
    return bool(path) and ".git" in [part.lower() for part in rules.parts(path)]


def _git_call(arguments: list[str]) -> tuple[list[tuple[str, str]], list[str], bool]:
    """A git command's folders (-C, --git-dir, --work-tree), its subcommand with arguments, and whether every option
    before the subcommand is known not to change what it does."""
    folders, index, known = [], 0, True
    while index < len(arguments) and arguments[index].startswith("-"):
        word = arguments[index]
        name, _, value = word.partition("=")
        if word in ("--version", "--help", "--exec-path"):
            return folders, ["version"], known
        if word.startswith("-C") or name in ("--git-dir", "--work-tree"):
            value = word[2:] if word.startswith("-C") else value
            if not value:
                index += 1
                value = arguments[index] if index < len(arguments) else ""
            folders.append(("-C" if word.startswith("-C") else name, value))
        elif word not in _GIT_HARMLESS:
            known = False
        index += 1
    return folders, arguments[index:], known


def _git_diff_only_reads(words: list[str]) -> bool:
    if any(word in ("--cached", "--staged", "--no-index") for word in words):
        return True
    named = [word for word in words if not word.startswith("-")]
    if any(word not in ("..", "...") and _GIT_RANGE.search(word) for word in named):
        return True
    return len(named) == 2 and bool(_GIT_COMMIT.fullmatch(named[1]))


def _git_only_reads(subcommand: list[str], known: bool) -> bool:
    if not known:
        return False
    if not subcommand:
        return True
    name, rest = subcommand[0], subcommand[1:]
    options = rest[:rest.index("--")] if "--" in rest else rest  # what follows -- is a path, whatever it looks like
    if any(_GIT_OTHER_OUTPUT.match(word) for word in options):
        return False
    if name == "grep" and any(re.match(r"-[A-Za-z]*O", word) or (
            len(word) > 3 and "--open-files-in-pager".startswith(word.split("=")[0])) for word in options):
        return False
    if name == "diff":
        return _git_diff_only_reads(options)
    if name == "reflog":
        return not options or options[0] == "show" or options[0].startswith("-")
    if name == "branch":
        return all(word in _GIT_LISTS for word in options)
    if name == "tag":
        return not options or options[0] in ("-l", "--list")
    if name == "remote":
        return options in ([], ["-v"], ["--verbose"])
    if name == "config":
        return options[:1] != [] and options[0] in _GIT_CONFIG_READS
    return name in _GIT_READS


def _shown_folder(tool: str, cwd: str, folders: list[str]) -> str | None:
    """The folder a command starts in, when the hook can know it. The computer's shell reports it; the sandbox shell
    keeps its own, which reaches the hook only when it is a workspace's (H19)."""
    if not _ABSOLUTE.match(cwd):
        return None
    return cwd if tool == "Bash" or _at_workspace(cwd, folders) else None


def _names_a_copy(value: str, folders: list[str]) -> bool:
    """Whether a relative folder can be taken for a copy: it does not climb, stay here or name a workspace."""
    parts = [part.lower() for part in re.split(r"[\\/]+", value) if part]
    names = {rules.parts(folder)[-1].lower() for folder in folders if rules.parts(folder)}
    return _join(None, value) == value and bool(parts) and parts != ["."] and ".." not in parts and not names & set(parts)


def _git_reason(command: str, tool: str, cwd: str, folders: list[str]) -> str | None:
    """A git command that can write, run in a workspace. In the sandbox shell, where the hook cannot see the folder,
    only a command that shows it runs elsewhere stays out; a relative -C is taken as showing that, unless the command
    or the folder the hook receives puts it in a workspace."""
    if not folders:
        return None
    unknown = tool != "Bash" or _at_workspace(cwd, folders)
    for step in _steps(command, _shown_folder(tool, cwd, folders)):
        if not step.words or not _GIT_PROGRAM.fullmatch(step.words[0]):
            continue
        named, subcommand, known = _git_call(step.words[1:])
        positional = [word for word in subcommand[1:] if not word.startswith("-")]
        if subcommand[:1] == ["clone"] and len(positional) > 1 and _ABSOLUTE.match(positional[-1]) \
                and not _at_workspace(positional[-1], folders):
            continue  # it reads the workspace and writes the copy
        base, relative_copy = step.spot, False
        for option, value in named:
            if option == "-C":
                relative_copy = relative_copy or (base is None and _names_a_copy(value, folders))
                base = _join(base, value)
        repositories = [value for option, value in named if option == "--git-dir"]
        trees = [value for option, value in named if option == "--work-tree"]
        repositories += [step.variables["GIT_DIR"]] if "GIT_DIR" in step.variables else []
        trees += [step.variables["GIT_WORK_TREE"]] if "GIT_WORK_TREE" in step.variables else []
        # --work-tree moves the files, not the repository: without --git-dir that is still the one found from here
        places = [_join(base, value) for value in repositories] or ([] if relative_copy else [base])
        places += [_join(base, value) for value in trees]
        if any(_at_workspace(place, folders, unknown) for place in places) and not _git_only_reads(subcommand, known):
            return REASONS["git"]
    return None


def _targets(words: list[str]) -> list[str]:
    """What a simple command writes, moves or removes, beyond its redirections."""
    if not words:
        return []
    verb, arguments = words[0].rsplit("/", 1)[-1], [word for word in words[1:] if not word.startswith("-")]
    if verb == "sed" and not any(word.startswith("-i") or word == "--in-place" for word in words[1:]):
        return []
    if verb == "find" and len(words) > 1 and ("-delete" in words or _FIND_REMOVERS.intersection(words)):
        return [words[1]]
    if verb in rules._ALL_ARGUMENTS or verb.lower() in _POWERSHELL_WRITERS:
        return arguments
    return arguments[-1:] if verb in rules._LAST_ARGUMENT else []


def _repository_reason(command: str, tool: str, cwd: str, folders: list[str]) -> str | None:
    """A shell command that writes or removes something inside a workspace's .git, wherever it stands. A place the
    text cannot show counts as a workspace's when it names .git: `$WS/.git/config`, `~/x/.git/config`."""
    if not folders:
        return None
    unknown = tool != "Bash" or _at_workspace(cwd, folders)

    names = {rules.parts(folder)[-1].lower() for folder in folders if rules.parts(folder)}

    def inside(target: str, spot: str | None) -> bool:
        place = _join(spot, target)
        shown = place is not None and bool(_ABSOLUTE.match(place))
        return _is_repository(place or target) and (
            _at_workspace(place, folders, unknown) or (not shown and _inside(target, names)))

    here = _shown_folder(tool, cwd, folders)
    for step in _steps(command, here):
        if any(inside(target, step.spot) for target in [*step.writes, *_targets(step.words)]):
            return REASONS["repository"]
    return REASONS["repository"] if any(inside(found, here) for found in _SCRIPTED_REMOVAL.findall(command)) else None


def _workspace_folders() -> list[str]:
    """The folders of the workspaces the connector registered."""
    try:
        return list(json.loads((data_dir() / "workspaces.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _workspace_names() -> set[str]:
    """Their folder names (the sandbox sees the same names)."""
    return {_parts(folder)[-1].lower() for folder in _workspace_folders() if _parts(folder)}


def _inside(text: str, names: set[str]) -> bool:
    return any(part.lower() in names for part in _parts(text.replace(" ", "/")))


# The connector, the workspace folders and the git servers are on the user's computer and its network, which a
# Cowork task in the cloud cannot reach: such a task is refused outright, prompt by prompt and tool by tool. Claude
# Code sets these variables in cloud sessions for hooks to read; the PreToolUse hook's onFailure also blocks when
# the hook cannot start there.
CLOUD = ("this Cowork task runs in the cloud, and eunomai-business only works with tasks on the user's computer. "
         "Ask the user to start a new task on this computer; if Cowork offers no way to, IT has to turn off running "
         "tasks in the cloud for the organization")


def in_the_cloud() -> bool:
    return (os.environ.get("CLAUDE_CODE_REMOTE", "").strip().lower() == "true"
            or bool(os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID", "").strip()))


def decide(payload: dict, policy: list[dict] | None = None) -> str | None:
    """Why a tool call may not run, or None: the file guard first, then the organization's deny rules (Bash rules
    anywhere, Edit rules in workspaces)."""
    if in_the_cloud():
        return CLOUD
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    found = None
    if tool in _WRITE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        found = reason(path, _inside(path, _workspace_names()))
    elif tool in _SHELL_TOOLS:
        command, folder = str(tool_input.get("command") or ""), str(payload.get("cwd") or "")
        workspaces = _workspace_folders()
        found = (_git_reason(command, tool, folder, workspaces)
                 or _repository_reason(command, tool, folder, workspaces)
                 or shell_reason(command, _inside(command + " " + folder, _workspace_names()), workspaces))
    if found or not policy or tool not in _WRITE_TOOLS | _SHELL_TOOLS:
        return found
    cwd = str(payload.get("cwd") or "")
    return (rules.deny_reason([r for r in policy if rules.parse(r["rule"])[0] == "Bash"], tool, tool_input, cwd, None)
            or rules.deny_reason([r for r in policy if rules.parse(r["rule"])[0] == "Edit"], tool, tool_input, cwd,
                                 _workspace_folders()))


def load_policy(path: str | None) -> list[dict]:
    """The organization's deny rules the build packaged (policy.json). Unreadable rules are an error, which the
    tool-call hook's onFailure turns into a block; their examples were checked by the build."""
    if not path:
        return []
    with open(path, encoding="utf-8") as handle:
        policy = json.load(handle).get("deny", [])
    errors = rules.problems(policy, examples=False)
    if errors:
        raise ValueError("eunomai-business: the packaged deny rules are invalid: " + "; ".join(errors))
    return policy


def _refuse_the_cloud(event: str | None) -> None:
    if event == "UserPromptSubmit":
        print(json.dumps({"decision": "block", "reason": f"eunomai-business: {CLOUD}."}))
    elif event == "SessionStart":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": f"eunomai-business: {CLOUD}."}}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": f"eunomai-business: {CLOUD}."}}))
    sys.exit(0)


def main(argv: list[str] | None = None) -> None:
    """SessionStart, UserPromptSubmit and PreToolUse hook. In the cloud everything is refused. Otherwise only tool
    calls are checked, and input it cannot read is let through: version_save still holds for workspaces."""
    parser = argparse.ArgumentParser(description="eunomai-business's guard hook.")
    parser.add_argument("--policy", help="the organization's deny rules (policy.json in the plugin)")
    arguments = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = None
    event = payload.get("hook_event_name") if isinstance(payload, dict) else None
    if in_the_cloud():
        _refuse_the_cloud(event)
    if not isinstance(payload, dict) or event not in (None, "PreToolUse"):
        sys.exit(0)
    found = decide(payload, load_policy(arguments.policy))
    if found:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": f"eunomai-business: {found}."}}))
    sys.exit(0)
