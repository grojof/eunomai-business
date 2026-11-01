# 4 · Build

Only when `specialist_settings` allows code in this workspace, and only with its technologies. Everything runs in
your sandbox.

## Before writing code

- **Choose the simplest structure** that meets the specification, within the allowed technologies. Check every
  technical choice in the official documentation; cite it where the choice is not obvious.
- **Every direct package through `dependency_check`.** Use the version it allows. If it blocks the version asked
  for, use the `recommended` one it returns, if any; if it blocks the package, choose another or do without; never
  insist.
- **Pin the whole tree, for every computer.** Python: the direct packages in `requirements.in`, and the
  development ones in `requirements-dev.in` starting with `-c requirements.txt`. Then, in the sandbox, for each:
  `uv pip compile <file>.in --universal --generate-hashes --python-version <version> --exclude-newer "14 days"
  -o <file>.txt` ([`uv pip compile`](https://docs.astral.sh/uv/reference/cli/#uv-pip-compile),
  [universal resolution](https://docs.astral.sh/uv/concepts/resolution/#universal-resolution); uv itself through
  `dependency_check`). `<version>` is the Python IT runs, from the project's context or the allowed technologies;
  if neither says, the sandbox's, and the question goes under *Not settled*. The list holds every package, direct
  and indirect, at its exact version, with its hashes and the markers of the platforms that need it; `pip freeze`
  lists only what the sandbox (Linux) installed, and fails on Windows. A project that already locks with `uv.lock`
  keeps it and runs `uv lock`. JavaScript: `package-lock.json`. Files kept in the project's own tree: `vendor.json`.
- Then `dependency_audit(workspace)`: its `verdict` must be `allowed`. If it blocks a version, pin the
  `recommended` one from `dependency_check` in the `.in` file (newer than two weeks only when it fixes a
  vulnerability: add `--exclude-newer-package <name>=<YYYY-MM-DD of today>`) and compile again. A package it blocks that the
  tooling needs, such as an indirect one without recent releases, goes to IT, who can vet it once for the
  organization: the connector refuses to send until then, so say so early, not at delivery. Repeat after any
  dependency change.
- **Open questions:** declared assumptions, as `SKILL.md` says; never a setting the code does not have.

## Tests first

- One test per scenario, named after it, with the scenario's values and its exact texts. Write it, run it, see it
  fail; then write the code that makes it pass. Screens agreed in Shape are a start, not finished work: they get
  their tests here like any code, and a test that passes at once proves nothing until you have broken the screen
  and seen it fail.
- **A test never moves to meet the code.** If they disagree, the code changes, or the scenario goes back to
  Specify and the user decides.
- For each important rule, break the code for a moment, see its test fail, restore the code and run it again: a
  test that cannot fail proves nothing.
- No tests that check nothing (everything mocked, assertions that cannot fail).

## Code

- Only what the specification asks for: no speculative features, no dead or commented-out code, no debugging
  leftovers.
- Identifiers and comments in `code_language`; technical terms and each language's conventions stay as they are.
- What reviewers of business applications ask for first:

| Topic | In practice |
|---|---|
| Identity | Users are matched by the identity provider's stable identifiers (`sub`, or `oid` and `tid` in Entra ID), never by e-mail; the expected tenant or issuer is checked |
| Authorization | Checked on the server for every action and every record, not only by hiding buttons |
| Forms with cookie sessions | Protection against cross-site requests (a token, or a check of `Origin`); signing out by POST |
| The same action twice | A double click or two requests at once cannot break a limit (a constraint or a lock, and its test) |
| Input | Validated at the edges, with limits on size and range; queries parameterized |
| Secrets and settings | From the environment. Production is the default: development or demonstration only when set explicitly, and the application refuses to start with them in production. Secrets with a minimum strength; sessions with a limited lifetime |
| Separation of duties | Nobody decides on their own record (approves their own request, signs off their own work), whatever the data says, for example someone loaded as their own manager |
| External resources | None: fonts, scripts and styles are served by the application |
| Errors | A clear message to the user, never a raw error page; no tokens or personal data in logs. "Not found" and "not allowed" answer alike |

- A short `README.md` section on how IT runs it and runs the tests, true to the code. A page in `docs/` starts with
  frontmatter: `type` (one of `tutorial`, `how-to`, `reference`, `explanation`, `decision`, in English), `title` and
  `description`; it describes only what the code does.

## Progress

- **One task, one save:** tick it in `tasks.md` and `version_save(workspace, <message>)`, with its tests and code
  together. IT follows the build save by save; one save for the whole application cannot be reviewed.
- Show the user the roadmap moving in one or two lines. Show them the application the first way that exists: on
  their computer, in the test environment (both below), or through screenshots taken in the sandbox, as images,
  saying they are pictures. If the sandbox cannot take one, say so: never a saved copy of the application's pages,
  which looks usable and is not. Never a launcher for their computer.
- **On the person's computer,** when `specialist_settings` returns `preview.available` true. It runs what is saved,
  so save first. Say first, in one plain sentence, what will happen: what was built so far will start on their
  computer, with their permissions, nobody has reviewed it yet, and it keeps running until they say stop or the hour
  ends, even if they close Claude. Wait for their yes. Then `app_preview(workspace)`; while it says `starting`, call it
  again. With `ready`, show `user_message`, in every turn it is asked for: the same version answers the one running,
  with the time it has left. Any other answer: show `user_message`, and do not offer it again in this task.
  `app_preview_stop(workspace)` when they say stop, whichever task started it, and show what it says: only `stopped`
  means it stopped. If `unsaved_changes` is true, what they see lacks the latest changes: say so.
- **The project's test environment,** when `specialist_settings` returns `test`: after a save whose tests pass,
  offer in one line to try it there. On yes, `version_to_test(workspace)`; with `sent`, give its `url` and say it
  takes a few minutes and replaces what was being tried. `not_saved` and `behind_main` say what to do first.
  `not_allowed`, `refused`, `no_test_environment` or an `error` mean it is not available now: give its
  `user_message` (or say so in one line), and do not offer it again in this task. `audit_refused` and
  `audit_unavailable` are as in `deliver.md`. It never replaces Deliver: production always takes IT's review.
- Something unclear means going back to Specify and asking; never guess.

## Done

Every task is ticked, every scenario has a passing test, and you have just run the whole suite and the
application's main paths in the sandbox: quote the result.
