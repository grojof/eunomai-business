"""Deny rules that IT writes in a build's configuration, in the syntax of Claude Code's permission rules, so they read
like Anthropic's (docs/hooks.md lists where they differ).

Two forms: `Bash(<command>)`, or a bare `Bash` for every command, and `Edit(<path>)`. `Bash` covers Cowork's shell
(mcp__workspace__bash) too; `Edit` covers every tool that writes a file and, best effort, the files a shell command
writes, moves or removes. A `*` in a command stands for any text, and a trailing ` *` also matches the bare command.
A path is relative to the workspace, with gitignore patterns: * inside one folder, ** at any depth, a bare name or
`folder/**` at any depth, a leading / at the workspace's root.

A deny rule errs on the side of denying: a command is looked for wherever one can start (after an operator, a
bracket, a quote or a keyword, inside substitutions and loops), without trusting quotes, so a quote cannot hide one.
Text that only mentions a command (a quoted message, a heredoc) can be denied too; Claude then writes it with the
file tools.

Standard library only: the project-plugin template carries an identical copy (a test keeps them equal).
"""

import re
import shlex

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "mcp__workspace__bash"}

_RULE = re.compile(r"\A(Bash|Edit)(?:\((.+)\))?\Z", re.DOTALL)
# Where a command can start, and where it ends.
_START = re.compile(r"\A|[;&|\n({`!'\"]|\$\(|[<>]\(|\b(?:then|do|else|elif|if|while|until)\b")
_END = re.compile(r"[;&|\n)`]")
_ASSIGNMENT = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=\S*\s+")
# The wrappers Claude Code strips before matching, with the options and values they take; xargs only without options.
_WRAPPER = re.compile(r"\A(?:timeout(?:\s+(?:-s|-k|--signal|--kill-after)\s+\S+|\s+-\S+)*\s+\S+|time(?:\s+-\S+)*"
                      r"|nice(?:\s+-n\s*\S+|\s+-\S+)*|nohup|stdbuf(?:\s+-[ioe]\s*\S+|\s+--\S+)*|command|builtin"
                      r"|noglob|xargs(?=\s+[^-\s]))\s+")


def parse(rule: str) -> tuple[str, str | None]:
    """("Bash" or "Edit", the pattern or None for the whole tool). ValueError for anything else."""
    found = _RULE.match(rule if isinstance(rule, str) else "")
    if not found:
        raise ValueError(f"{rule!r} is not Bash(<command>), Edit(<path>) or Bash")
    tool, spec = found.group(1), found.group(2)
    if tool == "Edit":
        if not spec:
            raise ValueError(f"{rule!r}: Edit needs a path")
        if spec != spec.strip() or spec.startswith(("//", "~", "!")) or "\\" in spec \
                or ".." in spec.split("/") or "." in spec.split("/")[1:]:
            raise ValueError(f"{rule!r}: a path relative to the workspace, with /, without spaces around it, ./ "
                             "inside, .., // , ~ or !")
    return tool, spec


# --- commands ------------------------------------------------------------------------------------------------------

def _forms(candidate: str) -> list[str]:
    """A candidate command and each form left after stripping a leading assignment or wrapper."""
    text = re.sub(r"[ \t]+", " ", candidate.strip().strip("'\""))
    forms = [text]
    while True:
        stripped = _WRAPPER.sub("", _ASSIGNMENT.sub("", text, count=1), count=1).strip()
        if stripped == text:
            return forms
        text = stripped
        forms.append(text)


def _candidates(command: str) -> list[str]:
    """Every place a command may start, up to where it ends."""
    found = []
    for start in _START.finditer(command):
        rest = command[start.end():]
        end = _END.search(rest)
        piece = (rest[:end.start()] if end else rest).strip()
        if piece:
            found.append(piece)
    return found


def _command_pattern(spec: str) -> re.Pattern:
    spec = re.sub(r"[ \t]+", " ", spec)
    if spec.endswith(":*"):  # the legacy form of a trailing wildcard
        spec = spec[:-2] + " *"
    if spec.endswith(" *") and spec.count("*") == 1:  # also the bare command
        return re.compile(re.escape(spec[:-2]) + r"(?: .*)?\Z", re.DOTALL)
    return re.compile(".*".join(re.escape(piece) for piece in spec.split("*")) + r"\Z", re.DOTALL)


def command_matches(spec: str | None, command: str) -> bool:
    if spec is None or spec == "*":
        return True
    pattern = _command_pattern(spec)
    return any(pattern.match(form) for candidate in _candidates(command or "") for form in _forms(candidate))


# --- paths ---------------------------------------------------------------------------------------------------------

def _glob(spec: str) -> tuple[str, bool]:
    """The pattern relative to the workspace's root, and whether it is anchored there."""
    glob = spec[2:] if spec.startswith("./") else spec
    if glob.endswith("/"):
        glob += "**"  # a folder: everything in it
    if glob.startswith("/"):
        return glob.lstrip("/"), True
    if "/" not in glob or re.fullmatch(r"[^/]+/\*\*", glob):
        return glob, False  # a bare name, or one folder and everything in it, at any depth
    return glob, True


def _path_pattern(spec: str) -> re.Pattern:
    glob, anchored = _glob(spec)
    out, i = "" if anchored else "(?:.*/)?", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + r"(?:/.*)?\Z", re.IGNORECASE)  # a folder's rule covers what is inside it


def path_matches(spec: str, relative: str) -> bool:
    return bool(_path_pattern(spec).match(relative.replace("\\", "/").strip("/")))


def _holds(spec: str, target: str) -> bool:
    """Whether removing or moving `target` would take what the rule protects with it."""
    glob, anchored = _glob(spec)
    fixed = []
    for part in glob.split("/"):
        if any(c in part for c in "*?["):
            break
        fixed.append(part.lower())
    target_parts = [p.lower() for p in target.replace("\\", "/").strip("/").split("/") if p]
    if not fixed:
        return not target_parts
    if anchored:
        return fixed[:len(target_parts)] == target_parts
    return not target_parts or target_parts[-1] == fixed[0]  # a folder of that name, wherever it is


def parts(path: str) -> list[str]:
    """A path's names, with .. resolved. An alternate data stream (x.csv:s) is still x.csv, and Windows ignores
    trailing dots and spaces."""
    raw = [part for part in re.split(r"[\\/]+", path or "") if part]
    if raw and ":" in raw[-1] and not re.fullmatch(r"[A-Za-z]:", raw[-1]):
        raw[-1] = raw[-1].split(":")[0]
    names = []
    for part in raw:
        if part == "..":
            names = names[:-1]
        elif part.rstrip(". "):
            names.append(part.rstrip(". "))
    return names


def relative(path: str, folders: list[str]) -> str | None:
    """The part of a path inside one of the workspace folders, or None. A workspace is found on the computer, or
    as Claude's sandbox mounts it (.../mnt/<workspace>/ or .../mnt/<root>/<workspace>/)."""
    lowered, original = [part.lower() for part in parts(path)], parts(path)
    for folder_path in folders:
        folder = [part.lower() for part in parts(folder_path)]
        if not folder:
            continue
        if lowered[:len(folder)] == folder:
            return "/".join(original[len(folder):])
        name, parent = folder[-1], folder[-2] if len(folder) > 1 else ""
        for index, part in enumerate(lowered[:-1]):
            if part != "mnt":
                continue
            if lowered[index + 1] == name:
                return "/".join(original[index + 2:])
            if parent and lowered[index + 1] == parent and lowered[index + 2:index + 3] == [name]:
                return "/".join(original[index + 3:])
    return None


_REMOVERS = {"rm", "rmdir", "unlink", "mv"}
_ALL_ARGUMENTS = {"rm", "rmdir", "unlink", "touch", "mkdir", "truncate", "tee", "mv"}
_LAST_ARGUMENT = {"cp", "mv", "ln", "install", "sed"}


def _words(text: str) -> list[str]:
    try:
        return shlex.split(text, comments=False, posix=True)
    except ValueError:
        return text.split()


def shell_writes(command: str) -> list[tuple[str, str]]:
    """(verb, path) for each file a command writes, moves or removes, best effort: the target of > and >>, the
    arguments of rm, rmdir, unlink, touch, mkdir, truncate, tee and mv, and the last one of cp, ln, install and sed."""
    found = [(">", target) for target in re.findall(r">>?\s*([^\s;&|<>()]+)", command or "")]
    for candidate in _candidates(command or ""):
        words = _words(_forms(candidate)[-1])
        if not words:
            continue
        verb, arguments = words[0].rsplit("/", 1)[-1], [w for w in words[1:] if not w.startswith("-")]
        if verb == "sed" and not any(w.startswith("-i") or w == "--in-place" for w in words[1:]):
            continue
        if verb in _ALL_ARGUMENTS:
            found += [(verb, argument) for argument in arguments]
        elif verb in _LAST_ARGUMENT and arguments:
            found.append((verb, arguments[-1]))
    return found


def deny_reason(rules: list[dict], tool: str, tool_input: dict, cwd: str, folders: list[str] | None) -> str | None:
    """The reason of the first rule that denies this call, or None. With folders None, Bash rules apply anywhere and
    Edit rules nowhere; otherwise only inside those workspace folders."""
    if tool in SHELL_TOOLS:
        command = str(tool_input.get("command") or "")
        here = relative(cwd or "", folders) if folders else None
        targets = []
        for verb, target in shell_writes(command) if folders else []:
            inside = relative(target, folders)
            if inside is None and here is not None and not re.match(r"^([\\/~]|[A-Za-z]:)", target):
                inside = "/".join(parts("/".join(filter(None, [here, target]))))
            if inside is not None:
                targets.append((verb, inside))
        in_scope = folders is None or here is not None or bool(targets)
        for rule in rules:
            name, spec = parse(rule["rule"])
            if name == "Bash" and in_scope and command_matches(spec, command):
                return rule["reason"]
            if name == "Edit":
                for verb, inside in targets:
                    if path_matches(spec, inside) or (verb in _REMOVERS and _holds(spec, inside)):
                        return f"{rule['reason']} ({inside or 'the workspace'})"
        return None
    if tool in WRITE_TOOLS and folders:
        inside = relative(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""), folders)
        if inside is None:
            return None
        for rule in rules:
            name, spec = parse(rule["rule"])
            if name == "Edit" and path_matches(spec, inside):
                return f"{rule['reason']} ({inside})"
    return None


def problems(rules: object, examples: bool = True) -> list[str]:
    """What is wrong with a configuration's deny rules: the build refuses to package them. With examples, each
    rule must also deny what it says it denies and let through what it says it allows."""
    if not isinstance(rules, list):
        return ["deny must be a list of {rule, reason, examples}"]
    found = []
    for index, item in enumerate(rules):
        where = f"deny[{index}]"
        if isinstance(item, dict) and "paths" in item:
            found.append(f"{where}: {{paths, reason}} is the old form; write each path as "
                         "{\"rule\": \"Edit(/<path>)\", \"reason\": ...} (a leading / keeps it at the root)")
            continue
        if not isinstance(item, dict) or not {"rule", "reason"} <= set(item) or set(item) - {"rule", "reason",
                                                                                              "examples"}:
            found.append(f"{where} must have rule and reason, and optionally examples")
            continue
        try:
            tool, spec = parse(item["rule"])
        except ValueError as error:
            found.append(f"{where}: {error}")
            continue
        if not isinstance(item["reason"], str) or not item["reason"].strip() or "\n" in item["reason"] \
                or len(item["reason"]) > 300:
            found.append(f"{where}.reason must be one line of at most 300 characters")
        cases = item.get("examples", {})
        if not isinstance(cases, dict) or set(cases) - {"denied", "allowed"} or \
                not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in cases.values()):
            found.append(f"{where}.examples must be {{\"denied\": [...], \"allowed\": [...]}} with strings")
            continue
        if not examples:
            continue
        check = (lambda text: command_matches(spec, text)) if tool == "Bash" else (lambda text: path_matches(spec,
                                                                                                             text))
        for text in cases.get("denied", []):
            if not check(text):
                found.append(f"{where}: {item['rule']} does not deny its example {text!r}")
        for text in cases.get("allowed", []):
            if check(text):
                found.append(f"{where}: {item['rule']} denies {text!r}, which its examples allow")
    return found
