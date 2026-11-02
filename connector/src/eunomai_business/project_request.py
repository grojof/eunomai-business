"""A request for a new project, written by the connector for the person to send to IT.

A business person never creates repositories (docs/decisions.md, decision 15). When no project exists, the specialist
understands the idea in conversation; this module turns what was understood into a message with a fixed format, an
e-mail link to the organization's support address, and a copy in the connector's folder that a later task picks up.
The connector sends nothing: the person does.
"""

import json
import os
import re
import time
import unicodedata
from pathlib import Path

from . import data_dir, settings
from .support import mail_link

# A suggestion IT may change: lowercase letters, digits and hyphens, which every git hosting accepts as a repository
# name and every file system as a file name. Windows' reserved device names are refused, as for workspaces.
_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")
_WINDOWS_RESERVED = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])\Z")
_REQUEST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,70}[a-z0-9])?\Z")
_FIELD_LIMIT = 4000
_QUESTION_LIMIT = 500
_QUESTIONS = 30
# Characters that change how a line reads without being seen: bidirectional overrides and isolates.
_INVISIBLE = re.compile("[‪-‮⁦-⁩]")
_SECTIONS = ("purpose", "users", "today", "first_version")
_SUBJECT = "eunomai-business: "  # fixed, so a mailbox rule can recognise a request in any language
# The fixed text, in the organization's documentation language (docs_language); any other language reads English.
# The person's own words are never translated.
WORDS = {
    "en": {"subject": "new project request: {name}", "title": "New project request",
           "name": "Proposed name: {name} (a suggestion: IT decides the name)", "request": "Request: {request}",
           "date": "Requested: {date}", "purpose": "What it is for", "users": "Who will use it",
           "today": "How it is done today", "first_version": "What the first version includes",
           "out_of_scope": "Out of scope", "nothing": "Nothing stated.", "open_questions": "Open questions",
           "none": "None.", "it": "What IT does",
           "it_text": "Create the repository from the organization's template, with its main branch protected, give "
                      "the requester write access, and reply with its address (owner/name). The requester then tells "
                      "the assistant it exists, and the work goes on from this request."},
    "es": {"subject": "solicitud de proyecto nuevo: {name}", "title": "Solicitud de proyecto nuevo",
           "name": "Nombre propuesto: {name} (una sugerencia: el nombre lo decide IT)", "request": "Solicitud: {request}",
           "date": "Fecha: {date}", "purpose": "Para qué sirve", "users": "Quién lo usará",
           "today": "Cómo se hace hoy", "first_version": "Qué incluye la primera versión",
           "out_of_scope": "Fuera de alcance", "nothing": "No se ha indicado nada.", "open_questions": "Preguntas abiertas",
           "none": "Ninguna.", "it": "Qué hace IT",
           "it_text": "Crear el repositorio a partir de la plantilla de la organización, con la rama principal "
                      "protegida, dar acceso de escritura a quien lo solicita y responder con su dirección "
                      "(propietario/nombre). Quien lo solicita avisa entonces al asistente de que existe, y el trabajo "
                      "sigue a partir de esta solicitud."},
    "ca": {"subject": "sol·licitud de projecte nou: {name}", "title": "Sol·licitud de projecte nou",
           "name": "Nom proposat: {name} (un suggeriment: el nom el decideix IT)", "request": "Sol·licitud: {request}",
           "date": "Data: {date}", "purpose": "Per a què serveix", "users": "Qui l'utilitzarà",
           "today": "Com es fa avui", "first_version": "Què inclou la primera versió",
           "out_of_scope": "Fora de l'abast", "nothing": "No s'ha indicat res.", "open_questions": "Preguntes obertes",
           "none": "Cap.", "it": "Què fa IT",
           "it_text": "Crear el repositori a partir de la plantilla de l'organització, amb la branca principal "
                      "protegida, donar accés d'escriptura a qui ho sol·licita i respondre amb la seva adreça "
                      "(propietari/nom). Qui ho sol·licita avisa llavors l'assistent que existeix, i la feina continua "
                      "a partir d'aquesta sol·licitud."},
}


def _folder() -> Path:
    return data_dir() / "project-requests"


def _text(value, field: str, required: bool, limit: int = _FIELD_LIMIT) -> str:
    """Text as the person said it, with line breaks kept and nothing that could hide or break a line."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    value = "".join(char for char in value if char == "\n" or unicodedata.category(char) != "Cc")
    value = "\n".join(line.rstrip() for line in _INVISIBLE.sub("", value).split("\n")).strip("\n ")
    if required and not value:
        raise ValueError(f"{field} cannot be empty: ask the person, or write what was understood")
    if len(value) > limit:
        raise ValueError(f"{field} is longer than {limit} characters: summarise it")
    return value


def _check_name(name) -> str:
    if not isinstance(name, str) or not _NAME.match(name) or _WINDOWS_RESERVED.match(name) \
            or name.endswith(("-git", "-wiki")):
        raise ValueError("name: a suggested repository name, 1 to 64 lowercase ASCII letters, digits and hyphens, "
                         "starting and ending with a letter or digit (for example alta-de-pedidos)")
    return name


def language() -> str:
    configured = str(settings.load()["docs_language"]).lower()
    return configured if configured in WORDS else "en"


def message(fields: dict) -> tuple[str, str]:
    """(subject, text) of a request, in its language. The same fields always give the same message."""
    words = WORDS[fields["language"]]
    subject = _SUBJECT + words["subject"].format(name=fields["name"])
    lines = [words["title"], "", words["name"].format(name=fields["name"]),
             words["request"].format(request=fields["request"]), words["date"].format(date=fields["created"][:10])]
    for key in _SECTIONS:
        lines += ["", words[key], fields[key]]
    lines += ["", words["out_of_scope"], fields["out_of_scope"] or words["nothing"]]
    lines += ["", words["open_questions"],
              *([f"- {question}" for question in fields["open_questions"]] or [words["none"]])]
    lines += ["", words["it"], words["it_text"]]
    return subject, "\n".join(lines) + "\n"


def _read(path: Path) -> dict | None:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) and saved.get("status") in ("pending", "done") else None


def _write(path: Path, saved: dict, new: bool) -> None:
    """Whole or not at all: a temporary file beside it, then put in place. A new request never takes another's file."""
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(json.dumps(saved, ensure_ascii=False, indent=1).encode("utf-8"))
        if new:
            with open(path, "x", encoding="utf-8"):
                pass  # claims the name: two tasks never write the same new request
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        if new and path.exists() and path.stat().st_size == 0:
            path.unlink(missing_ok=True)
        raise


def _saved() -> list[tuple[Path, dict]]:
    folder = _folder()
    if not folder.is_dir():
        return []
    found = [(path, _read(path)) for path in sorted(folder.glob("*.json")) if _REQUEST.match(path.stem)]
    return [(path, saved) for path, saved in found if saved is not None]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def prepare(name: str, purpose: str, users: str, today: str, first_version: str, out_of_scope: str = "",
            open_questions: list[str] | None = None) -> dict:
    name = _check_name(name)
    fields = {key: _text(value, key, True) for key, value in
              (("purpose", purpose), ("users", users), ("today", today), ("first_version", first_version))}
    fields["out_of_scope"] = _text(out_of_scope, "out_of_scope", False)
    questions = open_questions or []
    if not isinstance(questions, list) or len(questions) > _QUESTIONS:
        raise ValueError(f"open_questions: a list of at most {_QUESTIONS} questions")
    fields["open_questions"] = [text for text in (_text(question, "an open question", False, _QUESTION_LIMIT)
                                                  for question in questions) if text]
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    saved = _saved()
    pending = next(((path, old) for path, old in saved if old["status"] == "pending" and old.get("name") == name),
                   None)
    if pending:
        path, old = pending
        request, created = path.stem, old.get("created") or _now()
    else:
        taken = {path.stem for path, _ in saved} | {path.stem for path in folder.glob("*.json")}
        request = next(candidate for candidate in (name, *(f"{name}-{n}" for n in range(2, 1000)))
                       if candidate not in taken)
        path, created = folder / f"{request}.json", _now()
    record = {"request": request, "status": "pending", "name": name, **fields, "created": created,
              "language": language()}
    if pending:
        record["updated"] = _now()
    subject, text = message(record)
    record.update(subject=subject, text=text)
    _write(path, record, new=not pending)
    answer = {"status": "prepared", "request": request, "name": name, "replaced": bool(pending), "subject": subject,
              "text": text, "saved": str(path)}
    address = os.environ.get("EUNOMAI_SUPPORT_EMAIL", "").strip()
    if address:
        answer["email_link"] = mail_link(address, subject, text)
        answer["user_message"] = ("Your request for a new project is ready. Open the e-mail, check it and send it to "
                                  "IT; nothing has been sent yet. When IT tells you the project exists, come back and "
                                  "say so, and the work goes on from here.")
    else:
        answer["user_message"] = ("Your request for a new project is ready. Copy the text and send it to IT the way you "
                                  "usually reach them; nothing has been sent yet. When IT tells you the project exists, "
                                  "come back and say so, and the work goes on from here.")
    return answer


def pending() -> list[dict]:
    """Requests not yet marked done, oldest first, with what was understood (not the message itself)."""
    keys = ("request", "name", "purpose", "users", "today", "first_version", "out_of_scope", "open_questions",
            "created")
    found = [{key: saved.get(key) for key in keys} for _, saved in _saved() if saved["status"] == "pending"]
    return sorted(found, key=lambda entry: (str(entry["created"]), entry["request"]))


def done(request: str, workspace: str, origin: str) -> dict:
    """Mark a request done once its project is a workspace here. It is kept, with where it went."""
    if not isinstance(request, str) or not _REQUEST.match(request):
        raise ValueError("request: the `request` of a saved project request, as workspace_list lists it")
    path = _folder() / f"{request}.json"
    saved = _read(path) if path.is_file() else None
    if saved is None:
        raise FileNotFoundError(f"no saved project request {request!r}; see workspace_list")
    if saved["status"] == "done":
        return {"status": "already_done", "request": request, "workspace": saved.get("workspace")}
    saved.update(status="done", done=_now(), workspace=workspace, origin=origin)
    _write(path, saved, new=False)
    return {"status": "done", "request": request, "workspace": workspace}
