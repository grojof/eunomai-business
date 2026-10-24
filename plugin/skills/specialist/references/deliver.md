# 5 · Deliver

Goal: a pull request a reviewer can judge quickly, where anything not settled is visible.

## Readiness check

Run it now, not from memory. Each line holds, or goes into the summary under *Not settled* or *Skipped*:

- the whole test suite passes in a run made now; every requirement has a scenario, and every scenario a test;
- `dependency_audit(workspace)` answers `allowed`;
- review your own changes with two lenses, as a reviewer would: does it do what the specs say, no more and no less;
  and does it meet the table in `build.md`. If the organization provides a code or security review skill, run it
  too;
- the README, `design.md` and the proposal say what the code does (scope, settings, how to run it), nothing more;
- the application matches the approved prototype, or the differences are agreed;
- assumptions confirmed by the user; open questions listed;
- no secrets, no external resources, no dead code, no debugging leftovers, nothing meant to run on the user's
  computer.

## Archive the change, in this same version

1. Fold the change's specs into `openspec/specs/<capability>/spec.md`. A new file starts with
   `# <capability> Specification`, `## Purpose` (one or two sentences) and `## Requirements`. Append `ADDED`
   requirements under `## Requirements`, replace `MODIFIED` ones by name, delete `REMOVED` ones.
2. Move `openspec/changes/<name>/` to `openspec/changes/archive/<YYYY-MM-DD>-<name>/`, prototype included, and fix
   any link that pointed to the old place.
3. `version_save(workspace, <message>)`.

## Propose

`version_send(workspace)`, then `version_propose(workspace, <title>, <summary>)`. If it answers `created: false`,
the proposal was already open and the version just sent updates it. The summary, in `docs_language`, has these
sections, each short:

| Section | Content |
|---|---|
| Goal | What the user wanted, in two lines |
| Built | What changed, mapped to the requirements |
| Evidence | The test of each scenario and its result, from the run made now; the dependency audit |
| Not settled | Assumptions not confirmed, rules without a source, open questions |
| Skipped | What was not built or not validated, and why |
| Help used | Skills used besides this one, and any conflict with these rules and how it was resolved |
| For the project's context | Only if the project has none or it fell short: the lines IT could add |
| Course changes | Only those that matter to the reviewer, one line each |

## With the user

One line: it was sent for review, and what happens next. When they come back after the review,
`workspace_update` brings the result, and you suggest the next step.
