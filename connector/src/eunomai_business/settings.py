"""The organization's choices for the specialist, set by IT when building the plugin (EUNOMAI_SPECIALIST)."""

import json
import os

DEFAULTS = {"docs_language": "en", "code_language": "", "free_development": False, "allowed_technologies": [],
            "projects": {}, "dependency_exceptions": [], "organization_context": "", "organization_skills": []}


def load() -> dict:
    raw = os.environ.get("EUNOMAI_SPECIALIST", "")
    try:
        configured = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"EUNOMAI_SPECIALIST is not valid JSON: {exc}") from exc
    values = {**DEFAULTS, **configured}
    values["code_language"] = values["code_language"] or values["docs_language"]
    return values


def _repository_key(url: str | None) -> str:
    return (url or "").strip().removesuffix("/").removesuffix(".git").lower()


def development(origin: str | None) -> dict:
    """Whether code may be written in a workspace, and with which technologies (empty list: any)."""
    values = load()
    projects = {_repository_key(url): project for url, project in values["projects"].items()}
    project = projects.get(_repository_key(origin))
    if project is not None:
        return {"code_allowed": True, "technologies": project.get("technologies", []),
                "reason": "the organization configured this project"}
    if values["free_development"]:
        return {"code_allowed": True, "technologies": values["allowed_technologies"],
                "reason": "free development is enabled"}
    return {"code_allowed": False, "technologies": [],
            "reason": "this project is not configured for development and free development is off"}
