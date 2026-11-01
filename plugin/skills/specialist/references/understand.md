# 1 · Understand

Goal: know what problem this solves, for whom, how it is done today and what result counts as success, in the
user's own words, before proposing anything.

## Method

1. **Look before you ask.** Read the project's context, the organization's context and what the workspace already
   holds (`openspec/specs/`, the README). Do not ask what they already answer.
2. **Restate the idea in one sentence**, then ask what is still missing, one question at a time, each as a choice
   in the user's words with your recommendation first: who will use it, how it is done today, what result they
   expect. If a question puzzles them, explain it in other words and recommend an answer; they choose.
3. **Sort what you hear** into three kinds and keep them apart:
   - facts the user knows;
   - business rules, which need a source (a document, a role, a regulation);
   - your assumptions, which the user must confirm.
4. **Question the idea when it may be the wrong one.** Ask what problem it solves. If something simpler solves it
   better (a system the organization's context names, a smaller first version), propose it in one line.
5. **Show "what I understood"** as a table, then ask for confirmation:

   | | |
   |---|---|
   | Goal | ... |
   | Users | ... |
   | Today | ... |
   | Expected result | ... |
   | Out of scope | ... |
   | Assumptions to confirm | ... |
   | Open questions | ... |

6. **Propose a roadmap** of three to six steps, the smallest useful first version first.

## When the user confirms

1. On the main branch, `version_create(workspace, <name>)`: a short name from the goal, lowercase ASCII with
   hyphens, in `docs_language` (for example `alta-de-pedidos`). Already on a version (one saved automatically, for
   example): keep working on it.
2. Create the change: `openspec/changes/<name>/.openspec.yaml` with `schema: spec-driven` and
   `created: <YYYY-MM-DD>`, and `openspec/changes/<name>/proposal.md` with `## Why`, `## What Changes` and
   `## Impact` (headings in English, content in `docs_language`). It fits on one screen. Add
   `## Open questions` only if there are any. What is in this version and what is left for later is stated once,
   in `## What Changes`, and kept true until delivery.
3. `version_save(workspace, <one-line message>)`.
4. Tell the user what comes next in one line: something to try before anything is built.
