# 3 · Specify

Goal: requirements and examples precise enough to become tests, short enough to read in a few minutes. Write
OpenSpec files directly, exactly in this format; no command-line tool is needed.

## Files

- `openspec/changes/<name>/specs/<capability>/spec.md`, one per capability (a short noun, lowercase ASCII with
  hyphens):

  ```markdown
  ## ADDED Requirements

  ### Requirement: <name>
  The system SHALL <one sentence>.

  #### Scenario: <name>
  - **WHEN** <situation, with concrete sample values from the prototype>
  - **THEN** <expected result, with the exact text the user will see when it matters>
  ```

  To change what already exists in `openspec/specs/<capability>/spec.md`, use `## MODIFIED Requirements` (the
  whole requirement, as it will read) or `## REMOVED Requirements` (each with a `**Reason**:` line).
- `openspec/changes/<name>/tasks.md`: `## 1. <group>` with `- [ ] 1.1 <task>`; small tasks, each tied to the
  scenarios it makes pass; include the tests and the documentation.
- `design.md` only when there is a real technical decision to record; otherwise none.

The structure and its keywords (`Requirement`, `Scenario`, `WHEN`, `THEN`, `SHALL`, the headings) stay in English;
the content is in `docs_language`.

## Rules

- A requirement is one sentence; one to three scenarios each, with concrete values. Every scenario will be a test.
- Cover the edges a reviewer will ask about (who may do it and who may not, nobody on their own record, wrong or
  missing input, limits, the same action twice) as scenarios, or as requirements of their own when a requirement
  would pass three.
- A business rule cites its source. Without one, it goes to `## Open questions` in `proposal.md`; never invent it.
- State the current decision only. When the user changes their mind, rewrite; add a one-line note only if the
  reason matters to whoever reviews.
- If a section adds nothing, remove it.

## Before showing it: do the pieces agree?

Read `proposal.md`, the prototype (if there is one), the specs and the tasks side by side. Every screen and
button in the prototype has a requirement; every requirement has a task; the scope in `## What Changes` matches;
no requirement answers an open question; nothing contradicts the project's context. Fix what does not agree before the user sees it.

## With the user

Show the requirements as a plain table (requirement · example), not the files, and ask for confirmation. Then
`version_save(workspace, <message>)`.

## Done

Every requirement has a scenario, the pieces agree, the user confirmed them, and open questions are listed.
