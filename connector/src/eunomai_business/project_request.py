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
from . import data_dir
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
_SECTIONS = (("purpose", "What it is for"), ("users", "Who will use it"), ("today", "How it is done today"),
             ("first_version", "What the first version includes"))
WHAT_IT_DOES = ("Create the repository from the organization's template, with its main branch protected, give the "
                "requester write access, and reply with its address (owner/name). The requester then tells the "
                "assistant it exists, and the work goes on from this request.")


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


def message(fields: dict) -> tuple[str, str]:
    """(subject, text) of a request. The same fields always give the same message."""
    subject = f"eunomai-business: new project request: {fields['name']}"
    lines = ["New project request", "",
             f"Proposed name: {fields['name']} (a suggestion: IT decides the name)",
             f"Request: {fields['request']}", f"Requested: {fields['created'][:10]}"]
    for key, heading in _SECTIONS:
        lines += ["", heading, fields[key]]
    lines += ["", "Out of scope", fields["out_of_scope"] or "Nothing stated."]
    lines += ["", "Open questions", *([f"- {question}" for question in fields["open_questions"]] or ["None."])]
    lines += ["", "What IT does", WHAT_IT_DOES]
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
    record = {"request": request, "status": "pending", "name": name, **fields, "created": created}
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
