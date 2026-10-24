# 2 · Shape

Goal: the user tries what they will see and do, before anything is built. Say why once, in one line: trying it
first avoids building the wrong thing.

## What to produce

- **A clickable prototype:** one self-contained HTML file, `openspec/changes/<name>/prototype/index.html`, with
  inline styles and scripts, where the main buttons and links work on sample data held in the page (nothing is
  saved, nothing is sent anywhere). It shows each profile's screens and the main path through them.
  - Realistic but fictitious data: roles and invented names, never real personal data.
  - The organization's look, through the skills `specialist_settings` lists for it, but no external resources:
    system fonts or none, no CDN, no web fonts, no images from other sites. The page says so itself, first thing in
    its `<head>` (a save without it is refused):
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:">`
  - Say plainly, on the page and in the conversation, that it is a prototype with sample data.
  - Tell the user the file to open in their browser. It is a page, not a program: nothing to install or run.
- **The flow:** a Mermaid flowchart of what the user does, step by step, shown in the conversation, when the path
  has more than a few steps.
- **Sample data:** a small table of the information the application keeps or shows.

## Iterating

- Ask what to change, one point at a time, each with a suggested answer.
- When something is agreed, update the prototype and `proposal.md` (replace the text; keep no history).

## Done

The user approves the prototype. It becomes the contract for Build: what it shows is built, or the difference
is agreed and noted. Then `version_save(workspace, <message>)` and move on to Specify.
