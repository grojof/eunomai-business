---
name: validate-setup
description: Validate an eunomai-business installation (where the local connector and hooks run, reachability of internal hosts, sign-in with every provider) and report the results as a table. Only present in builds with diagnostics enabled. Use when the user asks to validate the setup, run the eunomai checks, or test the connector.
---

# Validate the setup

Run the checks in this order with the `eunomai-business` connector tools. Do not change anything else and never
print tokens. If a tool is missing, say so: that is a result too (the connector did not start). Reply in the
language the user writes in; keep tool names, hypothesis numbers and error texts as they are.

1. `diag_environment` — note host, OS, user, `expansion_ok`, `providers`, `client_roots`, `client_protocol`.
2. `diag_reach` for each URL the user gives (ask for them if none were given). Note `resolves_to`,
   `system_store` and `bundled_store`.
3. For **each** provider in `providers`, one at a time: `whoami(provider)`. If not signed in:
   `sign_in_start(provider)`, tell the user to complete the sign-in in the browser, then call
   `sign_in_status(provider)` until it is no longer `waiting` (at most a few times; ask the user before
   retrying further). Note `stored_bytes` and `token_bytes` (sizes only) and any error text verbatim.
4. `whoami(provider)` again for each provider, to confirm the stored sign-in works.
5. `diag_hook_log` — say whether hook lines exist, on which host and with which shell. If the session context
   contains a line starting with `[eunomai-business] SessionStart hook ran`, quote it.
6. Guard probe (H9). None of these files exist; the point is whether a hook stops the tool first:
   a. with your file-reading tool, read `eunomai-guard-test-json.txt`;
   b. with your shell, run `cat eunomai-guard-test-exit2.txt`;
   c. with your file-reading tool, read `eunomai-guard-control.txt` (control: expect "not found", not a block).
   For each, report whether the tool was blocked by a hook and the exact message you saw. Then
   `diag_hook_log(15)`: for those calls note `guard`, `input_keys`, `launch_ms` and `hook_ms`, and give the range
   of `launch_ms` over all PreToolUse lines.

## The hypotheses (use these exact numbers and names)

| # | Hypothesis | Settled by |
|---|---|---|
| H1 | The plugin's local connector runs on the host computer, not in a sandbox VM | step 1: host and OS |
| H2 | It reaches internal HTTPS hosts and trusts the internal CA through the OS certificate store | step 2 |
| H3 | It starts with no per-user setup: `uv` found, `${CLAUDE_PLUGIN_ROOT}` expanded, the locked packages installed | the tools exist; `expansion_ok` |
| H4 | Sign-in works with every provider: browser, loopback redirect, no secret, tokens stored in the per-user store | step 3 ends `signed_in` for each provider |
| H5 | The stored sign-in is reused (new task, Desktop restart, refresh after expiry) | step 4 and later runs |
| H6 | Plugin hooks run in Cowork, on the host, and with which shell | step 5 |
| H9 | A PreToolUse hook receives the tool's input and its *deny* stops the tool (JSON answer and exit code 2); time per call | step 6: a and b blocked, c not; `input_keys` present; `launch_ms` |

Report one table (one row per provider for H4 and H5): hypothesis, what was observed, and pass / fail / not
tested. Facts only; mark anything you inferred as inferred.
