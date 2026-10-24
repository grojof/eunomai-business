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

## Bringing the latest changes

`workspace_update` brings the project's latest changes on its own, in this order, and never loses work:

| Step | Rule |
|---|---|
| 1 · Keep | Unsaved changes are saved first; on the main branch they go to a new version (`work/<date>`) |
| 2 · Fetch | The server's branches are read; nothing local moves yet |
| 3 · Back up | Before anything moves, the branch's position is kept as `refs/eunomai/backup/<time>/<branch>` |
| 4 · Decide | Accepted version (in the main branch, or its pull request merged): back to the main branch, the version retired. Open version behind the main branch: combined only if no file was changed on both sides, checked before touching any file; lines of the same file are never merged automatically. On the main branch: fast-forward only |
| Stop | The same file changed on both sides, a version changed elsewhere, a main branch that diverged, files in the way: nothing changes, and IT is told |

## Dependencies

`dependency_check` decides which version of a package may be used, by rules, not by the model. Deny by default:

| Rule | Decision |
|---|---|
| Known vulnerability (OSV) | Blocked, always; no exception lifts it |
| Yanked, deprecated or a pre-release | Blocked |
| No source repository published | Blocked, unless IT made an exception |
| No release in three years, or marked inactive | Blocked, unless IT made an exception |
| Released less than two weeks ago | Blocked, unless every older version is vulnerable: then the fix wins |
| No answer from the registry or from OSV | Not allowed |

The newest version that passes is recommended, with its runtime requirements. The specialist uses only what the
check allows.

eunomai-business follows the same rules itself. Its whole dependency tree is locked (`connector/uv.lock`, nothing
younger than two weeks unless it fixes a vulnerability) and users' computers install exactly that tree
(`connector/constraints.txt`, passed to `uvx`). Outside that tree: a test tool used only on developers' computers,
and a package installed only in web browsers.

## When the connector stops

Whenever a situation is not certain, the connector does not guess ([decision 6](decisions.md#6--the-user-never-resolves-a-technical-problem)):

- the user gets one plain sentence and the assurance that their work is safe;
- IT gets a report (workspace, repository, version, files involved, connector version; never tokens) and, when
  `support_email` is set, the user gets an e-mail link with that report already written;
- an unexpected error is handled the same way: the user never sees a technical error;
- an unreachable server is not a case for IT: the user is asked to check the network or VPN.

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
  (planned: file guard hooks, see [architecture.md](architecture.md#hooks)). Where code may be written, and that
  dependencies go through `dependency_check`, is followed by the specialist; the planned guard will enforce it.
- **A program running as the same Windows user.** DPAPI stops other users, not malware running as you.
- **Sign-out on the server.** Signing out deletes the tokens from the computer; it does not revoke them on the
  server. See [data-on-computers.md](data-on-computers.md#uninstalling).

## Diagnostics (opt-in)

Only in builds with `diagnostics: true` ([configuration.md](configuration.md#settings)); never for users.

| Tool or behaviour | What it does |
|---|---|
| `diag_environment` | Reports host, user, paths, the providers' names and some environment variables |
| `diag_reach` | Requests any URL from the computer, with the OS certificate store and the bundled one |
| Hooks on every tool use | Log each tool call (time, tool name, input field names, timings, computer, paths, session) to `hooks.log`; deny only tools whose input mentions a guard-test marker (`eunomai-guard-test-json`, `eunomai-guard-test-exit2`) |
| `diag_hook_log` | Reads that log |
| Skills `validate-setup` and `validate-git` | Step-by-step validation of an installation |
