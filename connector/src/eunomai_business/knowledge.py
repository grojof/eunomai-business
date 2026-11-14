"""What an application knows, as IT reads it in a pull request: its pages by kind and tag, and its requirements with
their source (docs/decisions.md, decision 16). A report, never a refusal: the work is the person's, the review is IT's.

The pages are read from the commit the server holds, never from the folder."""

import re

KINDS = {"context": "explanation", "glossary": "reference", "decision": "decision", "open-question": "reference"}
"""Each kind's tag and the `type` its pages carry. Always allowed, whatever the organization's vocabulary says."""

TAG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHOWN = 10
"""Entries listed per finding in a pull request; the rest are counted."""

_REQUIREMENT = re.compile(r"^### Requirement:\s*(.+?)\s*$", re.MULTILINE)
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_SOURCE = re.compile(r"^\*\*Source:\*\*\s*\S", re.MULTILINE)


def is_page(path: str) -> bool:
    """A page of the application's own knowledge: under docs/, not the base's reference in docs/base/."""
    return path.startswith("docs/") and not path.startswith("docs/base/") and path.endswith(".md")


def is_spec(path: str) -> bool:
    return path.startswith("openspec/specs/") and path.endswith(".md")


def frontmatter(text: str) -> dict[str, str] | None:
    """The page's frontmatter as plain `key: value` lines, or None without one. Only what the check reads: the keys
    the specialist writes on one line each."""
    text = text.lstrip("﻿")
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None
    end = re.search(r"^---\s*$", text[4:], re.MULTILINE)
    if end is None:
        return None
    found = {}
    for line in text[4:4 + end.start()].splitlines():
        key, colon, value = line.partition(":")
        if colon and key.strip() and not key.startswith((" ", "\t", "#")):
            found[key.strip()] = value.strip().strip("\"'")
    return found


def tags(value: str) -> list[str]:
    """`[context, sales]` or `context, sales`, as written on one line."""
    return [tag.strip().strip("\"'") for tag in value.strip().strip("[]").split(",") if tag.strip()]


def requirements_without_source(path: str, text: str) -> list[str]:
    """The requirements of a spec whose block has no `**Source:**` line."""
    missing = []
    for found in _REQUIREMENT.finditer(text):
        rest = text[found.end():]
        following = _NEXT_HEADING.search(rest)
        block = rest[:following.start()] if following else rest
        if not _SOURCE.search(block):
            missing.append(f"{path}: {found[1]}")
    return missing


def check(files: dict[str, str], vocabulary: list[str]) -> dict:
    """The application's pages and requirements against decision 16 and the organization's vocabulary (empty: no
    vocabulary, so any well-formed tag)."""
    allowed = set(KINDS) | set(vocabulary)
    pages = requirements = 0
    outside: list[str] = []
    kinds: list[str] = []
    unsourced: list[str] = []
    for path in sorted(files):
        text = files[path]
        if is_spec(path):
            requirements += len(_REQUIREMENT.findall(text))
            unsourced += requirements_without_source(path, text)
            continue
        if not is_page(path):
            continue
        meta = frontmatter(text)
        if meta is None or "tags" not in meta:
            continue
        found = tags(meta["tags"])
        own = [tag for tag in found if tag in KINDS]
        if not own:
            continue
        pages += 1
        if len(own) > 1 or meta.get("type") != KINDS[own[0]]:
            kinds.append(f"{path} (type {meta.get('type') or 'missing'}, tags {', '.join(own)})")
        strange = [tag for tag in found if not TAG.match(tag) or (vocabulary and tag not in allowed)]
        if strange:
            outside.append(f"{path} ({', '.join(strange)})")
    return {"pages": pages, "requirements": requirements, "vocabulary": bool(vocabulary), "outside": outside,
            "kinds": kinds, "unsourced": unsourced}


def _listed(items: list[str]) -> str:
    shown = "; ".join(items[:SHOWN])
    return shown + (f"; and {len(items) - SHOWN} more" if len(items) > SHOWN else "")


def lines(report: dict) -> list[str]:
    """The report for the pull request's checks, one line and its findings."""
    if not report["pages"] and not report["requirements"]:
        return ["- Knowledge: no pages by kind and no requirements yet"]
    found = []
    if report["outside"]:
        what = "outside the organization's vocabulary" if report["vocabulary"] else "not lowercase words joined by -"
        found.append(f"  - tags {what}: {_listed(report['outside'])}")
    if report["kinds"]:
        found.append(f"  - a kind's tag with another type, or two kinds on one page: {_listed(report['kinds'])}")
    if report["unsourced"]:
        found.append(f"  - requirements without a **Source:** line: {_listed(report['unsourced'])}")
    vocabulary = "the organization's vocabulary" if report["vocabulary"] else "no vocabulary set by IT"
    head = (f"- Knowledge: {report['pages']} pages by kind, {report['requirements']} requirements; {vocabulary}; "
            + ("**to look at**" if found else "nothing to look at"))
    return [head, *found]
