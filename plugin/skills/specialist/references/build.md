# 4 · Build

Only when `specialist_settings` allows code in this workspace, and only with its technologies.

## Before writing code

- **Choose the simplest structure** that meets the specification, within the allowed technologies. Check every
  technical choice in the official documentation; cite it where the choice is not obvious.
- **Every package through `dependency_check`.** Use the exact version it allows and pin it (a lockfile, or `==`
  in requirements). If it blocks a package, choose another or do without; never insist.

## Tests first

- One test per scenario, named after it, with the scenario's values. Write it, see it fail, then make it pass.
- Run the tests in your shell. If they cannot run here, say so and record it for the reviewer as not validated.
- No tests that check nothing (everything mocked, assertions that cannot fail).

## Code

- Only what the specification asks for: no speculative features, no dead or commented-out code, no debugging
  leftovers.
- Identifiers and comments in `code_language`; technical terms and each language's conventions stay as they are.
- Secure by default: validate input at the edges, parameterized queries, no secrets in code, least privilege.
- A short `README.md` section on how to run it and how to run the tests.

## Progress

- After each task: tick it in `tasks.md` and `version_save(workspace, <message>)`.
- Show the user the roadmap moving, and how to see it working, in one or two lines.
- Something unclear means going back to Specify and asking; never guess.

## Done

Every task is ticked and every scenario has a passing test.
