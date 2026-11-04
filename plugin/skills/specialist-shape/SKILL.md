---
name: specialist-shape
description: Stage 2, Shape, of the {{PLUGIN}} specialist: the first real screens, or a clickable prototype where code is not allowed, approved by the user. Load it only when the specialist skill reaches this stage; it is not a starting point on its own.
---

# 2 · Shape

Goal: the user tries what they will see and do early, while changing it costs little. Say why once, in one line:
trying it first avoids building the wrong thing.

| The project | What they try |
|---|---|
| Allows code, with `preview.available` or a `test` environment in `specialist_settings` | The first real screens, in `app_preview` or the test environment |
| Allows code, with neither | The first real screens as screenshots from the sandbox, as images. If the sandbox cannot take them, say plainly they will see it at review, and agree on the flow and the sample data instead |
| Does not allow code | A clickable prototype |

## The first real screens

Build them before tests and the full specification: the point is to agree on the real thing early.

- On the project's own base: its layout, components and theme, never a separate page.
- Only the screens and the main path needed to agree. An unfinished screen is not polished: no edge cases, no
  refinements, nothing the user has not asked to see. Time spent here on what may change is wasted.
- Example data the application holds itself: roles and invented names, never real personal data. Say plainly that
  it is example data.
- Dependencies as in `specialist-build`: `dependency_check`, the whole tree pinned, `dependency_audit` allowed. Neither
  `app_preview` nor the send works without them.
- `version_save(workspace, <message>)`, then show them as `specialist-build` says, one way at a time.

## A clickable prototype

Only where the project does not allow code: one self-contained HTML file,
`openspec/changes/<name>/prototype/index.html`, with inline styles and scripts, where the main buttons and links work
on sample data held in the page (nothing is saved, nothing is sent anywhere). It shows each profile's screens and the
main path through them.

- Realistic but fictitious data: roles and invented names, never real personal data.
- The organization's look, through the skills `specialist_settings` lists for it, but no external resources:
  system fonts or none, no CDN, no web fonts, no images from other sites. The page says so itself, first thing in
  its `<head>` (a save without it is refused):
  `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:">`
- Say plainly, on the page and in the conversation, that it is a prototype with sample data.
- Tell the user the file to open in their browser. It is a page, not a program: nothing to install or run.

## With either

- **The flow:** a Mermaid flowchart of what the user does, step by step, shown in the conversation, when the path
  has more than a few steps.
- **Sample data:** a small table of the information the application keeps or shows.

## Iterating

- Ask what to change, one point at a time, each with a suggested answer.
- When something is agreed, update the screens or the prototype and `proposal.md` (replace the text; keep no history).

## Done

The user approves what they tried. It becomes the contract for Build: what it shows is built, or the difference is
agreed and noted. List the screens agreed under `## Agreed screens` in `proposal.md`, one line each. Then
`version_save(workspace, <message>)` and move on to Specify.
