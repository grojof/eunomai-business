"""A request for a new project: the connector writes it, the person sends it, IT creates the repository.

A business person never creates repositories. When no project exists, the specialist understands the idea in
conversation and `project_request` turns it into a fixed message for IT, an e-mail link and a saved copy that a later
task picks up from `workspace_list`. Nothing is sent by the connector.
"""

import json
import shutil
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from eunomai_business import data_dir, server as tools

FIELDS = {"name": "alta-de-pedidos", "purpose": "Register customer orders in one place.",
          "users": "The sales team, about ten people.", "today": "A shared spreadsheet, copied by e-mail.",
          "first_version": "Enter an order and list the open ones."}


@pytest.fixture(autouse=True)
def no_requests(monkeypatch, workspaces):
    shutil.rmtree(data_dir() / "project-requests", ignore_errors=True)
    monkeypatch.setenv("EUNOMAI_SUPPORT_EMAIL", "it@example.test")
    yield
    shutil.rmtree(data_dir() / "project-requests", ignore_errors=True)


def prepare(**changes) -> dict:
    return tools.project_request(**{**FIELDS, **changes})


def mail(link: str) -> tuple[str, dict]:
    """The address and the fields of a mailto link, as a mail program reads them."""
    parts = urlsplit(link)
    assert parts.scheme == "mailto" and not parts.fragment
    return unquote(parts.path), parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)


def saved_files() -> list:
    return sorted((data_dir() / "project-requests").glob("*.json"))


# --- the message ---------------------------------------------------------------------------------------------

def test_the_request_has_a_fixed_subject_and_sections_in_order():
    answer = prepare(open_questions=["Who approves an order?", "Do orders have a maximum amount?"],
                     out_of_scope="Invoices.")
    assert answer["status"] == "prepared" and answer["request"] == "alta-de-pedidos"
    assert answer["subject"] == "eunomai-business: new project request: alta-de-pedidos"
    text = answer["text"]
    headings = ["New project request", "Proposed name: alta-de-pedidos", "What it is for", "Who will use it",
                "How it is done today", "What the first version includes", "Out of scope", "Open questions",
                "What IT does"]
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "IT decides the name" in text
    assert "Register customer orders in one place." in text and "- Who approves an order?" in text
    assert "- Do orders have a maximum amount?" in text and "Invoices." in text
    assert "from the organization's template" in text and "main branch protected" in text
    assert "nothing has been sent" in answer["user_message"]


def test_the_same_fields_give_the_same_text():
    first, second = prepare()["text"], prepare()["text"]
    assert first == second


def test_empty_optional_sections_say_so():
    text = prepare()["text"]
    assert "Out of scope\nNothing stated." in text and "Open questions\nNone." in text


def test_the_mail_link_carries_the_subject_and_the_text_with_crlf_line_breaks():
    answer = prepare()
    address, fields = mail(answer["email_link"])
    assert address == "it@example.test" and set(fields) == {"subject", "body"}
    assert fields["subject"] == [answer["subject"]]
    assert fields["body"] == [answer["text"].replace("\n", "\r\n")]
    assert "%0D%0A" in answer["email_link"] and "%0A" not in answer["email_link"].replace("%0D%0A", "")


@pytest.mark.parametrize("hostile", [
    "Orders & more?body=replaced&cc=someone@example.test",
    "Line one\r\nBcc: someone@example.test\r\n\r\nLine two",
    "Hash # and percent %41 and plus + and equals =",
    "Tabs\tand bells\x07 and nulls\x00 and escapes\x1b[31m",
    "Right-to-left ‮override‬ and isolates ⁦x⁩",
    "Accents: añadir, façade, Größe; and 注文",
])
def test_characters_that_must_not_break_the_mail(hostile):
    answer = prepare(purpose=hostile, open_questions=[hostile])
    _, fields = mail(answer["email_link"])
    assert set(fields) == {"subject", "body"}, "nothing in a field becomes another field of the mail"
    body = fields["body"][0]
    assert body == answer["text"].replace("\n", "\r\n")
    assert not any(ord(char) < 32 and char not in "\r\n\t" for char in body)
    assert not any(char in body for char in "‪‫‬‭‮⁦⁧⁨⁩")
    assert "Bcc: someone" not in body.split("\r\n")[0]
    if "Accents" in hostile:
        assert "añadir, façade, Größe; and 注文" in body


def test_without_a_support_address_the_text_is_still_ready_to_copy(monkeypatch):
    monkeypatch.delenv("EUNOMAI_SUPPORT_EMAIL")
    answer = prepare()
    assert answer["status"] == "prepared" and "email_link" not in answer
    assert answer["text"].startswith("New project request") and saved_files()
    assert "copy" in answer["user_message"].lower()


# --- what is not a request ----------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["", "Alta-De-Pedidos", "alta de pedidos", "../outside", "a/b", "a\\b", "con",
                                  "lpt1", "nul", "-starts", "ends-", "pedidos.git", "añadir", "x" * 65, "a.b",
                                  "name\nwith-line"])
def test_a_name_that_is_not_a_plain_repository_name_is_a_mistake_in_the_call(name):
    answer = prepare(name=name)
    assert "error" in answer and not saved_files()


@pytest.mark.parametrize("field", ["purpose", "users", "today", "first_version"])
def test_a_required_section_cannot_be_empty(field):
    assert "error" in prepare(**{field: "  \n "}) and not saved_files()


def test_overlong_text_is_refused_rather_than_cut():
    assert "error" in prepare(purpose="x" * 4001)
    assert "error" in prepare(open_questions=["?"] * 31)
    assert "error" in prepare(open_questions=["x" * 501])


# --- the saved copy --------------------------------------------------------------------------------------------

def test_a_copy_is_kept_in_the_connectors_folder_and_listed_as_pending():
    answer = prepare(open_questions=["Who approves an order?"])
    [path] = saved_files()
    assert answer["saved"] == str(path) and path.parent == data_dir() / "project-requests"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "pending" and saved["name"] == "alta-de-pedidos"
    assert saved["text"] == answer["text"] and saved["subject"] == answer["subject"]
    assert saved["open_questions"] == ["Who approves an order?"] and saved["created"]
    listed = tools.workspace_list()["project_requests"]
    assert [entry["request"] for entry in listed] == ["alta-de-pedidos"]
    assert listed[0]["first_version"] == FIELDS["first_version"] and "text" not in listed[0]


def test_the_same_name_twice_replaces_the_pending_request():
    prepare()
    again = prepare(purpose="Register and approve customer orders.")
    assert again["replaced"] is True and again["request"] == "alta-de-pedidos"
    [path] = saved_files()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["purpose"] == "Register and approve customer orders." and saved["updated"]
    assert len(tools.workspace_list()["project_requests"]) == 1


def test_nothing_is_left_behind_when_saving_fails(monkeypatch):
    import os

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    answer = prepare()
    assert answer.get("status") != "prepared"
    assert not list((data_dir() / "project-requests").glob("*"))


# --- when IT has created it ------------------------------------------------------------------------------------

def test_marking_done_keeps_the_request_and_records_where_it_went(signed_in, workspaces):
    signed_in.initialize("alta-pedidos")
    prepare()
    tools.workspace_clone(f"{signed_in.url}/me/alta-pedidos.git")
    answer = tools.project_request_done("alta-de-pedidos", "alta-pedidos")
    assert answer["status"] == "done" and answer["workspace"] == "alta-pedidos"
    [path] = saved_files()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "done" and saved["workspace"] == "alta-pedidos" and saved["done"]
    assert saved["origin"].endswith("/me/alta-pedidos.git") and saved["text"]
    assert tools.workspace_list()["project_requests"] == []
    assert tools.project_request_done("alta-de-pedidos", "alta-pedidos")["status"] == "already_done"


def test_a_request_is_only_marked_done_with_a_workspace_on_this_computer():
    prepare()
    assert "error" in tools.project_request_done("alta-de-pedidos", "not-cloned")
    assert tools.workspace_list()["project_requests"][0]["request"] == "alta-de-pedidos"


def test_an_unknown_request_is_a_mistake_in_the_call():
    assert "error" in tools.project_request_done("never-asked", "anything")
    assert "error" in tools.project_request_done("../workspaces", "anything")


def test_the_same_name_after_one_is_done_is_a_new_request(signed_in, workspaces):
    signed_in.initialize("pedidos-done")
    prepare()
    tools.workspace_clone(f"{signed_in.url}/me/pedidos-done.git")
    tools.project_request_done("alta-de-pedidos", "pedidos-done")
    again = prepare()
    assert again["replaced"] is False and again["request"] == "alta-de-pedidos-2"
    assert {p.stem for p in saved_files()} == {"alta-de-pedidos", "alta-de-pedidos-2"}
    assert [r["request"] for r in tools.workspace_list()["project_requests"]] == ["alta-de-pedidos-2"]


def test_a_saved_copy_that_cannot_be_read_is_skipped_not_fatal():
    prepare()
    (data_dir() / "project-requests" / "broken.json").write_text("{not json", encoding="utf-8")
    listed = tools.workspace_list()["project_requests"]
    assert [entry["request"] for entry in listed] == ["alta-de-pedidos"]


# --- in the organization's language ----------------------------------------------------------------------------

LANGUAGES = {
    "en": ("eunomai-business: new project request: alta-de-pedidos",
           ["New project request", "Proposed name: alta-de-pedidos", "What it is for", "Who will use it",
            "How it is done today", "What the first version includes", "Out of scope", "Open questions",
            "What IT does"], "Nothing stated.", "None."),
    "es": ("eunomai-business: solicitud de proyecto nuevo: alta-de-pedidos",
           ["Solicitud de proyecto nuevo", "Nombre propuesto: alta-de-pedidos", "Para qué sirve", "Quién lo usará",
            "Cómo se hace hoy", "Qué incluye la primera versión", "Fuera de alcance", "Preguntas abiertas",
            "Qué hace IT"], "No se ha indicado nada.", "Ninguna."),
    "ca": ("eunomai-business: sol·licitud de projecte nou: alta-de-pedidos",
           ["Sol·licitud de projecte nou", "Nom proposat: alta-de-pedidos", "Per a què serveix", "Qui l'utilitzarà",
            "Com es fa avui", "Què inclou la primera versió", "Fora de l'abast", "Preguntes obertes",
            "Què fa IT"], "No s'ha indicat res.", "Cap."),
}


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_the_fixed_text_is_in_the_organizations_documentation_language(monkeypatch, language):
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"docs_language": language}))
    subject, headings, nothing, none = LANGUAGES[language]
    answer = prepare(purpose="Registrar pedidos.")
    assert answer["subject"] == subject and answer["subject"].startswith("eunomai-business: ")
    positions = [answer["text"].index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert f"\n{nothing}\n" in answer["text"] and f"\n{none}\n" in answer["text"]
    assert "Registrar pedidos." in answer["text"], "the person's words stay as given"
    _, fields = mail(answer["email_link"])
    assert fields["subject"] == [subject] and fields["body"] == [answer["text"].replace("\n", "\r\n")]
    saved = json.loads(Path(answer["saved"]).read_text(encoding="utf-8"))
    assert saved["language"] == language


def test_another_language_falls_back_to_english(monkeypatch):
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"docs_language": "fr"}))
    assert prepare()["subject"] == LANGUAGES["en"][0]


def test_every_language_has_every_fixed_text():
    from eunomai_business import project_request

    keys = set(project_request.WORDS["en"])
    assert set(project_request.WORDS) == {"en", "es", "ca"}
    assert all(set(words) == keys for words in project_request.WORDS.values())
