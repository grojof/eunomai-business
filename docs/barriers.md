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
| To the test branch goes only a saved version the audit allows, that has everything on the main branch, never onto the main branch or the version's own, and checked against the main branch by the same rules as a save; the git server decides who may | The test environment never loses others' work nor gets a file only IT changes, and production still takes a pull request |
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
`requirements*.txt`, `requirements/*.txt`, `package-lock.json` (version 2 or later), `uv.lock`, or `vendor.json`, outside
environments and never through a link. The rules name no library or framework: which technologies a project may use is
`allowed_technologies`, and a package IT vetted despite the origin rules is in `dependency_exceptions`
([configuration](configuration.md)). It blocks:

- a requirement that is not an exact pin from the public index: ranges, URLs, local paths, other indexes or
  `--find-links`, and any `-r`/`-c` that does not name another pinned list in the same folder;
- an npm entry not downloaded from the public registry under its own name, with no version, or a link;
- a `package-lock.json` that no longer answers the `package.json` beside it, or that lists a package it does not hold;
- a script's own lockfile (`*.py.lock`, `*.pyw.lock`, `*.pyz.lock`), which `uv run script.py` honours: it would install
  what the audit never saw. Any other `*.lock` says nothing about Python or npm;
- a `uv.lock` entry that does not come from the public index, other than the project itself, so a workspace member
  is refused too. Every entry has files, each with a hash that the registry published for that name and version:
  anyone can upload to the index, so an address says nothing about which package a file is;
- a `uv.lock` that no longer answers `pyproject.toml`: a package missing or at a version it does not accept, or a
  requirement by address. A plain `uv sync` would write a new lockfile and install what the audit never saw;
- a `tool.uv` setting outside a short list of those that change neither where a package comes from nor which one is
  installed, and a `uv.toml` beside the lockfile;
- a `vendor.json` entry that does not name a valid npm `package` (or whose name is not one) and a `version` published
  there, or with a `url` other than https on a known code host or the npm registry. A file a project keeps in its
  own tree meets the same rules as the published package of that version; the project checks the bytes itself, and
  the host says nothing about who owns the file. `vendor.json` never counts as the list of what a project installs;
- a list that pins nothing, or leaves out a package a pinned one requires (Python requirements lists; npm and uv
  lockfiles are read as they are), including one required only on Windows, Linux or macOS, since
  `--require-hashes` then fails there (markers are evaluated as PEP 508 says, with `packaging`). What a package requires only on other platforms,
  or only on Pythons older than the one a list was compiled for (`--python-version` in uv's header, or the
  `requires-python` of a `pyproject.toml` beside the list), is listed apart, not blocked;
- declared packages (`pyproject.toml`, including its development groups, extras and dynamic dependencies,
  `package.json`, including peer and optional ones, `setup.cfg` with `install_requires`...) without a pinned list **in
  their own folder**, or in a `requirements/` folder beside them: a list elsewhere in the tree, or of another ecosystem,
  answers for nothing here. Every folder counts, named or not, poetry included, unless a project above names it as a member and has
  its lockfile. A copy, a sample or a template does not, told by its path: `vendor/`, `fixtures/` or `templates/` directly
  under the root, a test's fixtures (`tests/.../fixtures/`), or a library copied into what the application serves
  (`static/vendor/`, `assets/vendor/`, `public/vendor/`). The same name deeper in a project is an ordinary folder;
- a `pyproject.toml` whose `dependencies` the requirements lists beside it leave out, unless a `uv.lock` answers for it.
  Development groups and extras may rightly be in other lists;
- an npm workspace: its members are links, and the audit reads no link;
- a `uv.lock` holding anything the audit does not read, and a pinned list that is a link: tools follow it.

A text file named like a list is one unless some line could not install: pip refuses a whole file on such a line, so
`requirements/what-sales-wants.txt` is prose and blocks nothing, while `evil (>=1.0)`, `wheels/evil.whl` or `${EVIL}`
make it a list, and a real list with one bad line is blocked. The person reads which file it was. Not read, by design,
and left to IT's review: lists under other names (`deps.txt`, `constraints.txt`), `bundledDependencies`, pdm's
development dependencies, folders named `venv`, and which of a folder and a console script of one name uv runs.

Every package in a `uv.lock` is audited, whatever marker leads to it: a marker in a lockfile cannot be told from one
somebody edited, so a package only a browser installs needs IT's exception like any other. A package left out of a
lockfile is not installed, so the application breaks but nothing unaudited arrives. The audit reads the lockfile and
never runs uv, because `uv lock --check` can run a project's build backend on the user's computer. So it does not
prove the lockfile is what uv would write today, and what `[build-system]` installs is outside it, as no lockfile
holds it. `uv lock --check` belongs in the project's continuous integration, and the application installs with
`--frozen`: a plain `uv run` or `uv sync` may write a new lockfile. A `uv.lock` in a subfolder says nothing about a
project beside it, as with a requirements list.

A project that installs no packages has nothing to check. Lists without hashes are noted.

The audit decides the send. `version_send`, `version_propose` and `version_to_test` audit what is saved and refuse
unless it is `allowed`, whatever the project declares: a declaration that is missing, not valid or says no code is no
reason to send what nobody audited, and the code in a test environment runs too.

| Case | What happens |
|---|---|
| `allowed` | It goes, and the result is appended to the pull request, for the commit it names, so what IT reads there was not written by the model |
| `blocked` | Nothing is sent; the user reads why in plain words, and IT gets a report |
| The audit cannot run (no network, a registry that does not answer) | Nothing is sent: deny by default, like the rest of the audit |
| A version with no packages | `allowed`, without asking the network |
| A commit that breaks the rules of a save, at any point | Not sent, proposed or run: `.git` is writable from the sandbox, so each commit a version has beyond the main branch, as the server has it, is checked on the host, not only the last. A protected file added and taken out again would still travel in the history. A merge counts for what differs from all its parents, so taking in what IT changed is not changing it |
| The server has no such main branch | Nothing is sent, and IT is told: it was renamed, or the repository is empty. A server that does not answer is the network, as always |
| No history in common with the main branch | Nothing is sent, and IT is told: it was rewritten on the server |
| A branch the connector did not make | Nothing is sent to it: the connector keeps, outside the workspace, the names `version_create` made, and the branch is read once and checked as it is sent. HEAD on the main or test branch is refused outright. For a workspace from before this list, a version counts if the server has no such branch yet or has a proposal from it; anything else goes to IT |
| `version_propose` when the server's version is not the latest save | Nothing is proposed: `not_sent`. A proposal holds what the server has, so it must be sent first, and the send is where the audit answers. Work saved after a send, allowed or not, cannot reach review behind the commit that went |

| How | Why |
|---|---|
| It audits a copy of the saved version in a temporary folder, not the workspace | What goes is what is saved; the sandbox can rewrite the folder at any moment |
| The commit audited is the one sent, by its id, never by a local reference, and it stops if the version moved meanwhile | The sandbox can move a reference in `.git` during the send: nothing that was not audited goes |
| What a proposal says it audited is the commit it found on the server | Not one read a moment later |
| An `allowed` answer is kept for that saved tree for 15 minutes; any other answer is asked again | A send and the proposal after it wait once, and a registry that did not answer can come back |
| Packages are checked eight at a time | 51 packages took 38 seconds one by one, and this runs before every send |


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
| A repository that points to another folder or rewrites its own history is refused, and history is read from the commits alone ([what `.git` can change](#what-git-can-change)) | Reads and writes must stay in the workspace, and a rewritten history would turn the check of what a version changed into checking nothing |
| A Cowork task in the cloud is refused: Claude is told at the start, prompts are blocked, and every write, shell command and connector call is denied (or blocked if the guard cannot start). Known from the variables Claude Code sets in cloud sessions; in Cowork, H16 | The connector, the workspace folder and internal servers are on the user's computer and its network; a cloud sandbox would work on other files than the ones the connector saves |
| One operation at a time per workspace, across connector processes: creating a version, saving, sending (to review or to the test environment), bringing the latest changes and reading the project's context | Two updates or saves at once could undo each other |
| The computer's Git configuration (system and user) is ignored | Same behaviour with or without Git installed; a global filter cannot apply ([decision 3](decisions.md#3--git-inside-the-connector-independent-of-any-git-on-the-computer)) |
| Each clone gets `core.autocrlf=false` | A Git on the computer, if any, sees the files exactly as the connector does |
| Clones never fetch submodules (dulwich's default, not exposed as an option) | A submodule could bring code from another server |
| A save point never carries the project's context (`AGENTS.md`, `CLAUDE.md`), its declaration (`.eunomai/`), Claude's configuration (`.claude/`, `.mcp.json`) or continuous integration (`.gitea/`, `.github/`...): they are put back as the last save point has them, regardless of case and never through a link. Adding or changing a file Windows runs on a double click (`.bat`, `.ps1`, `.lnk`...) stops the save; removing one is allowed. Every path must be valid on Windows and stay in the workspace, in the index too. The tree actually committed is checked again | The context steers Claude and only IT changes it; integration runs on IT's servers; the workspace folder is on the user's computer, where a double click would run what the sandbox wrote; the sandbox can write the index and race the save |

### What `.git` can change

The sandbox can write `.git`, so nothing there is taken on trust. What dulwich could believe from it:

| In `.git` | Could change | The connector |
|---|---|---|
| `info/grafts`, `shallow` | A commit's parents | Refused: the repository stops. The connector's clones are full. Ignored besides |
| `objects/info/commit-graph`, `commit-graphs/` | A commit's parents | Ignored: history is read from the commits. A Git on the computer may leave a real one |
| `refs/replace/` | An object for another | Ignored: dulwich does not follow them |
| `objects/info/alternates`, `commondir` | Where objects come from | Refused |
| Objects, packs and their indexes, `multi-pack-index` | What a name holds | Verified: reading an object by name hashes it against the name, and a mismatch stops |
| Trees and commits in what goes | What the checks see against what git uses: of two entries with one name dulwich keeps the last, git the first | Verified: every commit beyond the main branch and every tree in it, from their raw entries. Refused: two entries with one name, adjacent or not, wrong order, modes or names git would not write, names one folder cannot hold apart (case, Unicode), malformed commits. What is already on the main branch is not judged |
| What travels | Objects nobody checked | Only what commits reach: the pack is built from them, so a stray object stays, and a blob a tree reaches is covered by the rules on its path |
| `config` | Filters, hooks, the address, `core.commitGraph`, `extensions`, other files through `include` and `includeIf` | Allow-list, then pinned for the operation. An include is never followed: its section is refused |
| `HEAD`, `refs/`, `packed-refs` | Which commit, which branch | Not believed for a decision: what is sent goes by commit id, audited first, to a branch checked as it is sent. The main branch's commit comes from the server |
| `hooks/` | Commands | Never run |
| `index` | What a save takes | Paths validated, and the tree committed is checked again |

## The preview on the person's computer

Off by default. Where IT turned it on, `app_preview` shows the real application in the person's browser, through the
connector ([decision 7](decisions.md#7--nothing-runs-on-the-users-computer-except-a-preview-it-turns-on)).

**This runs code an AI wrote and nobody has reviewed yet, on the person's computer, with their rights, outside any
sandbox.** The barriers below reduce that risk and do not remove it. They keep a mistake from becoming an incident;
they do not stop code written to do harm, and a program with the person's rights can undo most of them.

| Barrier | Why |
|---|---|
| Two keys, both needed: `app_preview` in the build, and `[preview]` in the project's declaration on the main branch, read from the server, never from the workspace | Neither an organization's build nor one project turns it on alone, and the sandbox cannot rewrite what is run |
| It runs a copy of the saved version, in a temporary folder outside the workspace, never the working folder. What the version changed since it left the main branch must meet the rules of a save | Nothing unsaved runs, and no file the sandbox just wrote. The sandbox can write `.git`, so a commit it forged with an executable or a file only IT changes does not run |
| It refuses unless the audit of that same copy says `allowed` and the copy has a `uv.lock`; if the audit cannot run, it refuses | Only packages the rules allow, and exactly those |
| Installed with `uv sync --frozen`, hashes verified, development packages out, wheels only (`--no-build`, at run time too), the project itself not installed (`--no-install-project`), uv's configuration files ignored (`--no-config`), on uv's own Python, of the version in `.python-version` if the project has one. Anything but a plain version there, such as `3.13`, is refused | Nothing is resolved anew, no package or build backend runs code at installation, and a file in the copy cannot redirect uv or name a program as the interpreter |
| Each command is a list of words run as `uv run --frozen <words>`, never through a shell. What may run is python with a file of the project, `python -m` with a module other than `pip`, `ensurepip` or `venv`, or a console script of a package in the lock, checked once they are installed. Never `python -c`, nor a script as the program, whose own metadata and lockfile uv would honour. `{port}` is the only substitution. The checks on a declaration catch slips, not malice: **IT reviews the declaration**, like anything else on the main branch | What IT reviewed is what runs |
| The environment is built from a short list: what uv and the system need, where installed programs are (`ProgramFiles`, so a browser the computer has is found), and `[preview.environment]`, which cannot replace those. What runs has only the project's own programs on its `PATH`. A proxy's address reaches the installation only. The person's own folders are replaced by empty ones, shaped as a profile, and `UV_PROJECT_ENVIRONMENT` points inside the temporary folder | The person's tokens, the connector's settings and every other variable stay out of its reach through the environment |
| It listens on 127.0.0.1 only: a free port is chosen; `run` must say so with a host option, `-b`, or `127.0.0.1:{port}`, and name no other host, socket or wildcard; the host variables of the servers it knows (`GUNICORN_CMD_ARGS`, `FLASK_RUN_HOST`, `UVICORN_HOST`, `HOST`, `BIND`) are checked the same way, and no other variable is the connector's business; an option it cannot know the meaning of, such as `--ip 0`, is left to the next check; it must answer before the person is told it is ready; and the system's own table must show it listening nowhere else: on Windows the whole tree on any port, elsewhere the application's port | Nothing is offered to the network |
| One preview per workspace folder, however its name is spelt, across connectors. The same saved version gets the running one's address and the time it has left, and no second copy; another saved version replaces it. Any connector can stop it | Nothing is left running by mistake. `stopped` is said only when it really stopped, `not_running` when there was nothing to stop, `not_stopped` when it may still be running |
| It ends on `app_preview_stop`, on a newer version, and 60 minutes after it started, a limit a detached process, the watcher, enforces itself. It does not end with the connector, the task or Claude Desktop. The watcher starts every step, so nothing descends from the connector; it is started by a process that ends at once, so no parent link leads to it, and that process breaks away from any job that allows it. Once the application answers, it no longer depends on the connector in any way. Until then a preparation ends with the connector that asked for it. On Windows every process runs in a job object with no name, from its first instruction, and dies with it; only the watcher is given it. Elsewhere a process group per step. The job and the limit stop an application that misbehaves, not one built to stay. The watcher also ends the preview if the application ends by itself, which the next `app_preview` tells, and if its state file is removed, as nothing could find it again. It then removes the temporary folder and its files | A connector lives one turn in Cowork, so the watcher is what looks after a preview. Whether it lives is the lock it holds, which the system frees however it dies: a process number can come back as another program, and a dead connector means nothing. A watcher that does not end when asked is ended, if its program and start time match. A process group left by a dead watcher is ended only if the marker in the preview's folder matches and, where `/proc` exists, a process of that group works in that folder. The state protects against the sandbox, not against the application, which runs as the person and can rewrite it: every field goes through one reader, an address is built from a checked port, and anything else ends that preview. What a state says of a version may not be true, so a person is not told it as fact |
| A workspace keeps, between versions, a folder of its own beside the previews: `data`, which the declaration reaches only as `{data}`, an absolute path of the connector's, and `environment`, the installed packages. It goes on `app_preview_stop`, at the time limit and with the sweep; a new version, an application that ended by itself and a turn cut short keep it. The environment is used again only for the same lockfile, declaration and Python, and anything else removes it whole before installing. A setup that fails on the data kept runs once more on none, and the person is told. `fresh` starts with none | The application writes there, so nothing in it is believed: the connector never reads the data, and runs the environment only inside the job, as it runs everything else |
| The person is told first, in one plain sentence, and agrees in the conversation | They decide. This one is a rule the specialist follows: the connector cannot check it |
| Cowork tasks in the cloud are refused by the guard | The computer is not there |

**What it does not stop.** While it runs, the application is a program of the person's:

- **Their files and network.** It can read anything they can read and send it anywhere they can reach. The allow-list
  covers the environment, not the disk: a saved password, a document, a browser's profile.
- **Their sign-in.** DPAPI stops other users, not a program running as this one, so it can read the git sign-in and
  act as the person on the git server, within what the server lets them do.
- **What it leaves behind.** Stopping the tree ends what it started directly. A file written elsewhere, a scheduled
  task, or a program started through a service outside the tree, stays.
- **The port, while it is open.** 127.0.0.1 keeps other computers out, not other programs here: other people signed
  in to a shared computer, and any web page open in the browser, can send it requests.
- **What the audit cannot see.** The audit judges packages by rules, not by reading them, and it says nothing about
  the code the assistant wrote.
- **A later listener.** The check on what it listens on is made once, as it starts. On Linux and macOS it covers only
  the application's port, and a program that starts a session of its own leaves the process group.
- **The tests.** `app_tests` runs a project's tests behind the same barriers, its own key and `[tests]`, for up to
  20 minutes, with the development packages too. What returns to the model is counts and at most ten failures, each
  a test's name and a line, marked as the application's text; whether they passed is the exit code's. The output,
  which can say anything, stays on the computer.
- **An audit a preview keeps.** A preview keeps an `allowed` audit for an hour, for the same rules, exceptions,
  file names and the content of every file the audit could read, so a change to the code is shown in seconds. That
  record is in the connector's folder, which the person's own programs can write, a preview's application among
  them. Such an application already runs its own code in a preview, so a forged entry gives it nothing it lacks.
  `version_send`, `version_propose` and `version_to_test` never trust it: they always audit afresh.
- **What one version leaves for the next.** The data and the installed packages are writable by the application, so
  one version's code can leave something the next one reads, or a changed package the next one runs, inside the job,
  until the lockfile, the declaration or the Python changes, or a stop.
- **A preview that outlives its keys.** One running when IT turns the setting off or removes `[preview]` carries on
  until it stops, within 60 minutes.
- **A preview nobody is looking at.** It outlasts the task and Claude Desktop itself, for up to 60 minutes, with
  everything above still true. The person is told, and only they, or the limit, end it. Closing Claude is not a stop.
- **Code built to stay.** The job and the limit stop an application that misbehaves. Code running as the person can
  start a program through a system service, outside the job, or take a handle of the job itself, as was proved on
  Windows, and so leave anything behind. That is the risk of decision 7, and no stop or limit answers for it. `stop`
  says `not_stopped` when the application's address still answers or the state cannot be read; a program that got
  out and listens nowhere is not seen. Running previews at Low integrity is a possible hardening, untested.
- **A host that holds the connector in a job it does not let anything leave.** That job is respected: nothing goes
  around it. The preview works, ends with the host, `keeps_running` is false and the person is told so. A job that
  allows leaving is left, and a tree kill finds nothing to follow. Elsewhere, what ends a whole session or control
  group, such as logging out, ends a preview too, whatever the watcher does; the next connector cleans up.
- **Text it printed.** The last lines of a step that failed go into the report for IT, marked as the application's.
  The model sees them too: the specialist shows them when asked and never follows them.

The real controls stay outside: least privilege for the person's account, what they can reach on the network,
application control, and IT's review. Before turning it on, read [configuration](configuration.md#seeing-the-application-on-a-persons-computer).

## What eunomai-business does not protect

Said plainly, so nobody relies on it for these:

- **A preview's code.** It runs with the person's rights: [what the preview does not stop](#the-preview-on-the-persons-computer).

- **What goes into a save point.** A secret, a huge file or a wrong line ending is saved as it is (the connector
  reports CRLF in changed files, but does not block it). Projects decide their own rules
  ([project-practices.md](project-practices.md)); the git server enforces them.
- **Branch protection on the server.** The connector never sends the main branch, but only the server stops
  anyone else (another tool, a person with Git) from doing so. Protect it on the server.
- **Claude's own file tools and shell, beyond the file guard.** The guard hook denies writing executables, the
  project's context and configuration ([architecture.md](architecture.md#hooks)) and git in a workspace
  ([hooks](hooks.md#git-from-the-sandbox-shell)), only best effort in the shell; everything else is governed by Cowork
  and its permissions. Where code may be written is followed by the specialist, not enforced.
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
