"""Deny rules that IT writes in a build's configuration, in the syntax of Claude Code's permission rules, so they
read the same as Anthropic's and could move to `permissions.deny` unchanged (docs/hooks.md).

Two forms: `Bash(<command>)` and `Edit(<path>)`, or a bare `Bash` for every command. `Bash` covers Cowork's shell
(mcp__workspace__bash) too; `Edit` covers every tool that writes a file. A `*` in a command stands for any text, and
a trailing ` *` also matches the bare command; a command is split at shell operators and each part is checked, past
leading variable assignments and the wrappers Claude Code strips. A path is relative to the workspace, with
gitignore patterns: * inside one folder, ** at any depth, a bare name or `folder/**` at any depth, a leading / at the
workspace's root.

Standard library only: the project-plugin template carries an identical copy (a test keeps them equal).
"""

import re

TOOLS = {"Bash", "Edit"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "mcp__workspace__bash"}

_RULE = re.compile(r"\A(Bash|Edit)(?:\((.+)\))?\Z", re.DOTALL)
_SEPARATORS = ("&&", "||", "|&", ";", "|", "&", "\n")
_ASSIGNMENT = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+")
# The wrappers Claude Code strips before matching, with the options and values they take.
_WRAPPERS = re.compile(r"\A(?:timeout(?:\s+-\S+)*\s+\S+|time|nice(?:\s+-n\s+\S+|\s+-\S+)*|nohup|stdbuf(?:\s+-\S+)*"
                       r"|command|builtin|noglob|xargs)\s+")
_SUBSTITUTIONS = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def parse(rule: str) -> tuple[str, str | None]:
    """("Bash" or "Edit", the pattern or None for the whole tool). ValueError for anything else."""
    found = _RULE.match((rule or "").strip())
    if not found:
        raise ValueError(f"{rule!r} is not Bash(<command>), Edit(<path>) or Bash")
    tool, spec = found.group(1), found.group(2)
    if tool == "Edit" and not spec:
        raise ValueError(f"{rule!r}: Edit needs a path; deny every write with the plugin's own guard instead")
    if tool == "Edit" and spec.startswith(("//", "~")):
        raise ValueError(f"{rule!r}: paths are relative to the workspace (no // or ~)")
    return tool, spec


def _split(command: str) -> list[str]:
    """A command's parts at shell operators outside quotes, with what $(...) and `...` run."""
    parts, current, quote, i = [], "", None, 0
    while i < len(command):
        char = command[i]
        if quote:
            current += char
            if char == quote:
                quote = None
            i += 1
            continue
        if char in "'\"":
            quote, current, i = char, current + char, i + 1
            continue
        separator = next((s for s in _SEPARATORS if command.startswith(s, i)), None)
        if separator:
            parts.append(current)
            current, i = "", i + len(separator)
            continue
        current, i = current + char, i + 1
    parts.append(current)
    for match in _SUBSTITUTIONS.finditer(command):
        parts.extend(_split(match.group(1) if match.group(1) is not None else match.group(2)))
    return [part for part in parts if part.strip()]


def _bare(part: str) -> str:
    """A part without grouping, leading assignments and wrappers: the command Claude Code matches."""
    text = part.strip().lstrip("({").rstrip(")}").strip()
    while True:
        stripped = _ASSIGNMENT.sub("", text, count=1)
        stripped = _WRAPPERS.sub("", stripped, count=1)
        if stripped == text:
            return text
        text = stripped.strip()


def _command_pattern(spec: str) -> re.Pattern:
    if spec.endswith(":*"):  # the legacy form of a trailing wildcard
        spec = spec[:-2] + " *"
    if spec.endswith(" *") and spec.count("*") == 1:  # also the bare command
        return re.compile(re.escape(spec[:-2]) + r"(?: .*)?\Z", re.DOTALL)
    return re.compile(".*".join(re.escape(piece) for piece in spec.split("*")) + r"\Z", re.DOTALL)


def command_matches(spec: str | None, command: str) -> bool:
    if spec is None or spec == "*":
        return True
    pattern = _command_pattern(spec)
    return any(pattern.match(_bare(part)) for part in _split(command or ""))


def _path_pattern(spec: str) -> re.Pattern:
    glob = spec[2:] if spec.startswith("./") else spec
    if glob.startswith("/"):
        glob = glob.lstrip("/")
    elif "/" not in glob.rstrip("/") or re.fullmatch(r"[^/]+/\*\*", glob):
        glob = "**/" + glob  # a bare name, or one folder and everything in it, at any depth
    out, i = "", 0
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


# Commands that write, move or remove files: the targets of these are checked against Edit rules, best effort.
_WRITES = re.compile(r"(?:>|\btee\b|\bcp\b|\bmv\b|\bln\b|\btouch\b|\bmkdir\b|sed\s+-i|Set-Content|Add-Content"
                     r"|Out-File|New-Item|\brm\b|\brmdir\b|\btruncate\b|\bdd\b|\bunzip\b|\btar\b|Remove-Item)",
                     re.IGNORECASE)
_TOKENS = re.compile(r"""[^\s'"<>|;&]+""")


def shell_targets(command: str, cwd: str, folders: list[str]) -> list[str]:
    """Workspace-relative paths a command that writes may touch: absolute ones in a workspace, and relative ones when
    it runs in a workspace."""
    if not _WRITES.search(command or ""):
        return []
    here = relative(cwd or "", folders)
    found = []
    for token in _TOKENS.findall(command):
        inside = relative(token, folders)
        if inside is None and here is not None and not re.match(r"^([\\/~]|[A-Za-z]:)", token):
            inside = "/".join(parts("/".join(filter(None, [here, token]))))
        if inside:
            found.append(inside)
    return found


def deny_reason(rules: list[dict], tool: str, tool_input: dict, cwd: str, folders: list[str] | None) -> str | None:
    """The reason of the first rule that denies this call, or None. With folders None, Bash rules apply anywhere and
    Edit rules nowhere; otherwise only inside those workspace folders."""
    if tool in SHELL_TOOLS:
        command = str(tool_input.get("command") or "")
        in_scope = folders is None or relative(cwd or "", folders) is not None or \
            any(relative(token, folders) is not None for token in _TOKENS.findall(command))
        targets = shell_targets(command, cwd, folders) if folders else []
        for rule in rules:
            name, spec = parse(rule["rule"])
            if name == "Bash" and in_scope and command_matches(spec, command):
                return rule["reason"]
            if name == "Edit" and any(path_matches(spec, target) for target in targets):
                return f"{rule['reason']} ({next(t for t in targets if path_matches(spec, t))})"
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


def problems(rules: object) -> list[str]:
    """What is wrong with a configuration's deny rules, examples included: the build refuses to package them."""
    if not isinstance(rules, list):
        return ["deny must be a list of {rule, reason, examples}"]
    found = []
    for index, item in enumerate(rules):
        where = f"deny[{index}]"
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
        examples = item.get("examples", {})
        if not isinstance(examples, dict) or set(examples) - {"denied", "allowed"} or \
                not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in examples.values()):
            found.append(f"{where}.examples must be {{\"denied\": [...], \"allowed\": [...]}} with strings")
            continue
        check = (lambda text: command_matches(spec, text)) if tool == "Bash" else (lambda text: path_matches(spec,
                                                                                                             text))
        for text in examples.get("denied", []):
            if not check(text):
                found.append(f"{where}: {item['rule']} does not deny its example {text!r}")
        for text in examples.get("allowed", []):
            if check(text):
                found.append(f"{where}: {item['rule']} denies {text!r}, which its examples allow")
    return found
