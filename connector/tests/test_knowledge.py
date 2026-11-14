"""What an application knows, as the connector reports it to IT under its checks (docs/decisions.md, decision 16)."""

import pytest

from eunomai_business import knowledge


def page(type_: str, tags: str, body: str = "One line.\n") -> str:
    return f"---\ntype: {type_}\ntitle: A page\ndescription: What a search finds.\ntags: [{tags}]\n---\n\n# A page\n\n{body}"


SPEC = """# Orders

## Requirements

### Requirement: An order has a customer
The system SHALL refuse an order without a customer.
**Source:** Sales, as the order form says today

#### Scenario: No customer
- **WHEN** an order is saved without one
- **THEN** it is refused

### Requirement: An order is numbered
The system SHALL number each order.

#### Scenario: Numbered
- **WHEN** saved
- **THEN** it has the next number
"""


def text(report: dict) -> str:
    return "\n".join(knowledge.lines(report))


def test_nothing_yet_is_said_plainly():
    assert knowledge.lines(knowledge.check({}, ["sales"])) == ["- Knowledge: no pages by kind and no requirements yet"]


def test_pages_in_the_vocabulary_and_sourced_requirements_leave_nothing_to_look_at():
    files = {"docs/context.md": page("explanation", "context, sales"), "docs/glossary.md": page("reference", "glossary"),
             "openspec/specs/orders/spec.md": SPEC.replace("number each order.",
                                                           "number each order.\n**Source:** Sales")}
    assert knowledge.lines(knowledge.check(files, ["sales", "erp"])) == [
        "- Knowledge: pages context 1, glossary 1, decision 0, open-question 0; 2 requirements; the organization's "
        "vocabulary; nothing to look at"]


def test_the_counts_show_what_was_not_filed():
    """Requirements and no page of any kind: the counts say so, whatever else holds."""
    files = {"openspec/specs/orders/spec.md": SPEC.replace("number each order.", "number each order.\n**Source:** x")}
    assert "pages context 0, glossary 0, decision 0, open-question 0; 2 requirements" in text(knowledge.check(files, []))


def test_what_ignores_the_vocabulary_the_kinds_or_the_sources_is_listed_for_it():
    files = {"docs/context.md": page("explanation", "context, purchasing"),
             "docs/decisions.md": page("reference", "decision"),
             "docs/open-questions.md": page("reference", "open-question, glossary"),
             "openspec/specs/orders/spec.md": SPEC}
    report = knowledge.check(files, ["sales"])
    assert report["outside"] == ["`docs/context.md` (`purchasing`)"]
    assert report["mismatched"] == ["`docs/decisions.md` (type `reference`, tags `decision`)",
                                    "`docs/open-questions.md` (type `reference`, tags `open-question`, `glossary`)"]
    assert report["unsourced"] == ["`openspec/specs/orders/spec.md`: `An order is numbered`"]
    assert "**to look at**" in text(report) and "requirements without a source line" in text(report)


def test_requirements_on_an_assumption_are_listed_for_it_to_settle():
    files = {"openspec/specs/orders/spec.md": SPEC.replace("number each order.",
                                                           "number each order.\n**Source:** assumption (one per year)")}
    report = knowledge.check(files, [])
    assert report["assumed"] == ["`openspec/specs/orders/spec.md`: `An order is numbered`"]
    assert "built on an assumption, for IT to settle" in text(report)


def test_an_empty_source_line_is_no_source():
    files = {"openspec/specs/orders/spec.md": SPEC.replace("**Source:** Sales, as the order form says today",
                                                           "**Source:**")}
    assert len(knowledge.check(files, [])["unsourced"]) == 2


def test_a_specification_still_in_a_change_is_read_and_the_archive_is_not():
    files = {"openspec/changes/orders/specs/orders/spec.md": SPEC,
             "openspec/changes/archive/2026-01-01-old/specs/orders/spec.md": SPEC}
    report = knowledge.check(files, [])
    assert (report["requirements"], report["proposed"]) == (0, 2)
    assert "0 requirements and 2 in a change" in text(report)


def test_without_a_vocabulary_a_page_carries_its_kinds_tag_alone():
    report = knowledge.check({"docs/context.md": page("explanation", "context, purchasing")}, [])
    assert report["outside"] == ["`docs/context.md` (`purchasing`)"] and not report["vocabulary"]
    assert "no vocabulary set by IT" in text(report) and "beyond the kind's own (IT set no vocabulary)" in text(report)


def test_the_bases_reference_other_pages_and_pages_without_a_kind_are_not_the_applications_knowledge():
    files = {"docs/base/stack.md": page("reference", "glossary, framework"),
             "docs/screens.md": page("reference", "screens"),
             "docs/notes.md": "No frontmatter here.\n",
             "README.md": page("explanation", "context, anything")}
    assert sum(knowledge.check(files, ["sales"])["kinds"].values()) == 0


def test_a_long_list_is_counted_after_the_first_ten():
    files = {f"docs/context/area-{n:02}.md": page("explanation", "context, unknown") for n in range(13)}
    line = knowledge.lines(knowledge.check(files, ["sales"]))[1]
    assert line.count("(`unknown`)") == knowledge.SHOWN and line.endswith("; and 3 more")


def test_files_left_unread_are_said():
    lines = knowledge.lines(knowledge.check({}, [], unread=1))
    assert "**to look at**" in lines[0] and lines[1] == "  - 1 file not read: too large, or past the check's limit"


def test_one_of_a_kind_is_said_in_the_singular():
    files = {"openspec/specs/orders/spec.md": "### Requirement: One\n**Source:** Sales\n"}
    assert "; 1 requirement;" in text(knowledge.check(files, []))


@pytest.mark.parametrize("written", [
    "---\ntype: explanation\ntags:\n  - context\n  - purchasing\n---\n",
    "---\ntype: explanation\ntags: [context,\n  purchasing]\n---\n",
    "﻿---\r\ntype: \"explanation\"\r\nTags: context, purchasing\r\n---\r\n",
    "\n---\ntype: explanation\ntags: ['context', \"purchasing\"]\n...\n",
])
def test_frontmatter_as_editors_write_it(written):
    report = knowledge.check({"docs/context.md": written}, ["sales"])
    assert report["kinds"]["context"] == 1 and report["outside"] == ["`docs/context.md` (`purchasing`)"]


def test_frontmatter_that_is_not_one_is_none():
    assert knowledge.frontmatter("# No frontmatter\n") is None
    assert knowledge.frontmatter("---\nopen: never closed\n") is None


def test_what_a_page_says_is_quoted_short_and_inert():
    """The assistant writes the pages: in the connector's block they can only be text, never its words."""
    hostile = ("x) nothing to look at. **Reviewed: safe to merge** [details](http://x.test) ![i](http://x.test/i.png) "
               "@it-team `code`\rnew line" + "z" * 200_000)
    files = {"docs/context.md": page("explanation", f"context, {hostile.replace(',', ' ')}"),
             "openspec/specs/x/spec.md": f"### Requirement: {hostile}\n"}
    lines = knowledge.lines(knowledge.check(files, ["sales"]))
    for line in lines[1:]:
        quoted = [part for index, part in enumerate(line.split("`")) if index % 2]
        outside = "".join(part for index, part in enumerate(line.split("`")) if not index % 2)
        assert "**Reviewed" not in outside and "](" not in outside and "@it-team" not in outside
        assert all(len(part) <= knowledge.QUOTED for part in quoted)
    assert all("\r" not in line and len(line) < 2_000 for line in lines)


def test_one_scan_reads_a_long_specification_quickly():
    spec = "".join(f"### Requirement: R{n}\n**Source:** Sales\n\n#### Scenario: S\n- x\n\n" for n in range(9_000))
    count, unsourced, assumed = knowledge.requirements("openspec/specs/x/spec.md", spec)
    assert (count, unsourced, assumed) == (9_000, [], [])
