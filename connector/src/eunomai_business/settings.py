"""The organization's choices for the specialist, set by IT when building the plugin (EUNOMAI_SPECIALIST), and what a
project declares for itself on its main branch (.eunomai/project.toml)."""

import json
import os
import re
import tomllib
from urllib.parse import urlsplit

DEFAULTS = {"docs_language": "en", "code_language": "", "free_development": False, "allowed_technologies": [],
            "dependency_exceptions": [], "organization_context": "", "organization_skills": []}


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
