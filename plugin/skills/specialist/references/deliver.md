# 5 · Deliver

Goal: a pull request a reviewer can judge quickly, where anything not settled is visible.

## Readiness check

Each line holds, or goes into the summary under *Not settled* or *Skipped*:

- every requirement has a scenario, and every scenario a passing test;
- assumptions confirmed by the user; open questions listed;
- every dependency allowed by `dependency_check`, pinned;
- the project's documentation updated (how to use it, how to run it);
- no secrets, no dead code, no debugging leftovers.

## Archive the change, in this same version

1. Fold the change's specs into `openspec/specs/<capability>/spec.md`. A new file starts with
   `# <capability> Specification`, `## Purpose` (one or two sentences) and `## Requirements`. Append `ADDED`
   requirements under `## Requirements`, replace `MODIFIED` ones by name, delete `REMOVED` ones.
2. Move `openspec/changes/<name>/` to `openspec/changes/archive/<YYYY-MM-DD>-<name>/`, mockups included.
3. `version_save(workspace, <message>)`.

## Propose

`version_send(workspace)`, then `version_propose(workspace, <title>, <summary>)`. The summary, in
`docs_language`, has these sections, each short:

| Section | Content |
|---|---|
| Goal | What the user wanted, in two lines |
| Built | What changed, mapped to the requirements |
| Evidence | The test of each scenario and its result |
| Not settled | Assumptions not confirmed, rules without a source, open questions |
| Skipped | What was not built or not validated, and why |
| Course changes | Only those that matter to the reviewer, one line each |

## With the user

One line: it was sent for review, and what happens next. When they come back after the review,
`workspace_update` brings the result, and you suggest the next step.
