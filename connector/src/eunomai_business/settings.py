"""The organization's choices for the specialist, set by IT when building the plugin (EUNOMAI_SPECIALIST), and what a
project declares for itself on its main branch (.eunomai/project.toml)."""

import json
import os
import tomllib

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
