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
| The main branch is never sent; nothing is force-sent, except a version to the project's declared test branch | The shared history cannot be overwritten from a computer |
| To the test branch goes only a saved version that has everything on the main branch, never onto the main branch or the version's own, and checked against the main branch by the same rules as a save; the git server decides who may | The test environment never loses others' work nor gets a file only IT changes, and production still takes a pull request |
| Pull requests only from a version (branch) | Same rule, from the other side |
| No versions until the repository has its main branch | A version must start from the shared history, not from nothing |
| Workspace names are plain folder names, under `workspaces_root` only, never a Windows device name (`con`, `nul`, `com1`...) | No path tricks (`..`, absolute paths) |
| Version names: parts of letters, digits and `. _ -` separated by `/`, each starting with a letter or digit, none ending in `.` or `.lock`, no `..` | Only names git accepts |

## Bringing the latest changes

`workspace_update` brings the project's latest changes on its own, in this order, and never loses work:

| Step | Rule |
|---|---|
| 1 · Keep | Unsaved changes are saved first; on the main branch they go to a new version (`work/<date>`) |
| 2 · Fetch | The server's branches are read; nothing local moves yet |
| 3 · Back up | Before anything moves, the branch's position is kept as `refs/eunomai/backup/<time>/<branch>`; files changed during the update stop it instead of being replaced |
| 4 · Decide | A version with nothing saved: moves to the latest main branch. Accepted version (in the main branch, or its pull request merged): back to the main branch, the version retired. A proposal closed without merging: noted, the version kept. Open version behind the main branch: combined only if no file was changed on both sides, checked before touching any file; lines of the same file are never merged automatically. On the main branch: fast-forward only |
| Stop | The same file changed on both sides, a version changed elsewhere, a main branch that diverged or missing, files in the way: nothing changes, and IT is told |

## Dependencies

`dependency_check` decides which version of a package may be used, by rules, not by the model. Deny by default:

| Rule | Decision |
|---|---|
| Known vulnerability (OSV) | Blocked, always; no exception lifts it |
| Yanked, deprecated or a pre-release | Blocked |
| No source repository published, or the one published does not answer | Blocked, unless IT made an exception. A known code host (GitHub, GitLab, Codeberg, Bitbucket, sr.ht, `git.*`) or any https link the package labels as its code counts, if it exists |
| No release in three years, or marked inactive | Blocked, unless IT made an exception |
| Released less than two weeks ago | Blocked, unless every older version checked (the ten newest) is vulnerable: then the fix wins |
| No release older than two weeks at all | Blocked: the package is too new to trust |
| No answer from the registry or from OSV | Not allowed |

The newest version that passes is recommended, with its runtime requirements. The specialist uses only what the
check allows.

`dependency_audit` applies the same rules to every package a workspace pins, direct and indirect, in
`requirements*.txt` or `package-lock.json` (version 2 or later), outside environments and archives and never
through a link. It blocks:

- a requirement that is not an exact pin from the public index: ranges, URLs, local paths, other indexes or
  `--find-links`, and any `-r`/`-c` that does not name another pinned list in the same folder;
- an npm entry not downloaded from the public registry under its own name;
- a list that pins nothing, or leaves out a package a pinned one requires (Python; an npm lockfile is complete by
  construction), including one required only on Windows, Linux or macOS, since `--require-hashes` then fails
  there (markers are evaluated as PEP 508 says, with `packaging`). What a package requires only on other platforms,
  or only on Pythons older than the one a list was compiled for (`--python-version` in uv's header, or the
  `requires-python` of a `pyproject.toml` beside the list), is listed apart, not blocked;
- declared packages (`pyproject.toml`, `package.json`...) without a pinned list.

A project that installs no packages has nothing to check. Lists without hashes are noted. The specialist runs the
audit before delivering, and the connector runs it again itself and appends the result to every pull request, so
what IT reads there was not written by the model.

The source check is a signal of origin, not proof: a link that answers says nothing about what the package
contains. It never follows a redirect, never contacts an address that is not on the public internet, and never
reads the page. IT's own continuous integration (for example OSV-Scanner on every pull request) is the
complementary check on the server ([project practices](project-practices.md#checks-on-the-server)).

eunomai-business follows the same rules itself. Its whole dependency tree is locked (`connector/uv.lock`, nothing
younger than two weeks unless it fixes a vulnerability). Users' computers install exactly that tree with
`uv run --frozen`, which checks every package against the hash recorded in the lock and refuses a mismatch,
downloads with the operating system's certificate store, and ignores uv's configuration files on the computer.
Outside what a computer installs: a test tool used only on developers' computers, and a package installed only
in web browsers. Every day, a workflow applies these rules to the tree and proposes the result as a pull request.

## When the connector stops

Whenever a situation is not certain, the connector does not guess ([decision 6](decisions.md#6--the-user-never-resolves-a-technical-problem)):

- the user gets one plain sentence and the assurance that their work is safe;
- IT gets a report (workspace, repository, version, files involved, connector version; never tokens) and, when
  `support_email` is set, the user gets an e-mail link with that report already written;
- an unexpected error is handled the same way: the user never sees a technical error;
- an unreachable server is not a case for IT: the user is asked to check the network or VPN;
- a mistake in how Claude called a tool (not signed in yet, a name that is not allowed) comes back as `error`, for
  Claude to correct; it is never shown to the user.

## Between Claude's sandbox and the computer

Claude can write in the workspace folder, `.git` included, and the connector acts on that folder from the
computer itself. These barriers keep that from becoming a way to run commands on the computer.

| Barrier | Why |
|---|---|
| All git hooks are disabled: the connector empties the repository's hook table before any operation | dulwich runs `post-commit` even when told not to verify; any hook written into `.git/hooks` would run outside the sandbox |
| Only known `.git/config` entries are accepted: `core` (format, file mode, bare, ref logs, case, symlinks, Unicode, `autocrlf`), `remote.<name>.url/fetch`, `branch.<name>.remote/merge`, and the inert notes editors add to a branch (`description`, `vscode-merge-base`, `github-pr-owner-number`). Anything else stops the operation | Filters, `hooksPath`, `fsmonitor`, includes and submodules can run commands or fetch code |
| The configuration is checked once per operation and then pinned: what is written to `.git/config` afterwards is not read | dulwich re-reads the configuration on every call; a filter written between the check and the use would run |
| Content is never filtered: no filter driver, no line-ending conversion, no LFS, whatever `.gitattributes` says | A filter is a command; files go in and out exactly as they are |
| The repository's address and main branch come from the connector's own registry, recorded at clone time; an address changed in `.git/config` stops the operation | Otherwise the sandbox could send the user's work to another repository |
| A repository that points to another folder (`commondir`, `alternates`) is refused | Reads and writes must stay in the workspace |
| One operation at a time per workspace, across connector processes: creating a version, saving, sending (to review or to the test environment), bringing the latest changes and reading the project's context | Two updates or saves at once could undo each other |
| The computer's Git configuration (system and user) is ignored | Same behaviour with or without Git installed; a global filter cannot apply ([decision 3](decisions.md#3--git-inside-the-connector-independent-of-any-git-on-the-computer)) |
| Each clone gets `core.autocrlf=false` | A Git on the computer, if any, sees the files exactly as the connector does |
| Clones never fetch submodules (dulwich's default, not exposed as an option) | A submodule could bring code from another server |
| A save point never carries the project's context (`AGENTS.md`, `CLAUDE.md`), its declaration (`.eunomai/`), Claude's configuration (`.claude/`, `.mcp.json`) or continuous integration (`.gitea/`, `.github/`...): they are put back as the last save point has them, regardless of case and never through a link. Adding or changing a file Windows runs on a double click (`.bat`, `.ps1`, `.lnk`...) stops the save; removing one is allowed. Every path must be valid on Windows and stay in the workspace, in the index too. The tree actually committed is checked again | The context steers Claude and only IT changes it; integration runs on IT's servers; the workspace folder is on the user's computer, where a double click would run what the sandbox wrote; the sandbox can write the index and race the save |

## What eunomai-business does not protect

Said plainly, so nobody relies on it for these:

- **What goes into a save point.** A secret, a huge file or a wrong line ending is saved as it is (the connector
  reports CRLF in changed files, but does not block it). Projects decide their own rules
  ([project-practices.md](project-practices.md)); the git server enforces them.
- **Branch protection on the server.** The connector never sends the main branch, but only the server stops
  anyone else (another tool, a person with Git) from doing so. Protect it on the server.
- **Claude's own file tools and shell, beyond the file guard.** The guard hook denies writing executables, the
  project's context and configuration ([architecture.md](architecture.md#hooks)), only best effort in the shell;
  everything else is governed by Cowork and its permissions. Where code may be written is followed by the
  specialist, not enforced.
- **Script sources Windows can run.** A `.js` file opens in Windows Script Host on a double click, and a `.py`
  file in Python where the launcher is installed; web applications need them, so they are not refused. Disable
  Windows Script Host on business users' computers (a standard hardening policy), and keep application control
  (AppLocker, WDAC) in place.
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
