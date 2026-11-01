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
_SCRIPTS = (".py", ".pyw", ".pyz")  # `uv run` reads a script's own metadata and lockfile; `python <file>` does not
_MODULE = re.compile(r"[A-Za-z_][\w.]*\Z")
PYTHONS = {"python", "python3"}
_NOT_MODULES = {"pip", "ensurepip", "venv"}
NOT_SCRIPTS = {"pip", "pip3", "uv", "uvx"}  # they change what is installed, whichever package brings them
_SHELL_TEXT = re.compile(r"[;&|`<>\n\r]|\$\(")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_THIS_COMPUTER = "127.0.0.1"
_HOST_OPTIONS = ("--host", "--bind", "--listen", "--address", "--interface")
_SHORT_HOST = re.compile(r"-[bhH]")
_LISTENS_ELSEWHERE = {"--uds", "--fd"}
_ELSEWHERE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}|\[?::|\blocalhost\b|\*:|(?:^|=)0:", re.IGNORECASE)
_HOST_VARIABLE = re.compile(r"_(?:HOST|BIND|LISTEN|ADDR|ADDRESS|INTERFACE)\Z")
_VARIABLE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
# What the connector sets or keeps out itself, and what steers a tool: a project does not replace it.
_RESERVED = re.compile(r"(?:UV_|PYTHON|PIP_|LD_|DYLD_|SSL_|GIT_|NODE_|CONDA_|VIRTUAL_ENV\Z|PATH\Z|PATHEXT\Z|SYSTEM|WINDIR\Z"
                       r"|COMSPEC\Z|HOME\Z|USERPROFILE\Z|APPDATA\Z|LOCALAPPDATA\Z|TEMP\Z|TMP\Z|TMPDIR\Z|.*_PROXY\Z)")


def _python_problem(arguments: list[str]) -> str | None:
    first = arguments[0] if arguments else ""
    if first == "-m":
        module = arguments[1] if len(arguments) > 1 else ""
        if not _MODULE.match(module) or module.split(".")[0].lower() in _NOT_MODULES:
            return "python -m needs a module of the application, not pip, ensurepip or venv"
        return None
    if not first or first.startswith("-") or first.startswith(("/", "\\", "~")) or ":" in first \
            or ".." in re.split(r"[\\/]", first):
        return "python runs a file of the project, or -m <module>, and nothing else"
    return None


def _entry_problem(entry) -> str | None:
    """Why a command the project declares cannot be run as it is. Its shape only: which console scripts exist is known
    once the locked packages are installed, and the connector checks that then."""
    if not isinstance(entry, list) or not entry or not all(isinstance(word, str) and word for word in entry):
        return "a list of words, with the program first"
    if not _PROGRAM.match(entry[0]) or entry[0].lower().endswith(_SCRIPTS):
        return f"its program must be python or a package's console script, not {entry[0]!r}"
    if any(_SHELL_TEXT.search(word) for word in entry):
        return "it must not need a shell"
    return _python_problem(entry[1:]) if entry[0].lower() in PYTHONS else None


def _names_elsewhere(word: str) -> bool:
    return bool(_ELSEWHERE.search(word.replace(_THIS_COMPUTER, "")))


def _host_problem(run: list[str]) -> str | None:
    """Why the application might listen anywhere but on this computer, as far as its command line shows. A host option
    must say so, in full: 127.0.0.1 elsewhere in the command says nothing about what it listens on."""
    wanted = f"run must say --host {_THIS_COMPUTER}, in full, and name no other host"
    named = False
    for index, word in enumerate(run):
        option, _, value = word.partition("=")
        if option in _LISTENS_ELSEWHERE or _SHORT_HOST.match(word) or _names_elsewhere(word):
            return wanted
        if len(option) > 2 and any(full.startswith(option) for full in _HOST_OPTIONS):
            value = value or (run[index + 1] if index + 1 < len(run) else "")
            if option not in _HOST_OPTIONS or value not in (_THIS_COMPUTER, f"{_THIS_COMPUTER}:{{port}}"):
                return wanted
            named = True
    return None if named else wanted


def _environment_problem(environment: dict) -> str | None:
    """A host an application or its server reads from the environment, in the same words."""
    for name, value in environment.items():
        host = _HOST_VARIABLE.search(name) and value.split(":")[0] != _THIS_COMPUTER
        if host or any(_names_elsewhere(word) or _SHORT_HOST.fullmatch(word) for word in value.split()):
            return f"{name} must name {_THIS_COMPUTER} and no other host"
    return None


def preview(declaration: dict | None) -> dict | None:
    """How the project is run on the person's computer, if it says: `setup` (commands), `run` (a command) and
    `environment`. None when it says nothing; {"invalid": reason} when IT must correct it. This catches slips, not
    malice: IT reviews the declaration, as anything else on the main branch (docs/barriers.md)."""
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
    problem = _environment_problem(environment)
    if problem:
        return {"invalid": f"[preview.environment] {problem}; IT corrects it"}
    return {"setup": setup, "run": run, "environment": environment}
