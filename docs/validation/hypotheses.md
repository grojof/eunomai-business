---
type: reference
title: Validation checks
description: "What must hold on a real installation for the design to stand, how each check is made, and its current status."
tags: [validation]
audience: [it, developers]
related: [run-the-validation.md]
---

# Validation checks

What must hold on a real installation for the design to stand, and how to check it. The automated tests
(`connector/tests/`) cover the connector's logic against a fake server; these checks cover what only a real
Claude Desktop, network and git server can show. How to run them: [run-the-validation.md](run-the-validation.md).

Target setup: Claude Desktop on Windows, a Cowork session **running on the user's computer**, a user **without
administrator rights**, internal servers reachable over the corporate network or VPN and not published to the
internet.

## Checks

| # | Must hold | Checked by | Status |
|---|---|---|---|
| H1 | The local connector runs on the user's computer, not in Claude's sandbox | `validate-setup`, step 1 | Pass · 2026-10-24: Windows 11 host, Python from uv's cache |
| H2 | It reaches internal HTTPS hosts, trusting an internal CA through the OS certificate store | `validate-setup`, step 2 | Pass · 2026-10-24: 200 on both internal hosts with the OS store; the bundled store fails, as expected with an internal CA |
| H3 | It starts with no per-user setup: `uv` found, `${CLAUDE_PLUGIN_ROOT}` expanded, the locked packages installed | The tools exist; `expansion_ok` | Pass · 2026-10-24 |
| H4 | Sign-in works with every provider (git server and Entra ID): browser, loopback redirect, no secret, tokens stored encrypted | `validate-setup`, step 3 | Pass · 2026-10-24: Gitea (2,084 bytes stored) and Entra ID (5,332 bytes stored), PKCE, loopback redirect |
| H5 | The sign-in is reused: new task, Desktop restart, refresh after expiry | [Guide, step 8](run-the-validation.md#8--robustness-h5) | Partial · 2026-10-24: reused within a task and in a new task without signing in again; restart and refresh pending |
| H6 | Plugin hooks run in Cowork, on the user's computer; which shell runs them | `validate-setup`, step 5 | Pass · 2026-10-24: SessionStart and PreToolUse on the host, through Git Bash (Git installed) |
| H7 | `uv` installs per user without administrator rights and Desktop finds it | [Guide, step 1](run-the-validation.md#1--install-uv-for-the-current-user-h7), on a standard account | Partial · 2026-10-24: installed from a non-elevated PowerShell (no elevation needed); a standard account under corporate policies (AppLocker, script execution policy, proxy) pending |
| H8 | Workspaces end to end, as a user joining a repository in use: **a** the connector sees exactly Claude's edits; **b** version, save point and send without Git; **c** text intact on the server (UTF-8, LF); **d** Claude's sandbox and the connector share `.git` without trouble; **e** the version is proposed with a pull request; **f** after the pull request is merged, `workspace_update` brings the user back to the updated main branch on its own | `validate-git` | **a, b, d, e** pass · 2026-10-24: clone of `main`, version, an existing file edited and a new one with accents, no CRLF, save, send and pull request with the connector only; the sandbox shell's `git log` sees the connector's commit and a clean tree. **c** pass: accents and author correct in the pull request, merged. **f** pass: after the merge, `workspace_update` returned to the updated main branch, retired the version and kept a backup |
| H9 | A PreToolUse hook receives the tool's input (file path, shell command) and a *deny* answer stops the tool, as a JSON answer and as exit code 2; fast enough for every call; works without Git | `validate-setup`, step 6 | Partial · 2026-10-24: both denials stop the tool (file reads and the sandbox shell alike; the hook runs on the host), the control passes, input field names arrive; launch about 150 ms per call. Exit code 2 shows the hook's command line, so the guard will answer in JSON. A computer without Git pending |
| H11 | The `specialist` skill takes over on vague requests in Cowork and keeps the conversation on the journey | A business-user test project | Pending |
| H12 | Visuals reach the user in Cowork: tables and Mermaid diagrams render, and a mockup (an HTML page in the workspace) opens | Same test | Pending |
| H13 | OpenSpec files written without its command-line tool follow its format: changes, specs, tasks, archive | Same test; the files read by the OpenSpec tool on a developer's computer | Pending |
| H14 | Code and tests run in Cowork's sandbox for the allowed technologies, and `dependency_check` decides every package | Same test | Pending |

## Planned

| # | Must hold | For |
|---|---|---|
| H10 | A project plugin's skills use the base plugin's connector; both plugins' hooks run; the organization can offer a plugin to some users only | Plugin per project ([architecture.md](../architecture.md#plugin-per-project)) |
