---
type: reference
title: Barriers
description: "What the connector enforces in code and no configuration can turn off, and what it does not protect."
tags: [barriers, security, git, sign-in]
audience: [it, security]
related: [architecture.md, data-on-computers.md]
---

# Barriers

What eunomai-business enforces itself, in code. These are **not** settings: no configuration turns them off,
because a barrier that can be relaxed is not a guarantee. The connector's own barriers have tests in
`connector/tests/`; dropping the token on a redirect and TLS verification are done by dulwich and the operating
system.

Everything a project decides about its own files (line endings, ignored files, branch protection) belongs to the
project and its git server. See [project-practices.md](project-practices.md).

## Sign-in and tokens

| Barrier | Why |
|---|---|
| Public clients only: no client secret or certificate anywhere | Nothing secret to distribute or leak |
| Authorization code with PKCE (S256) and a `state` check | Stops code interception and forged callbacks |
| Redirect only to `127.0.0.1` or `localhost`, on the configured port | The answer never leaves the computer |
| HTTPS only; plain HTTP only to this computer (tests) | Tokens never travel in clear text |
| Tokens are never returned to Claude | The model cannot print, copy or send them |
| Tokens stored per user and per provider, encrypted: DPAPI on Windows, the OS keyring elsewhere | Other users of the computer cannot read them |
| The git token is sent only to the git sign-in's own origin (scheme, host, port), never written to `.git/config`; on a redirect to another origin dulwich drops it | A repository URL pointing elsewhere cannot capture it |
| TLS verified with the operating system's certificate store | Internal CAs work; nothing skips verification |

## Git

| Barrier | Why |
|---|---|
| No save points on the main branch: `main`, `master`, and the server's main branch, recorded at clone time in the connector's own folder (not in `.git`, which Claude's sandbox can write) | Changes reach it only through a pull request |
| The main branch is never sent; nothing is ever force-sent | The shared history cannot be overwritten from a computer |
| Pull requests only from a version (branch) | Same rule, from the other side |
| No versions until the repository has its main branch | A version must start from the shared history, not from nothing |
| Workspace names are plain folder names, under `workspaces_root` only | No path tricks (`..`, absolute paths) |
| Version names: parts of letters, digits and `. _ -` separated by `/`, each starting with a letter or digit, none ending in `.` or `.lock`, no `..` | Only names git accepts |

## Between Claude's sandbox and the computer

Claude can write in the workspace folder, `.git` included, and the connector acts on that folder from the
computer itself. These barriers keep that from becoming a way to run commands on the computer.

| Barrier | Why |
|---|---|
| All git hooks are disabled: the connector empties the repository's hook table before any operation | dulwich runs `post-commit` even when told not to verify; any hook written into `.git/hooks` would run outside the sandbox |
| Only known `.git/config` entries are accepted: `core` (format, file mode, bare, ref logs, case, symlinks, Unicode, `autocrlf`), `remote.<name>.url/fetch`, `branch.<name>.remote/merge`. Anything else stops the operation | Filters, `hooksPath`, `fsmonitor`, includes and submodules can run commands or fetch code |
| The computer's Git configuration (system and user) is ignored | Same behaviour with or without Git installed; a global filter cannot apply ([decision 3](decisions.md#3--git-inside-the-connector-independent-of-any-git-on-the-computer)) |
| Each clone gets `core.autocrlf=false` | A Git on the computer, if any, sees the files exactly as the connector does |
| Clones never fetch submodules | A submodule could bring code from another server |

## What eunomai-business does not protect

Said plainly, so nobody relies on it for these:

- **What goes into a save point.** A secret, a huge file or a wrong line ending is saved as it is (the connector
  reports CRLF in changed files, but does not block it). Projects decide their own rules
  ([project-practices.md](project-practices.md)); the git server enforces them.
- **Branch protection on the server.** The connector never sends the main branch, but only the server stops
  anyone else (another tool, a person with Git) from doing so. Protect it on the server.
- **Claude's own file tools and shell.** They are governed by Cowork and its permissions, not by this plugin
  (planned: file guard hooks, see [architecture.md](architecture.md#hooks)).
- **A program running as the same Windows user.** DPAPI stops other users, not malware running as you.
- **Sign-out on the server.** Signing out deletes the tokens from the computer; it does not revoke them on the
  server. See [data-on-computers.md](data-on-computers.md#uninstalling).

## Diagnostics (opt-in)

Only in builds with `diagnostics: true` ([configuration.md](configuration.md#settings)); never for users.

| Tool or behaviour | What it does |
|---|---|
| `diag_environment` | Reports host, user, paths, the providers' names and some environment variables |
| `diag_reach` | Requests any URL from the computer, with the OS certificate store and the bundled one |
| Hooks on every tool use | Log each tool call (time, tool name, computer, paths, session) to `hooks.log` |
| `diag_hook_log` | Reads that log |
| Skills `validate-setup` and `validate-git` | Step-by-step validation of an installation |
