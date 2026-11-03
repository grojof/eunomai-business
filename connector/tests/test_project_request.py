"""A request for a new project: the connector writes it, the person sends it, IT creates the repository.

A business person never creates repositories. When no project exists, the specialist understands the idea in
conversation and `project_request` turns it into a fixed message for IT, a page in the person's browser that copies
it and opens an e-mail with its subject, and a saved copy that a later task picks up from `workspace_list`. The
message never goes back to the model, which could retype it shorter. Nothing is sent by the connector.
"""

import base64
import hashlib
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from eunomai_business import data_dir, message_page, server as tools

FIELDS = {"name": "alta-de-pedidos", "purpose": "Register customer orders in one place.",
          "users": "The sales team, about ten people.", "today": "A shared spreadsheet, copied by e-mail.",
          "first_version": "Enter an order and list the open ones."}


@pytest.fixture(autouse=True)
def opened(monkeypatch, workspaces) -> list:
    shutil.rmtree(data_dir() / "project-requests", ignore_errors=True)
    monkeypatch.setenv("EUNOMAI_SUPPORT_EMAIL", "it@example.test")
    pages: list = []
    monkeypatch.setattr(message_page.webbrowser, "open", lambda url: pages.append(url) or True)
    yield pages
    shutil.rmtree(data_dir() / "project-requests", ignore_errors=True)


def prepare(**changes) -> dict:
    return tools.project_request(**{**FIELDS, **changes})


def text_of(answer: dict) -> str:
    """The message as saved: the answer never carries it."""
    return json.loads(Path(answer["saved"]).read_text(encoding="utf-8"))["text"]


def page_of(answer: dict) -> str:
    return Path(answer["saved"]).with_suffix(".html").read_text(encoding="utf-8")


def mail(link: str) -> tuple[str, dict]:
    """The address and the fields of a mailto link, as a mail program reads them."""
    parts = urlsplit(link)
    assert parts.scheme == "mailto" and not parts.fragment
    return unquote(parts.path), parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)


def mail_links(page: str) -> list[str]:
    return [html.unescape(link) for link in re.findall(r'href="(mailto:[^"]*)"', page)]


def template(page: str, name: str) -> str:
    return re.search(rf'<template id="{name}">(.*?)</template>', page, re.S).group(1)


def saved_files() -> list:
    return sorted((data_dir() / "project-requests").glob("*.json"))


# --- the message ---------------------------------------------------------------------------------------------

def test_the_request_has_a_fixed_subject_and_sections_in_order():
    answer = prepare(open_questions=["Who approves an order?", "Do orders have a maximum amount?"],
                     out_of_scope="Invoices.")
    assert answer["status"] == "prepared" and answer["request"] == "alta-de-pedidos"
    assert answer["subject"] == "eunomai-business: new project request: alta-de-pedidos"
    text = text_of(answer)
    headings = ["New project request", "Proposed name: alta-de-pedidos", "Request: alta-de-pedidos", "Requested: ",
                "What it is for", "Who will use it", "How it is done today", "What the first version includes",
                "Out of scope", "Open questions", "What IT does"]
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "IT decides the name" in text
    assert "Register customer orders in one place." in text and "- Who approves an order?" in text
    assert "- Do orders have a maximum amount?" in text and "Invoices." in text
    assert "from the organization's template" in text and "main branch protected" in text
    assert "nothing has been sent" in answer["user_message"].lower()


def test_the_message_never_goes_back_to_the_model():
    answer = prepare()
    assert not {"text", "email_link", "body"} & set(answer)
    assert "Register customer orders" not in json.dumps(answer)


def test_the_requesters_git_user_is_the_signed_in_one(signed_in):
    text = text_of(prepare())
    assert "\nRequester's git user: tester\n" in text
    assert text.index("Request: alta-de-pedidos") < text.index("Requester's git user") < text.index("Requested: ")


def test_without_a_sign_in_the_message_names_no_git_user():
    assert "git user" not in text_of(prepare())


@pytest.mark.parametrize("login", ["", "a b", "x\nRequest: other", "<b>", "x" * 101])
def test_a_git_user_that_is_not_a_plain_name_is_left_out(login):
    from eunomai_business import project_request

    answer = project_request.prepare(**FIELDS, requester=login)
    assert "git user" not in text_of(answer)


def test_the_same_fields_give_the_same_text():
    first, second = text_of(prepare()), text_of(prepare())
    assert first == second


def test_empty_optional_sections_say_so():
    text = text_of(prepare())
    assert "Out of scope\nNothing stated." in text and "Open questions\nNone." in text


# --- the page ------------------------------------------------------------------------------------------------

def test_the_page_opens_in_the_browser_with_the_whole_message(opened):
    answer = prepare(open_questions=["Who approves an order?"], out_of_scope="Invoices.")
    page = page_of(answer)
    assert opened == [answer["page"]] and answer["opened"] is True
    assert answer["page"] == Path(answer["saved"]).with_suffix(".html").resolve().as_uri()
    assert "open in your browser" in answer["user_message"]
    assert html.unescape(template(page, "mail-text")) == text_of(answer)
    rich = template(page, "mail-html")
    for words in ("Register customer orders in one place.", "Who approves an order?", "Invoices.", "Open questions"):
        assert html.escape(words) in rich
    assert 'style="' in rich, "a mail program keeps inline styles only"
    assert 'style="' not in re.search(r'<section class="message".*?</section>', page, re.S).group(0)


def test_the_e_mail_link_carries_only_the_address_and_the_subject():
    answer = prepare()
    [link] = mail_links(page_of(answer))
    address, fields = mail(link)
    assert address == "it@example.test" and fields == {"subject": [answer["subject"]]}


def test_the_page_loads_nothing_and_runs_only_its_own_script():
    page = page_of(prepare())
    policy = re.search(r'Content-Security-Policy" content="([^"]*)"', page).group(1)
    assert policy.startswith("default-src 'none';") and "unsafe-inline" not in policy and "unsafe-eval" not in policy
    attributes = {html.unescape(value) for value in re.findall(r'style="([^"]*)"', page)}
    for value in attributes:  # the copied message's styles, each by its hash, and no other
        digest = base64.b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii")
        assert f"'sha256-{digest}'" in policy
    assert policy.count("'sha256-") == len(attributes) + 2
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    for source in (script, style):
        digest = base64.b64encode(hashlib.sha256(source.encode("utf-8")).digest()).decode("ascii")
        assert f"'sha256-{digest}'" in policy
    assert page.count("<script") == 1 and not re.search(r"\b(src|href)=\"(https?:)?//", page)


@pytest.mark.parametrize("hostile", [
    "Orders & more?body=replaced&cc=someone@example.test",
    "Line one\r\nBcc: someone@example.test\r\n\r\nLine two",
    "Hash # and percent %41 and plus + and equals =",
    "Tabs\tand bells\x07 and nulls\x00 and escapes\x1b[31m",
    "Right-to-left ‮override‬ and isolates ⁦x⁩",
    "Accents: añadir, façade, Größe; and 注文",
    "</template><script>alert(1)</script><img src=x onerror=alert(1)>",
])
def test_characters_that_must_not_break_the_page_or_the_mail(hostile):
    answer = prepare(purpose=hostile, open_questions=[hostile])
    page, text = page_of(answer), text_of(answer)
    [link] = mail_links(page)
    assert set(mail(link)[1]) == {"subject"}, "nothing in a field becomes another field of the mail"
    assert page.count("<script") == 1 and "<img" not in page and "<script>alert" not in page
    assert page.count("<template") == 2 and page.count("</template>") == 2
    assert not any(ord(char) < 32 and char not in "\n\t" for char in text)
    assert not any(char in text for char in "‪‫‬‭‮⁦⁧⁨⁩")
    assert "Bcc: someone" not in text.split("\n")[0]
    if "Accents" in hostile:
        assert "añadir, façade, Größe; and 注文" in text and "añadir, façade, Größe; and 注文" in page


def test_without_a_support_address_the_page_still_copies_the_message(monkeypatch):
    monkeypatch.delenv("EUNOMAI_SUPPORT_EMAIL")
    answer = prepare()
    page = page_of(answer)
    assert answer["status"] == "prepared" and not mail_links(page) and saved_files()
    assert text_of(answer).startswith("New project request") and 'id="copy"' in page
    assert "the way you usually reach them" in answer["user_message"] and "the way you usually reach them" in page


def test_without_a_browser_the_answer_says_where_the_page_is(monkeypatch):
    monkeypatch.setattr(message_page.webbrowser, "open", lambda url: False)
    answer = prepare()
    assert answer["opened"] is False and answer["page"] in answer["user_message"]


def test_the_organizations_accent_and_font_reach_the_copied_message(monkeypatch):
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"message_style": {"accent": "#7a1f5c", "font": "Verdana"}}))
    rich = template(page_of(prepare()), "mail-html")
    assert "color:#7a1f5c" in rich and "font-family:Verdana" in rich


@pytest.mark.parametrize("style", [{"accent": "red;background:url(x)"}, {"font": "x}body{display:none"},
                                   {"accent": 5}, "Verdana", None])
def test_a_style_that_is_not_a_colour_or_font_names_falls_back_to_the_neutral_one(monkeypatch, style):
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"message_style": style}))
    page = page_of(prepare())
    assert "url(x)" not in page and "display:none" not in page
    assert message_page.DEFAULT_STYLE["accent"] in page


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
    assert saved["text"] == text_of(answer) and saved["subject"] == answer["subject"]
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
    from eunomai_business import project_request

    text, page = text_of(answer), page_of(answer)
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert f"\n{nothing}\n" in text and f"\n{none}\n" in text
    assert "Registrar pedidos." in text, "the person's words stay as given"
    [link] = mail_links(page)
    assert mail(link)[1] == {"subject": [subject]} and f'<html lang="{language}">' in page
    words = project_request.WORDS[language]
    assert html.escape(words["copy"]) in page and html.escape(words["steps_mail"][0]) in page
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


# --- withdrawn -------------------------------------------------------------------------------------------------

def test_a_withdrawn_request_is_kept_and_no_longer_listed():
    prepare()
    answer = tools.project_request_withdraw("alta-de-pedidos")
    assert answer["status"] == "withdrawn" and answer["request"] == "alta-de-pedidos"
    [path] = saved_files()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "withdrawn" and saved["withdrawn"] and saved["text"]
    assert tools.workspace_list()["project_requests"] == []
    assert tools.project_request_withdraw("alta-de-pedidos")["status"] == "already_withdrawn"
    assert "error" in tools.project_request_done("alta-de-pedidos", "anything")


def test_the_same_name_after_one_is_withdrawn_is_a_new_request():
    prepare()
    tools.project_request_withdraw("alta-de-pedidos")
    again = prepare()
    assert again["replaced"] is False and again["request"] == "alta-de-pedidos-2"


def test_a_request_already_done_is_not_withdrawn(signed_in, workspaces):
    signed_in.initialize("pedidos-kept")
    prepare()
    tools.workspace_clone(f"{signed_in.url}/me/pedidos-kept.git")
    tools.project_request_done("alta-de-pedidos", "pedidos-kept")
    assert tools.project_request_withdraw("alta-de-pedidos")["status"] == "already_done"
    assert json.loads(saved_files()[0].read_text(encoding="utf-8"))["status"] == "done"


def test_withdrawing_an_unknown_request_is_a_mistake_in_the_call():
    assert "error" in tools.project_request_withdraw("never-asked")
    assert "error" in tools.project_request_withdraw("../x")
