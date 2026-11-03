"""A message for a person to send, written by the connector as a page on their computer and opened in their browser.

A model that retypes a long message can shorten it without saying so, and a long mailto link can be cut by the mail
program. So nothing long passes through either: the page holds the whole message, a button copies it with its format
for a mail program and as plain text for any other, and a link opens a new e-mail with only the address and the
subject. The person pastes, reads and sends; the connector sends nothing.

The page is neutral. An organization may give it its accent colour and font (`message_style`, set when building the
plugin); the copied message carries them as inline styles, the only ones mail programs keep.
"""

import base64
import hashlib
import html
import re
import webbrowser
from pathlib import Path
from urllib.parse import quote

ACCENT = re.compile(r"#[0-9a-fA-F]{6}\Z")
FONT = re.compile(r"[A-Za-z0-9 ,'\"-]{1,100}\Z")
DEFAULT_STYLE = {"accent": "#1f4e79", "font": "Arial, Helvetica, sans-serif"}

_SCRIPT = """
const button = document.getElementById("copy");
const done = document.getElementById("done");
button.addEventListener("click", async () => {
  const rich = document.getElementById("mail-html").innerHTML;
  const plain = document.getElementById("mail-text").content.textContent;
  try {
    await navigator.clipboard.write([new ClipboardItem({
      "text/html": new Blob([rich], {type: "text/html"}),
      "text/plain": new Blob([plain], {type: "text/plain"}),
    })]);
  } catch (error) {
    const range = document.createRange();
    range.selectNodeContents(document.getElementById("message"));
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.execCommand("copy");
    selection.removeAllRanges();
  }
  done.textContent = button.dataset.done;
});
"""


def style(configured: object) -> dict:
    """The organization's accent and font where they are valid; the neutral ones otherwise."""
    chosen = dict(DEFAULT_STYLE)
    if isinstance(configured, dict):
        if isinstance(configured.get("accent"), str) and ACCENT.match(configured["accent"]):
            chosen["accent"] = configured["accent"]
        if isinstance(configured.get("font"), str) and FONT.match(configured["font"]):
            chosen["font"] = configured["font"]
    return chosen


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def _lines(text: str) -> str:
    return "<br>".join(html.escape(line) for line in text.split("\n"))


def mail_html(title: str, lead: list[str], sections: list[tuple[str, str | list[str]]], chosen: dict,
              inline: bool = True) -> str:
    """The message as a mail program keeps it: plain elements, with inline styles when `inline`, the only styles a
    mail program keeps. Without them it is what the page shows, styled by the page. Every word is escaped."""
    font = html.escape(chosen["font"], quote=True)
    accent = chosen["accent"]

    def styled(value: str) -> str:
        return f' style="{value}"' if inline else ""

    parts = [f"<div{styled(f'font-family:{font};font-size:14px;line-height:1.45;color:#1a1a1a')}>",
             f"<h2{styled(f'font-family:{font};font-size:18px;color:{accent};margin:0 0 8px')}>{html.escape(title)}</h2>",
             f"<p{styled('margin:0 0 12px')}>{'<br>'.join(html.escape(line) for line in lead)}</p>"]
    for heading, content in sections:
        parts.append(f"<h3{styled(f'font-family:{font};font-size:15px;color:{accent};margin:14px 0 4px')}>"
                     f"{html.escape(heading)}</h3>")
        if isinstance(content, list):
            items = "".join(f"<li{styled('margin:0 0 2px')}>{_lines(item)}</li>" for item in content)
            parts.append(f"<ul{styled('margin:0 0 4px;padding-left:20px')}>{items}</ul>")
        else:
            parts.append(f"<p{styled('margin:0')}>{_lines(content)}</p>")
    parts.append("</div>")
    return "".join(parts)


def page(language: str, words: dict, title: str, lead: list[str], sections: list[tuple[str, str | list[str]]],
         text: str, address: str, subject: str, chosen: dict) -> str:
    """The whole page: what to do, the two buttons and the message. Nothing loads from anywhere; the only script and
    the only stylesheet are those written here, allowed by their hashes."""
    accent, font = chosen["accent"], chosen["font"]
    css = (f"body{{font-family:{font};margin:0;background:#f4f5f7;color:#1a1a1a}}"
           "main{max-width:760px;margin:32px auto;padding:0 16px}"
           ".steps{background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:16px}"
           ".steps ol{margin:8px 0 12px;padding-left:20px}"
           f".actions{{display:flex;gap:12px;flex-wrap:wrap;align-items:center}}"
           f"button,.mail{{font:inherit;font-size:15px;padding:10px 18px;border-radius:6px;cursor:pointer;"
           f"border:2px solid {accent};text-decoration:none}}"
           f"button{{background:{accent};color:#fff}}.mail{{background:#fff;color:{accent}}}"
           "button:focus-visible,.mail:focus-visible{outline:3px solid #1a1a1a;outline-offset:2px}"
           "#done{font-weight:bold}"
           ".message{background:#fff;border-radius:8px;padding:20px 24px;line-height:1.45}"
           f".message h2,.message h3{{color:{accent};margin:14px 0 4px}}.message h2{{margin-top:0}}"
           ".message p{margin:0 0 4px}.message ul{margin:0 0 4px;padding-left:20px}")
    mail_link = ""
    if address:
        href = f"mailto:{quote(address, safe='@')}?subject={quote(subject, safe='')}"
        mail_link = f'<a class="mail" href="{html.escape(href, quote=True)}">{html.escape(words["open_mail"])}</a>'
    steps = words["steps_mail"] if address else words["steps_copy"]
    rich = mail_html(title, lead, sections, chosen)
    # The copied message's inline styles, each allowed by its hash: the browser parses them when it copies, and would
    # otherwise complain of each. No other inline style is allowed.
    inline = " ".join(sorted({_hash(html.unescape(value)) for value in re.findall(r'style="([^"]*)"', rich)}))
    return (
        "<!doctype html>\n"
        f'<html lang="{html.escape(language, quote=True)}"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        f"style-src {_hash(css)} 'unsafe-hashes' {inline}; script-src {_hash(_SCRIPT)}\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(subject)}</title><style>{css}</style></head><body><main>"
        f'<section class="steps"><strong>{html.escape(words["page_title"])}</strong><ol>'
        + "".join(f"<li>{html.escape(step)}</li>" for step in steps)
        + f'</ol><div class="actions"><button type="button" id="copy" data-done="{html.escape(words["copied"], quote=True)}">'
        f'{html.escape(words["copy"])}</button>{mail_link}<span id="done" role="status"></span></div></section>'
        f'<section class="message" id="message">{mail_html(title, lead, sections, chosen, inline=False)}</section>'
        f'<template id="mail-html">{rich}</template>'
        f'<template id="mail-text">{html.escape(text)}</template>'
        f"<script>{_SCRIPT}</script></main></body></html>\n"
    )


def write_and_open(path: Path, content: str) -> tuple[str, bool]:
    """Writes the page and opens it in the person's browser: its address, and whether the browser said it opened.
    The address is of the resolved path, the one opened, so a short Windows name never gives two addresses."""
    path.write_bytes(content.encode("utf-8"))
    address = path.resolve().as_uri()
    try:
        return address, bool(webbrowser.open(address))
    except Exception:  # noqa: BLE001 - no browser is not a failure: the page is there to open by hand
        return address, False
