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
  - **WHEN** <situation, with concrete sample values from the mockups>
  - **THEN** <expected result>
  ```

  To change what already exists in `openspec/specs/<capability>/spec.md`, use `## MODIFIED Requirements` (the
  whole requirement, as it will read) or `## REMOVED Requirements`.
- `openspec/changes/<name>/tasks.md`: `## 1. <group>` with `- [ ] 1.1 <task>`; small tasks, each tied to the
  scenarios it makes pass; include the tests and the documentation.
- `design.md` only when there is a real technical decision to record; otherwise none.

The structure and its keywords (`Requirement`, `Scenario`, `WHEN`, `THEN`, `SHALL`, the headings) stay in English;
the content is in `docs_language`.

## Rules

- A requirement is one sentence; one to three scenarios each, with concrete values. Every scenario will be a test.
- A business rule cites its source. Without one, it goes to `## Open questions` in the proposal; never invent it.
- State the current decision only. When the user changes their mind, rewrite; add a one-line note only if the
  reason matters to whoever reviews.
- If a section adds nothing, remove it.

## With the user

Show the requirements as a plain table (requirement · example), not the files, and ask for confirmation. Then
`version_save(workspace, <message>)`.

## Done

Every requirement has a scenario, the user confirmed them, and open questions are listed.
