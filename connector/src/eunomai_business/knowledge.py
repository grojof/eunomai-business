"""What an application knows, as IT reads it in a pull request: its pages by kind and tag, and its requirements with
their source (docs/decisions.md, decision 16). A report, never a refusal: the work is the person's, the review is IT's.

The pages are read from the commit the server holds, never from the folder. Everything quoted from them was written
by the assistant, so it reaches the pull request only as short code spans, which the server shows as text: no
formatting, link, image or mention of its own."""

import bisect
import re
import unicodedata

KINDS = {"context": "explanation", "glossary": "reference", "decision": "decision", "open-question": "reference"}
"""Each kind's tag and the `type` its pages carry. Always allowed, whatever the organization's vocabulary says."""

TAG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHOWN = 10
"""Entries listed per finding in a pull request; the rest are counted."""
QUOTED = 80
"""Characters of a value quoted from a page."""

_REQUIREMENT = re.compile(r"^### Requirement:[^\S\r\n]*(.*?)[^\S\r\n]*$", re.MULTILINE)
_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_SOURCE = re.compile(r"^\*\*Source:\*\*[^\S\r\n]*(\S.*)$", re.MULTILINE)
_KEY = re.compile(r"([A-Za-z_][\w-]*)[^\S\r\n]*:(.*)\Z")


def is_page(path: str) -> bool:
    """A page of the application's own knowledge: under docs/, not the base's reference in docs/base/."""
    return path.startswith("docs/") and not path.startswith("docs/base/") and path.endswith(".md")


def is_spec(path: str) -> bool:
    """A requirement in force: openspec/specs/."""
    return path.startswith("openspec/specs/") and path.endswith(".md")


def is_proposed_spec(path: str) -> bool:
    """A requirement still in a change, `openspec/changes/<name>/specs/`, never the archive: where code is not allowed,
    the specification is what is delivered, and it stays there."""
    parts = path.split("/")
    return (len(parts) >= 5 and parts[:2] == ["openspec", "changes"] and parts[2] != "archive"
            and parts[3] == "specs" and path.endswith(".md"))


def is_read(path: str) -> bool:
    return is_page(path) or is_spec(path) or is_proposed_spec(path)


def merges_by_line(path: str) -> bool:
    """A page two people may both change and have joined line by line when the lines do not meet: the application's
    own pages and anything written in openspec/. Code, configuration and the base's reference never are."""
    return is_page(path) or (path.startswith("openspec/") and path.endswith(".md"))


def frontmatter(text: str) -> dict[str, str] | None:
    """The page's frontmatter, or None without one: each top-level key with its value on one line, a list written as
    `[a, b]` over one or more lines or as `- a` lines below its key. Only what the check reads; keys in lowercase."""
    lines = text.lstrip("﻿").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(number for number, line in enumerate(lines[1:], 1) if line.strip() in ("---", "..."))
    except StopIteration:
        return None
    found: dict[str, str] = {}
    key = ""
    for line in lines[1:end]:
        if line[:1] not in (" ", "\t", "#", "") and _KEY.match(line):
            key, value = _KEY.match(line).group(1).lower(), _KEY.match(line).group(2).strip()
            found[key] = value
        elif key and line.strip().startswith("- ") and not found[key].startswith("["):
            found[key] = ", ".join(filter(None, [found[key], line.strip()[2:].strip()]))
        elif key and found[key].startswith("[") and not found[key].endswith("]"):
            found[key] += " " + line.strip()
    return {name: value.strip("\"'") for name, value in found.items()}


def tags(value: str) -> list[str]:
    """`[context, sales]`, `context, sales`, or what a block list became."""
    return [tag.strip().strip("\"'") for tag in value.strip().strip("[]").split(",") if tag.strip().strip("\"'")]


def quoted(value: str) -> str:
    """A value from a page, as the pull request shows it: control and format characters out, no backtick, one line,
    at most QUOTED characters, in a code span."""
    text = "".join(" " if unicodedata.category(c)[0] in "CZ" else c for c in value if c != "`")
    text = " ".join(text.split())
    if len(text) > QUOTED:
        text = text[:QUOTED - 1] + "…"
    return f"`{text}`" if text else "`(empty)`"


def requirements(path: str, text: str) -> tuple[int, list[str], list[str]]:
    """(how many requirements, those without a `**Source:**` line, those whose source is an assumption)."""
    headings = [found.start() for found in _HEADING.finditer(text)]
    count, unsourced, assumed = 0, [], []
    for found in _REQUIREMENT.finditer(text):
        count += 1
        following = bisect.bisect_right(headings, found.start())
        block = text[found.end():headings[following] if following < len(headings) else len(text)]
        source = _SOURCE.search(block)
        name = f"{quoted(path)}: {quoted(found[1])}"
        if source is None:
            unsourced.append(name)
        elif source[1].strip("*_ ").lower().startswith("assumption"):
            assumed.append(name)
    return count, unsourced, assumed


def check(files: dict[str, str], vocabulary: list[str], unread: int = 0) -> dict:
    """The application's pages and requirements against decision 16 and the organization's vocabulary. With no
    vocabulary, a page carries its kind's tag alone, as the specialist is told."""
    allowed = set(KINDS) | set(vocabulary)
    report: dict = {"kinds": dict.fromkeys(KINDS, 0), "requirements": 0, "proposed": 0, "vocabulary": bool(vocabulary),
                    "outside": [], "mismatched": [], "unsourced": [], "assumed": [], "unread": unread}
    for path in sorted(files):
        text = files[path]
        if is_spec(path) or is_proposed_spec(path):
            count, unsourced, assumed = requirements(path, text)
            report["requirements" if is_spec(path) else "proposed"] += count
            report["unsourced"] += unsourced
            report["assumed"] += assumed
            continue
        if not is_page(path):
            continue
        meta = frontmatter(text)
        found = tags(meta.get("tags", "")) if meta else []
        own = [tag for tag in found if tag in KINDS]
        if not own:
            continue
        report["kinds"][own[0]] += 1
        if len(own) > 1 or meta.get("type") != KINDS[own[0]]:
            report["mismatched"].append(f"{quoted(path)} (type {quoted(meta.get('type', ''))}, "
                                        f"tags {', '.join(quoted(tag) for tag in own)})")
        strange = [tag for tag in found if not TAG.match(tag) or tag not in allowed]
        if strange:
            report["outside"].append(f"{quoted(path)} ({', '.join(quoted(tag) for tag in strange)})")
    return report


def _counted(number: int, word: str) -> str:
    return f"{number} {word}" + ("" if number == 1 else "s")


def _listed(items: list[str]) -> str:
    shown = "; ".join(items[:SHOWN])
    return shown + (f"; and {len(items) - SHOWN} more" if len(items) > SHOWN else "")


def lines(report: dict) -> list[str]:
    """The report for the pull request's checks: one line with the counts, and each finding below it."""
    pages = sum(report["kinds"].values())
    if not pages and not report["requirements"] and not report["proposed"] and not report["unread"]:
        return ["- Knowledge: no pages by kind and no requirements yet"]
    found = []
    if report["outside"]:
        what = "outside the organization's vocabulary" if report["vocabulary"] else \
            "beyond the kind's own (IT set no vocabulary)"
        found.append(f"  - tags {what}: {_listed(report['outside'])}")
    if report["mismatched"]:
        found.append(f"  - a kind's tag with another type, or two kinds on one page: {_listed(report['mismatched'])}")
    if report["unsourced"]:
        found.append(f"  - requirements without a source line: {_listed(report['unsourced'])}")
    if report["assumed"]:
        found.append(f"  - requirements built on an assumption, for IT to settle: {_listed(report['assumed'])}")
    if report["unread"]:
        found.append(f"  - {_counted(report['unread'], 'file')} not read: too large, or past the check's limit")
    kinds = ", ".join(f"{kind} {number}" for kind, number in report["kinds"].items())
    proposed = f" and {report['proposed']} in a change" if report["proposed"] else ""
    vocabulary = "the organization's vocabulary" if report["vocabulary"] else "no vocabulary set by IT"
    head = (f"- Knowledge: pages {kinds}; {_counted(report['requirements'], 'requirement')}{proposed}; {vocabulary}; "
            + ("**to look at**" if found else "nothing to look at"))
    return [head, *found]
