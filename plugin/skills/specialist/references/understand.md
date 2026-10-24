# 1 · Understand

Goal: know what problem this solves, for whom, how it is done today and what result counts as success, in the
user's own words, before proposing anything.

## Method

1. **Restate the idea in one sentence** and ask up to three questions, each with a suggested answer: who will use
   it, how it is done today, what result they expect.
2. **Sort what you hear** into three kinds and keep them apart:
   - facts the user knows;
   - business rules, which need a source (a document, a role, a regulation);
   - your assumptions, which the user must confirm.
3. **Question the idea when it may be the wrong one.** Ask what problem it solves. If something simpler solves it
   better (an existing tool, a smaller first version), propose it in one line.
4. **Show "what I understood"** as a table, then ask for confirmation:

   | | |
   |---|---|
   | Goal | ... |
   | Users | ... |
   | Today | ... |
   | Expected result | ... |
   | Out of scope | ... |
   | Assumptions to confirm | ... |
   | Open questions | ... |

5. **Propose a roadmap** of three to six steps, the smallest useful first version first.

## When the user confirms

1. On the main branch, `version_create(workspace, <name>)`: a short name from the goal, lowercase ASCII with
   hyphens, in `docs_language` (for example `alta-de-pedidos`). Already on a version (one saved automatically, for
   example): keep working on it.
2. Create the change: `openspec/changes/<name>/.openspec.yaml` with `schema: spec-driven` and
   `created: <YYYY-MM-DD>`, and `openspec/changes/<name>/proposal.md` with `## Why`, `## What Changes` and
   `## Impact` (headings in English, content in `docs_language`). It fits on one screen. Add
   `## Open questions` only if there are any.
3. `version_save(workspace, <one-line message>)`.
4. Tell the user what comes next in one line: something to see before anything is built.
