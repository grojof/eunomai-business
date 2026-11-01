"""The organization's choices for the specialist, set by IT when building the plugin (EUNOMAI_SPECIALIST), and what a
project declares for itself on its main branch (.eunomai/project.toml)."""

import json
import os
import re
import tomllib
from urllib.parse import urlsplit

DEFAULTS = {"docs_language": "en", "code_language": "", "free_development": False, "allowed_technologies": [],
            "dependency_exceptions": [], "organization_context": "", "organization_skills": [], "app_preview": False}


def load() -> dict:
    raw = os.environ.get("EUNOMAI_SPECIALIST", "")
    try:
        configured = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"EUNOMAI_SPECIALIST is not valid JSON: {exc}") from exc
    values = {**DEFAULTS, **configured}
    values["code_language"] = values["code_language"] or values["docs_language"]
    return values


def _no_code(reason: str) -> dict:
    return {"code_allowed": False, "technologies": [], "reason": reason}


def _declared(text: str) -> dict | None:
    """The project's own answer, or None when it says nothing about development. A declaration IT cannot have meant
    (unreadable, wrong types) allows nothing."""
    try:
        declared = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return _no_code(f"the project's declaration is not valid TOML ({exc}); IT corrects it")
    if "development" not in declared:
        return None
    section = declared["development"]
    unknown = sorted(set(section) - {"code", "technologies"}) if isinstance(section, dict) else []
    if unknown:  # a misspelt technologies would otherwise mean any technology
        return _no_code(f"the project's declaration has unknown keys in [development] ({', '.join(unknown)}); IT "
                        "corrects it")
    code = section.get("code", False) if isinstance(section, dict) else None
    technologies = section.get("technologies", []) if isinstance(section, dict) else None
    if not isinstance(code, bool) or not isinstance(technologies, list) \
            or not all(isinstance(item, str) and item.strip() for item in technologies):
        return _no_code("the project's declaration is not valid: [development] takes code (true or false) and "
                        "technologies (a list of names); IT corrects it")
    if not code:
        return _no_code("the project declares that no code is written here")
    return {"code_allowed": True, "technologies": technologies, "reason": "the project declares it"}


def development(declaration: dict | None) -> dict:
    """Whether code may be written in a workspace, and with which technologies (empty list: any). The project's
    declaration on its main branch decides; without one, the build's free development does."""
    declared = _declared(declaration.get("text", "")) if declaration is not None else None
    if declared is not None:
        return declared
    values = load()
    if values["free_development"]:
        return {"code_allowed": True, "technologies": values["allowed_technologies"],
                "reason": "free development is enabled"}
    return _no_code("the project declares no development and free development is off")


_BRANCH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _branch_name(name) -> bool:
    """A plain branch name, as the connector names versions: parts of letters, digits, . _ - separated by /, each
    starting with a letter or digit and not ending in . or .lock; never main, master, HEAD or a full ref."""
    if not isinstance(name, str) or not 0 < len(name) <= 100 or ".." in name:
        return False
    if name.casefold() in {"main", "master", "head"} or name.casefold().startswith("refs/"):
        return False
    return all(_BRANCH_PART.match(part) and not part.endswith((".", ".lock")) for part in name.split("/"))


def test(declaration: dict | None) -> dict | None:
    """The project's test environment, if it declares one: the branch its CI applies to that environment, and where
    to see it. None when it declares none; {"invalid": reason} when IT must correct it."""
    if declaration is None:
        return None
    try:
        declared = tomllib.loads(declaration.get("text", ""))
    except tomllib.TOMLDecodeError:
        return {"invalid": "the project's declaration is not valid TOML; IT corrects it"}
    if "test" not in declared:
        return None
    section = declared["test"]
    if not isinstance(section, dict) or set(section) - {"branch", "url"}:
        return {"invalid": "[test] takes branch and url only; IT corrects it"}
    branch, url = section.get("branch"), section.get("url", "")
    if not _branch_name(branch):
        return {"invalid": "[test] needs branch, the name of a branch other than the main one; IT corrects it"}
    if not isinstance(url, str) or (url and (urlsplit(url).scheme != "https" or not urlsplit(url).netloc)):
        return {"invalid": "[test] url must be an https address; IT corrects it"}
    return {"branch": branch, "url": url}


_PROGRAM = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
# A program that would run text as commands, or change what is installed: `uv run` starts it, so a list does not stop it.
_NOT_A_PROGRAM = {"sh", "bash", "zsh", "dash", "ksh", "fish", "cmd", "powershell", "pwsh", "wsl", "env", "sudo", "uv",
                  "uvx", "pip", "pip3"}
_SHELL_TEXT = re.compile(r"[;&|`<>\n\r]|\$\(")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_ADDRESS = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}|\[?::|\blocalhost\b|\*:", re.IGNORECASE)
_HOST_OPTIONS = {"--host", "--bind", "-b", "--listen", "--address", "--interface"}
_LISTENS_ELSEWHERE = {"--uds", "--fd"}
_THIS_COMPUTER = "127.0.0.1"
_VARIABLE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
# What the connector sets or keeps out itself: a project does not replace it.
_RESERVED = re.compile(r"(?:UV_|PYTHON|LD_|DYLD_|VIRTUAL_ENV\Z|PATH\Z|PATHEXT\Z|SYSTEM|WINDIR\Z|COMSPEC\Z|HOME\Z"
                       r"|USERPROFILE\Z|APPDATA\Z|LOCALAPPDATA\Z|TEMP\Z|TMP\Z|TMPDIR\Z)")


def _entry_problem(entry) -> str | None:
    """Why a command the project declares cannot be run as it is, never through a shell."""
    if not isinstance(entry, list) or not entry or not all(isinstance(word, str) and word for word in entry):
        return "a list of words, with the program first"
    if not _PROGRAM.match(entry[0]):
        return f"its program must be a plain name, not {entry[0]!r}"
    if entry[0].lower().removesuffix(".exe") in _NOT_A_PROGRAM or any(_SHELL_TEXT.search(word) for word in entry):
        return "it must not need a shell"
    return None


def _host_problem(run: list[str]) -> str | None:
    """Why the application might listen anywhere but on this computer, as far as its command line shows."""
    named = False
    for index, word in enumerate(run):
        option, _, value = word.partition("=")
        if option in _LISTENS_ELSEWHERE:
            return f"run must listen on {_THIS_COMPUTER} only, not through {option}"
        if option in _HOST_OPTIONS:
            value = value or (run[index + 1] if index + 1 < len(run) else "")
            if value.split(":")[0] != _THIS_COMPUTER:
                return f"run must listen on {_THIS_COMPUTER} only, not {value}"
        found = [text for text in _ADDRESS.findall(value or word) if text != _THIS_COMPUTER]
        if found:
            return f"run must listen on {_THIS_COMPUTER} only, not {found[0]}"
        named = named or _THIS_COMPUTER in word
    return None if named else f"run must say {_THIS_COMPUTER}"


def preview(declaration: dict | None) -> dict | None:
    """How the project is run on the person's computer, if it says: `setup` (commands), `run` (a command) and
    `environment`. None when it says nothing; {"invalid": reason} when IT must correct it. Only what cannot reach a
    shell or listen beyond this computer is valid: this runs outside every sandbox (docs/barriers.md)."""
    if declaration is None:
        return None
    try:
        declared = tomllib.loads(declaration.get("text", ""))
    except tomllib.TOMLDecodeError:
        return {"invalid": "the project's declaration is not valid TOML; IT corrects it"}
    if "preview" not in declared:
        return None
    section = declared["preview"]
    unknown = sorted(set(section) - {"setup", "run", "environment"}) if isinstance(section, dict) else ["(not a table)"]
    if unknown:
        return {"invalid": f"[preview] takes setup, run and environment, not {', '.join(unknown)}; IT corrects it"}
    run, setup, environment = section.get("run"), section.get("setup", []), section.get("environment", {})
    problem = _entry_problem(run)
    if problem:
        return {"invalid": f"[preview] run: {problem}; IT corrects it"}
    placeholders = {found for word in run for found in _PLACEHOLDER.findall(word)}
    if placeholders != {"{port}"}:
        return {"invalid": "[preview] run must use {port}, and nothing else in braces; IT corrects it"}
    problem = _host_problem(run)
    if problem:
        return {"invalid": f"[preview] {problem}; IT corrects it"}
    if not isinstance(setup, list):
        return {"invalid": "[preview] setup must be a list of commands; IT corrects it"}
    for entry in setup:
        problem = _entry_problem(entry)
        if problem:
            return {"invalid": f"[preview] setup: {problem}; IT corrects it"}
        if any(_PLACEHOLDER.search(word) for word in entry):
            return {"invalid": "[preview] setup takes no braces: only run knows the port; IT corrects it"}
    if not isinstance(environment, dict) or not all(isinstance(value, str) for value in environment.values()):
        return {"invalid": "[preview.environment] takes names and text values; IT corrects it"}
    reserved = [name for name in environment if not _VARIABLE.match(name) or _RESERVED.match(name)]
    if reserved:
        return {"invalid": f"[preview.environment] cannot set {', '.join(sorted(reserved))}; IT corrects it"}
    return {"setup": setup, "run": run, "environment": environment}
