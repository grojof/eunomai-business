"""What an application knows, as the connector reports it to IT under its checks (docs/decisions.md, decision 16)."""

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


def test_nothing_yet_is_said_plainly():
    assert knowledge.lines(knowledge.check({}, ["sales"])) == ["- Knowledge: no pages by kind and no requirements yet"]


def test_pages_in_the_vocabulary_and_sourced_requirements_leave_nothing_to_look_at():
    files = {"docs/context.md": page("explanation", "context, sales"), "docs/glossary.md": page("reference", "glossary"),
             "openspec/specs/orders/spec.md": SPEC.replace("number each order.", "number each order.\n**Source:** "
                                                           "assumption")}
    report = knowledge.check(files, ["sales", "erp"])
    assert (report["pages"], report["requirements"]) == (2, 2)
    assert knowledge.lines(report) == ["- Knowledge: 2 pages by kind, 2 requirements; the organization's vocabulary; "
                                       "nothing to look at"]


def test_what_ignores_the_vocabulary_the_kinds_or_the_sources_is_listed_for_it():
    files = {"docs/context.md": page("explanation", "context, purchasing"),
             "docs/decisions.md": page("reference", "decision"),
             "docs/open-questions.md": page("reference", "open-question, glossary"),
             "openspec/specs/orders/spec.md": SPEC}
    report = knowledge.check(files, ["sales"])
    assert report["outside"] == ["docs/context.md (purchasing)"]
    assert report["kinds"] == ["docs/decisions.md (type reference, tags decision)",
                               "docs/open-questions.md (type reference, tags open-question, glossary)"]
    assert report["unsourced"] == ["openspec/specs/orders/spec.md: An order is numbered"]
    text = "\n".join(knowledge.lines(report))
    assert "**to look at**" in text and "outside the organization's vocabulary: docs/context.md (purchasing)" in text
    assert "without a **Source:** line: openspec/specs/orders/spec.md: An order is numbered" in text


def test_without_a_vocabulary_any_well_formed_tag_is_the_organizations_choice():
    files = {"docs/context.md": page("explanation", "context, purchasing, Bad Tag")}
    report = knowledge.check(files, [])
    assert report["outside"] == ["docs/context.md (Bad Tag)"] and not report["vocabulary"]
    assert "no vocabulary set by IT" in knowledge.lines(report)[0]
    assert "not lowercase words joined by -" in knowledge.lines(report)[1]


def test_the_bases_reference_other_pages_and_pages_without_a_kind_are_not_the_applications_knowledge():
    files = {"docs/base/stack.md": page("reference", "glossary, framework"),
             "docs/screens.md": page("reference", "screens"),
             "docs/notes.md": "No frontmatter here.\n",
             "README.md": page("explanation", "context, anything")}
    assert knowledge.check(files, ["sales"])["pages"] == 0


def test_a_long_list_is_counted_after_the_first_ten():
    files = {f"docs/context/area-{n:02}.md": page("explanation", "context, unknown") for n in range(13)}
    line = knowledge.lines(knowledge.check(files, ["sales"]))[1]
    assert line.count("(unknown)") == knowledge.SHOWN and line.endswith("; and 3 more")


def test_frontmatter_tolerates_what_editors_write():
    text = '﻿---\r\ntype: "explanation"\r\ntags: context, sales\r\n---\r\n'
    meta = knowledge.frontmatter(text)
    assert meta is not None and meta["type"] == "explanation" and knowledge.tags(meta["tags"]) == ["context", "sales"]
    assert knowledge.frontmatter("# No frontmatter\n") is None and knowledge.frontmatter("---\nopen: never closed\n") is None
