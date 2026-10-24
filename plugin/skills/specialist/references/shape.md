# 2 · Shape

Goal: agree on what the user will see and do, before anything is built. Say why once, in one line: seeing it
first avoids building the wrong thing.

## What to produce

- **Mockups of the screens:** one self-contained HTML file per set of screens in
  `openspec/changes/<name>/mockups/`, with inline styles, no external resources, and realistic but fictitious
  sample data (never real personal data). Tell the user the file to open.
- **The flow:** a Mermaid flowchart of what the user does, step by step, shown in the conversation.
- **Sample data:** a small table of the information the application keeps or shows.

## Iterating

- Ask what to change, at most three points per round, each with a suggested answer.
- When something is agreed, update the proposal (replace the text; keep no history).
- Keep the mockups simple: layout and content, not styling.

## Done

The user approves what they see. Then `version_save(workspace, <message>)` and move on to Specify.
