---
name: specialist-understand
description: Stage 1, Understand, of the eunomai-business specialist: know the problem, the users, how it is done today and the expected result, and confirm "what I understood"; with no project yet, prepare the request for IT. Load it only when the specialist skill reaches this stage; it is not a starting point on its own.
---

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
4. Tell the user what comes next in one line: something to try early.

## Without a project

When the person wants a new application and no project exists for it (none in `workspace_list`, and no address from
IT):

1. Say in one line that IT creates new projects, and that you start by understanding the idea now so nothing waits.
   Never offer to create a repository.
2. Follow the method above in conversation, with no repository and no files written, not even in the task's folder:
   goal, users, how it is done today, what the first version includes, open questions.
3. When they confirm "what I understood", suggest a name for the project from the goal (lowercase ASCII with
   hyphens, in `docs_language`) and say IT decides it. Then call `project_request` with that `name` and their words:
   `purpose`, `users`, `today`, `first_version`, `out_of_scope`, `open_questions`.
4. Show its `user_message`, in one or two lines: the request is on a page in their browser, with a button that
   copies it and another that opens the e-mail to IT. When `opened` is false, give them `page` as a link. Never write
   the request or an e-mail link yourself: the page holds the whole message, and a retyped one can come out shorter.
   Say plainly that nothing is sent until they send it. Ask nothing else of them for IT.
5. Stop there: the work goes on once the project exists.

## When IT has created the project

`workspace_list` lists the request under `project_requests` until it is done. When the person says the project
exists, in this task or a new one:

1. `workspace_clone` it (ask for the address IT gave them only if they did not say it), request its folder, and take
   steps 3 and 4 of the start of a session.
2. On the main branch, `version_create(workspace, <the request's name>)`, and create the change as in *When the user
   confirms*, step 2, from the request: `## Why` from `purpose`, `users` and `today`; `## What Changes` from
   `first_version` and `out_of_scope`; `## Open questions` from `open_questions`. Understand is not asked again: show
   the summary as one table and ask only whether anything changed.
3. `version_save(workspace, <one-line message>)`.
4. `project_request_done` with the request and the workspace: the request is kept, marked done, and no longer listed.
5. Carry on with something to try early.
