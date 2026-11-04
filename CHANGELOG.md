# Changelog

## Unreleased

- **`tools/new_project.py`: IT creates a project from a request in one command.** It reads the request e-mail as it arrived (English, Spanish or Catalan), checks the template and that the name is free, creates the repository, commits the application's name into `.env.example` and the preview before protecting `main`, protects it, gives the requester write access, turns Actions off where there is no runner, checks it all and prints the reply for the requester. `--dry-run` changes nothing; the token is read from its own file and never printed. Every server call goes through one `Platform` interface: Gitea implements it, and `platform: github` or `gitlab` is refused before the server is asked anything, until each has its class and a real server to test it. [Creating a project from the template](docs/project-practices.md#creating-a-project-from-the-template)
- **An organization names its plugin, and several live on one computer.** `plugin_name` (default `eunomai-business`) names the plugin, its tools and skills, its folder on each computer, its default workspaces folder and the start of its e-mail subjects; `plugin_description` its line in the plugin list. Two plugins, for example one for applications and one for web projects, never share sign-ins, requests, previews or workspaces, and each guard matches only its own tools and protects only its own workspaces. A project plugin names the base plugin it belongs to (`base_plugin`). [Several plugins on one computer](docs/configuration.md#several-plugins-on-one-computer)
- **The browser tests find Edge on a person's computer.** In a Cowork test the host started the connector without `PROGRAMFILES(X86)`, where Edge is installed, and all 106 browser tests stopped at launch. The folders where programs are installed now come from Windows itself (`SHGetKnownFolderPath`) when the connector's own environment lacks them. The test run also gets a wide terminal: pytest had cut each line of its summary at 80 columns, and the cause of the error never reached the specialist.
- **The specialist documents the application, not its template.** In a Cowork test the new project kept the base's README and its documentation, and nothing about the application was written. The build stage now asks, in the organization's documentation language and in the same save as the code: a README that maps this application (what, for whom, why, how IT runs it and tests it, an index that reaches every page), a page in `docs/` with living-docs frontmatter for what the README cannot hold, one fact in one home with links to the base's reference instead of copies, and the index and the page changed together. Delivery checks it.
- **Each stage of the specialist is a skill** (`specialist-understand`, `-shape`, `-specify`, `-build`, `-deliver`). In a Cowork test, once the project's folder was connected, Cowork refused to read the specialist's references: it shaped, built and delivered without them, and never ran the tests on the person's computer. A skill loads through the Skill tool wherever the task's folders are. The connector's tools are loaded by their exact names, and a search that finds none is no longer reported as a lost connection: the person had been told to check their VPN.
- **A request for a new project reaches IT whole.** In a Cowork test the model retyped the e-mail link and left out the request, the date, how it is done today, the scope and the open questions. The connector now opens the request on a page in the person's browser: a button copies it, formatted for a mail program and as plain text, and a link starts the e-mail with the subject alone, so no mail program cuts a long link. The model gets a short message and the page's address, never the request. The request names the signed-in git user, for the access IT gives. `message_style` gives the page and the copied e-mail an organization's accent and font; the default is neutral.
- **The tests run on pull requests only**, not again on main after a merge, and the job may take 30 minutes: on
  2026-11-02 the Windows job finished every test after 14 minutes and was then cut at its 15-minute limit.
- **What answers at the address is the preview's own** (review of the live preview): a program that took the port
  first was shown to the person as their application; the system's table must now say the listener is in the
  preview's tree. Read-only files no longer survive a removal that said it was done, and a stop or a fresh start
  that cannot clear says so. A summary of the tests leads with the exit code's verdict. A kept environment is checked
  against the lockfile by uv, not only against a record the application can write. `uv` and `pipx` are installers
  as modules too. The programs' list follows no link out of the environment. Starting the same version again keeps
  its hour.
- **A change shows in about 4 s**: a preview keeps an `allowed` audit for an hour, for the same rules, exceptions and
  every file the audit could read; sends, proposals and the test environment always audit afresh. Whether the
  folder has unsaved changes is asked while the rest goes on, and the watcher reacts sooner. The home a preview or a
  test run gives is shaped as a profile, which Edge needs to start: the base application's browser tests now pass
  through `app_tests`, in the computer's Edge.
- **`app_tests`: the project's tests on the person's computer**, behind a build key of its own and `[tests]` on the
  main branch: the preview's watcher, job, environment and audit, development packages too, for up to 20 minutes.
  The model gets counts and at most ten failures, marked as the application's text; the output stays on the
  computer for IT. Browser tests use a browser the computer has, as the declaration names it: Edge on Windows.
  The specialist runs them before proposing and after fixing a failure.
- **A preview a person keeps open while it changes**: a new version takes the address of the one it replaces, so the person
  reloads the page, keeps the data the declaration puts in `{data}`, and skips the installation when the lockfile,
  the declaration and the Python are the same: about 9 s for a change on the clean base application. The hour counts
  from the latest version. A setup that fails on the data kept runs once more on none, and says so; `fresh` starts
  over on request. The data goes with a stop, the time limit and the sweep. Each test run has its own temporary
  folder, so two runs on one computer no longer count each other's previews.
- **A business person never creates a repository** ([decision 15](docs/decisions.md#15--a-business-person-never-creates-a-repository)).
  When someone wants a new application and no project exists, the specialist understands it in conversation, with
  nothing written, and `project_request` turns it into a request for IT with a fixed format: an e-mail link to
  `support_email` and the same text to copy; nothing is sent until the person sends it. A copy stays in the
  connector's folder and `workspace_list` lists it; once IT has created the project, the specialist clones it, starts
  the first proposal from the request without asking again, and `project_request_done` marks it done and keeps it.
  The request's fixed text is in the organization's documentation language (Spanish, Catalan or English), with a
  subject that always starts `eunomai-business:`. A request the person no longer wants is withdrawn with
  `project_request_withdraw`: kept, and no longer asked about. The specialist never offers to create a repository. [Project practices](docs/project-practices.md#creating-a-project-from-the-template)
  say how IT generates one from a Gitea template with `protected_branch`, and what Gitea's docs leave open: the
  caller's permission, and any default protection for new repositories (H24). The connector creating repositories
  itself was set aside for that reason.
- **E-mail links to IT follow RFC 6068:** a stop's report and a project request are built by one function, with
  line breaks as `%0D%0A`; a stop's subject is cleaned like its body.
- **A preview belongs to its watcher** (first real test in Cowork): the application died seconds after each turn, as
  Cowork starts a process per turn and the connector lives one. A detached process now owns a preview: it starts every
  step, keeps the tree, enforces the 60 minutes, and survives a tree kill, a host's job that allows leaving, and a
  group kill. **So a preview now outlasts the task and Claude Desktop, for up to 60 minutes**, and the specialist says
  so. Any connector finds a running preview, with the time left and no restart, and stops it; another saved version
  replaces it; one that died by itself is told and started again; `stopped` is said only when it stopped. Liveness is
  a lock the watcher holds, so a process number that came back is not trusted. A host job that refuses is respected
  and told.
- **Nothing in a preview's state is believed** (independent review): the application runs as the person and can rewrite
  it, so a planted address reached `webbrowser.open`, which on Windows runs a file. Every field now goes through one
  reader, an address is built from a checked port, and a state that fails ends that preview. A watcher that does not
  answer is ended, once its program and start time match. The claim that nothing outlives the watcher is withdrawn: the
  job and the limit stop an application that misbehaves, not one built to stay. A ready preview nobody was told of,
  one that stopped answering, one that is ending, a changed declaration and a state file that cannot be written are
  each told for what they are. A turn that ends on `starting` ends the preparation, and the person is told.
- **`workspace_clone` takes `owner/repo`**, on the signed-in server: a task that was given one failed, then guessed
  github.com. Anything else says the only server there is, and to try no other.
- **A business user's computer** (add-on to the fourth review): the connector's start, a preview of the base application
  and the whole path against a fake server now run on uv and Windows' own folders, with no git and no Python, and a
  repository test keeps it so. When a download cannot get through the person reads one plain sentence and the report
  names the address, or the Python to deploy; uv's own three tries are the only ones. With `github.com` closed, every
  package seemed not to show where it comes from: it is now told as an audit that could not run, and still stops.
  [Configuration](docs/configuration.md#installing-uv-in-an-organization) says which Pythons to deploy, how much a
  person downloads, every address, and that a Python from the Microsoft Store is neither needed nor used.
- **What goes is well formed before anything reads it** (fourth review): a tree listing `AGENTS.md`, a workflows folder or
  `requirements.txt` twice showed dulwich's checks an innocent twin while git used the other, and it reached the server
  and a real merge. Every commit beyond the main branch and every tree in it are now read from their raw entries, for
  send, proposal, test environment, preview and the audit's copy: duplicates, order, modes, names that collide by case
  or Unicode, malformed commits. The rules of a save hold for each commit, not only the last. `include` is never
  followed in `.git/config`.
- **Real lists are lists, and a manifest cannot opt out** (third review): `evil (>=1.0)`, `wheels/evil.whl`, `file:./x.whl`
  or `${EVIL}` read as prose and went unaudited. A file is prose only if some line could not install, since pip refuses
  it then. Every folder that declares packages counts, named or not, poetry included; a parent answers only with its
  lockfile and for the folders it names; copies, samples and templates are told by their path. In the git rule, a
  folder with a wildcard could be anywhere.
- **History comes from the commits, and the connector chooses the target** (third review): a commit graph of 1 KB made a
  forged commit look like an ancestor of the main branch, the third such trick, so history is now read only from
  commit objects, which are hashed against their names. [Barriers](docs/barriers.md#what-git-can-change) lists what `.git`
  can change. The branch is read once and checked as it is sent, and only versions the connector made are sent. A main
  branch the server no longer has, and a history rewritten on the server, are told as such.
- **The git rule: daily commands pass, and a few mistakes no longer do** (second review): `git clone` to a copy, a `cd`
  after `&&` on a following line, `branch --show-current`, `branch -a`, `remote -v`, `tag -l`, `config --get` and
  `--exec-path` pass, as real git shows they do not write, as do heredocs with `<<\\EOF` and quoted delimiters. A
  relative `git -C` that climbs, stays here or names a workspace is refused; a `cd` in a pipe or behind `&` no longer
  moves what follows; text piped or `<<<` into a shell counts; Windows paths read alike in both quotes. The rule stays
  a helper: `docs/hooks.md` lists what text matching does not see.
- **A preview's declaration, fewer holes and fewer false refusals** (second review): `python.exe` no longer skips the
  shape check, and `pip3.13` is refused as an installer. `127.0.0.1:{port}` and `gunicorn -b` are accepted, and the
  environment check is limited to the host variables of the servers it knows: a database's address or a version is
  not its business. `.python-version` may have a byte order mark, blank lines and comments. A stop file left behind no
  longer ends the next preview, and a stop that cannot reach another task's preview says so.
- **The audit stops refusing what is not a list** (second review): since it decides every send, these blocked real
  projects. Prose in a file named like a list, any `*.lock` but a script's, a `package.json`, `pyproject.toml` or
  `requirements.in` that is not the project (under `vendor`, `fixtures`, `templates`, or with no project name), a
  `setup.cfg` with tool settings only, a `requirements/docs.txt` beside a `uv.lock`, a runtime list next to development
  groups, and a byte order mark. What a person reads now names the file. An npm workspace stays refused.
- **A forged commit does not leave the computer** (second review): a commit written straight into `.git` reached the
  server with workflows, the project's declaration and `AGENTS.md`, since only a save checked them. `version_send` now
  checks what a version changed against the main branch on the server, and refuses without it. HEAD on the main or test
  branch sends nothing. A repository with grafts or marked shallow stops: grafts emptied that very check. A proposal
  audits the commit it compared.
- **A preview stops more surely** (independent review): every process group of every step is kept, not only the last;
  the job has no name, so nothing in it can keep it open, and the watcher holds a handle of its own; the watcher
  removes the state file, and a number in one is acted on only while a marker in the preview's folder matches. The
  time limit counts from the start, and an application that answers slowly cannot hold the check. One preview per
  folder, however its name is spelt. A state file is written whole, and junk in one no longer stops every preview. A
  commit forged past the rules of a save does not run. A stale failure is no longer told for a version shown again,
  and a stop during the copy leaves nothing. What an application printed is marked as such in IT's report.
- **`.python-version` is honoured:** `--no-config` made uv ignore it, so an application could run on another Python than
  its own. A plain version goes to uv as `--python`; anything else is refused for IT.
- **What a preview may run is an allow-list** (independent review): a saved script with its own lockfile ran packages no
  audit saw, because `uv run app.py` honours them. A script is no longer a program, `--no-build` applies at run time
  too, and a program must be python with a file of the project, `python -m` with a module other than `pip`,
  `ensurepip` or `venv`, or a console script of a package in the lock, checked once installed. `python -c` is
  refused. What runs has only the project's own programs on its `PATH`. A host option must say exactly `127.0.0.1`:
  the address anywhere else in the command no longer passes, and `[preview.environment]` is checked too. On Linux and
  macOS the listening table is read instead of trying the computer's addresses. These checks catch slips, not malice:
  IT reviews the declaration. `app_preview` must be exactly `true`.
- **Ways around the audit closed** (independent review): `package.json` and the root of `package-lock.json` must agree;
  npm entries with no version or a link are refused, not skipped; peer and optional dependencies count; each folder
  that declares packages needs a pinned list of its own and its kind; a `pyproject.toml` must be answered by the
  requirements lists beside it; a folder called `archive` is read; `requirements/*.txt` are read; a lockfile the audit
  does not read, such as `script.py.lock`, is refused, as is a `uv.lock` wheel with a local path.
- **The audit gate holds for every send** (independent review): it no longer depends on what a project declares, since
  a declaration that was not valid turned it off. `version_to_test` goes through it too: that code runs in an
  environment. A version with no packages needs no network. `version_propose` judges what the server holds: if the
  latest save is not there it answers `not_sent`, so a proposal never says `allowed` for a commit it does not hold,
  and the audit's line names the commit. The commit audited is the one sent, by its id: a reference the sandbox moved
  during the send no longer changes what goes.
- **The git rule reads a command as a shell does** (independent review): a regression had let `echo x > $WS/.git/config`,
  `tee`, `touch`, `cp`, `~` paths, `Set-Content` and `New-Item` into `.git`; a place that cannot be worked out now
  counts as a workspace's when it names `.git`. `--work-tree` alone no longer counts as elsewhere, a `cd` holds only
  as far as it surely ran, and more wrappers are followed. A quoted word is data, so `echo "git add"`,
  `grep -r "git status" docs` and heredocs are no longer refused, nor `git diff HEAD~1 HEAD`, `git diff main HEAD`,
  `--output-indicator-new`, `--no-replace-objects`, a same-named copy in the sandbox's outputs, or a relative
  `git -C`.
- **Validation, first real test with the plugin built from main (2026-11-01):** H14, H17 and H19 updated with what
  was measured; H21 failed; H23 is new, for asking Cowork for a folder during a task.
- **Real screens instead of a prototype, where a project allows code:** the specialist builds the first real screens
  with example data on the project's own base, and the person tries those through `app_preview` or the test
  environment before tests and the full specification are written. Where neither exists, screenshots if the sandbox
  can take them, otherwise it says the person will see it at review. An unfinished screen is not polished. The HTML
  prototype stays only where a project does not allow code. `## Agreed screens` in `proposal.md` tells a new task
  that Shape is done.
- **Decision 7 changes: a person can see the real application on their own computer.** Off by default, with two keys:
  `app_preview` in the build and `[preview]` in the project's declaration. New tools `app_preview` and
  `app_preview_stop`, on the connector, so nothing is written for the person to run. It runs a copy of the saved
  version, refused unless the audit allows it and it has a `uv.lock`, through `uv` with `--frozen`, never a shell, in an
  environment built from a short list, on 127.0.0.1 only. It stops, its whole process tree and temporary folder with
  it, on request, with the connector, and after 60 minutes. **This runs code nobody has reviewed yet, with the
  person's rights, outside any sandbox; the limits reduce that risk and do not remove it** ([barriers](docs/barriers.md#the-preview-on-the-persons-computer)).
  H21 failed: a server in the sandbox cannot be opened from the computer. To validate: H22.
- **The specialist asks for the folder in the same task:** after `workspace_clone`, or when the folder is not
  selected, it requests it with `mcp__cowork__request_cowork_directory` and carries on; the sentence asking for a new
  task stays as the fallback when that tool is not there or fails. To validate: H23.
- **Everything shown is in the user's language:** the first real test showed lines such as "Main branch, no open
  change → Stage 1 Understand" and "Now generation", and told a business user to run `uv run uvicorn` in a terminal.
  The rule now covers status lines between tool calls, stage names and commands.
- **A question not answered means wait:** in the first real test the specialist asked, got no answer, and went on
  with `uv add requests`, saying "no preference, I take the recommended one". No default is taken in the user's name
  for anything that changes the project, and Understand no longer offers the recommended answer and moves on.
- **The audit decides the send:** in the first real test the specialist got `blocked` from `dependency_audit`,
  explained it away and sent the pull request; the rule was only in the skill. `version_send` and `version_propose`
  now audit what is saved where a project declares code, and refuse unless it is `allowed`, in plain words; an audit
  that cannot run refuses too. Nothing changes where a project declares no code. It audits a copy of the saved
  version, the send names the commit it audited, and an `allowed` answer is kept for 15 minutes, so a send and the
  proposal after it wait once. Packages are checked eight at a time: 51 took 38 seconds one by one.
- **Git stays out of a workspace's sandbox shell:** the first real test left `.git/index.lock` after a `git status`,
  which stopped `version_save`, temporary objects after a `git stash`, and the assistant then removed files inside
  `.git`. The guard now denies, built in, git commands that can write in a workspace and anything that writes or
  removes inside its `.git`, pointing to `workspace_status`; a copy elsewhere stays free. Measuring which commands
  really write showed that `git diff` is not read-only: it rewrites the index, even with `--no-optional-locks`, so
  only `--cached`, `--staged`, `--no-index` and ranges are allowed. `validate-git` no longer asks for `git status`.
- **Recommended stack without Alpine.js:** `business-app-base` built every form without it, so a plain script of the
  application's own takes its place; a screen with a lot of browser state decides it on its own. The validation guide
  gains the test of the base application in Cowork.
- **Dependency summaries say why a package moved:** one left only because it is newer than two weeks read as fixing
  a vulnerability, because the reason it is blocked contains the word.
- **`dependency_audit` reads `uv.lock` and `vendor.json`:** every package a uv project locks is audited, development
  ones included, and each file's hash must be one the registry published for that name and version. A lockfile that
  no longer answers `pyproject.toml`, a `tool.uv` setting outside a short list, and a `uv.toml` beside the lockfile
  are refused. Files kept in the project's own tree meet the same rules as the published package, and do not hide
  packages left unpinned. Nothing in the audit names a library. A package's source is now what it labels as its
  code: `annotated-doc`, which FastAPI needs, was blocked because a `Changelog` address was taken for its repository.
  Packages declared only for development, as extras or dynamically must now be pinned too, and a pinned list that
  is a link is refused. `colorama` and `httpx2-jsfetch` need IT's exception.
- **Decision 14, the visual layer and the organization's layer:** corrects the recommended stack, which refused
  Tailwind and Bootstrap for bringing a build or an npm tree. Neither needs an npm tree: Bootstrap is published
  compiled, and Tailwind's stylesheet is built by a standalone executable, with daisyUI's files. Tailwind with
  daisyUI is now the recommended layer, behind Jinja macros so an organization can replace it, with the generated
  CSS committed and colours only in the organization's theme. Bootstrap stays rejected, for its global styles. The organization's layer is a base
  application to clone (`business-app-base`), not a plugin holding components. The npm, Node and React rules do not
  change. To validate in Cowork: H20, H21.
- **Decision 13, one recommended stack:** Python with FastAPI, PostgreSQL, and pages made on the server with Jinja2
  and htmx; exact decimals end to end; an organization's layer of brand variables and Jinja macros; React only for
  IT. New page: [recommended stack](docs/recommended-stack.md). The templates follow.
- **Deny rules by configuration** (decision 12): `deny` in the build's configuration, in Claude Code's permission
  syntax (`Bash(<command>)`, `Edit(<path>)`), with examples the build checks. eunomai-business's guard applies them
  after the file guard (Bash rules anywhere, Edit rules in workspaces); a project plugin applies its own in its
  workspaces, replacing its `{paths, reason}` rules. One rule module, shared and kept identical by a test. New page:
  [hooks and rules](docs/hooks.md). A deny rule errs on the side of denying: quotes, loops, substitutions and
  wrappers do not hide a command. **Migrating a project plugin:** write each path as `Edit(/<path>)`; without the
  leading `/`, a bare name such as `*.lock` or one folder such as `secrets/**` now matches at any depth, as in Claude
  Code. To validate in Cowork: H19.
- **Only tasks on the user's computer:** a Cowork task in the cloud is refused. Claude is told at the start, prompts
  are blocked, and every write, shell command and connector call is denied, from the variables Claude Code sets in
  cloud sessions. The hook's matcher is anchored, so it covers exactly the file tools, the shell and the plugin's
  own tools; the project-plugin template does the same for its tools. To validate in Cowork: H16.
- **The test environment pulls its branch:** a branch-following agent for any Linux server with systemd
  (`templates/test-environment-agent/`): a read-only deploy key handed over as a credential, each commit fetched
  into a throwaway repository, IT's own apply command without the key, the previous release kept live when an apply
  fails or hangs, one unprivileged hardened user per application. The guide for IT now sets out six layers, for any git server;
  deploying from CI with repository secrets is advised against.
- **Build variants:** `variants/<name>.json` holds only what differs from `config.local.json`;
  `python tools/build.py --variant <name>` or `--all` writes each package in its own folder, after checking all of
  them.
- **A test environment without waiting for IT:** a project may declare a test branch (`[test]` in
  `.eunomai/project.toml`). `version_to_test` replaces it with the user's saved version, which must already have
  everything on main; the project's CI applies it. The git server decides who may (a protected branch limited to a
  team); for anyone else the version goes through IT's review as usual. The specialist offers it after a save whose
  tests pass. To validate on a real Gitea: H18.
- **Decision 11 and the project-plugin template** (`templates/project-plugin/`): a local server for the
  project's tools, a hook that only denies the paths the project protects in its own workspaces (told by
  eunomai-business's register of workspaces, with Python's standard library only), a skill, and a build that
  declares eunomai-business as a dependency and refuses obvious secrets.
- **A project declares its own development:** `.eunomai/project.toml` on its main branch (`[development]`: `code`,
  `technologies`), read from the server with `AGENTS.md` and protected like it. The `projects` setting is gone; a
  build that still has it stops with a message. Unknown keys in `[development]`, or a main branch the connector
  cannot read, allow no code.
- **Decision 10:** eunomai-business holds what is valid for everyone; a project brings its own capabilities as a
  project plugin that depends on it, and its context in `AGENTS.md`. Per-project path rules in the base were
  rejected. H10 (`research/project-plugin/`): a project plugin with `dependencies: ["eunomai-business"]` loads
  next to it in Cowork and stays off without it, and both plugins' hooks run on the same call (a member's own
  upload; the organization's upload pending).
- **Audit:** the `requires-python` of a `pyproject.toml` beside a list also sets the Pythons it must cover; each
  list counts with its own.
- **Second business-user test:** the specialist saves per task, runs its readiness check last, never changes
  what the user approved without asking them, keeps open questions open, makes production the default and
  forbids deciding on one's own record, pins dependencies for every computer (`uv pip compile --universal`),
  and shows screenshots only as images. Pages in `docs/` get a valid `type`.
- **IT's review reaches the specialist:** `workspace_status` brings an open pull request's review decision and
  the reviewers' open requests; the specialist reworks them as a small change in the same version.
- **Audit:** a requirement for Windows, Linux or macOS left out of the pinned list now blocks; markers are
  evaluated with `packaging` (PEP 508), a new direct dependency of the connector, for the Python a list was
  compiled for.
- **The runtime is IT's (decision 9):** one plugin carries skills, hooks and the connector; IT deploys uv at a fixed
  version and absolute path. Researched and rejected for now, with their official sources: a Node.js connector,
  the connector as a separate MCPB extension, and an MCPB bundle inside the plugin (not run by Cowork).
- **Launch:** `--system-certs` replaces the deprecated `--native-tls`, and `--managed-python` makes uv use its own
  Python 3.12, never the computer's. uv 0.13.4 or later is required for security (GHSA-hq85-5cpj-mr62).
- **Dependency audit:** a pin that only another platform installs (a web browser's `emscripten`) is listed apart
  instead of blocked; the connector's own locked tree passes its own audit (41 packages, hashed, no known
  vulnerabilities).
- **Lessons from the first business-user test:**
  - nothing runs on the user's computer: the specialist never writes launchers or gives commands, and a save point
    refuses files Windows runs on a double click; users try a clickable prototype instead of static mockups;
  - a file guard hook in every build denies writing the project's context (`AGENTS.md`, `CLAUDE.md`), Claude's
    configuration and executables, and `version_save` enforces it on the host;
  - whose context counts: new settings `organization_context` and `organization_skills`, and the project's
    context read from the main branch on the server, in `specialist_settings`;
  - `dependency_audit` checks every pinned package, direct and indirect, and finds packages left out of the list;
    a source repository is any existing https link the package labels as its code (openpyxl on heptapod);
  - the specialist sizes the journey to the request, asks one question at a time, claims nothing without fresh
    evidence, never bends a test to the code, saves per task, checks that its documents agree, and reports the
    skills it used and their conflicts with its rules;
  - new skill `review-skills`, for IT to review the skills and plugins users have alongside eunomai-business;
  - notes VS Code adds to a branch in `.git/config` no longer stop the workspace;
  - the connector's data folder under Claude Desktop installed as a Windows package is documented.
- **Independent audit of those changes (security, skills, coherence, decisions):**
  - a save can no longer write or delete outside the workspace through paths planted in the index or a crafted
    tree, links, case variants or names Windows trims; the tree actually committed is checked again;
  - the project's context is read from the server at the moment it is asked, not from references in `.git`;
  - the guard blocks when it cannot run, covers configuration and continuous integration folders in the shell,
    applies its context rules only inside workspaces, and refuses more Windows executables;
  - the dependency audit refuses other indexes, local paths, unpinned includes, lockfiles version 1 and npm
    entries from elsewhere; the source check never contacts private addresses or follows redirects;
  - every pull request ends with the connector's own dependency audit; a pull request already open gets its
    description updated;
  - prototypes are saved only with a Content-Security-Policy that loads nothing from other sites;
  - the specialist's description, start order, stage table and no-code path were corrected.
- **Coherence fixes (independent review):** network errors narrowed (a local disk problem is not "check the
  network"); the proposal lookup pages through recent pull requests; IT reports name the build; the specialist
  handles a failed sign-in, an unknown proposal and the recommended version; the daily workflow runs upgraded
  packages without write access and closes its issue once problems are gone.
- **Security hardening (independent review):** the workspace configuration is pinned once checked, so a filter
  written into `.git/config` during an operation can no longer run on the computer; content is never filtered;
  the repository address comes from the connector's registry, not from `.git/config`; one operation at a time
  per workspace; edits made during an update are never overwritten; repositories pointing to other folders,
  empty credentials in addresses, Windows reserved names and case variants of the main branch are refused; a
  burst of fresh releases no longer gets past the two-week rule; forged sign-in answers are ignored.
- **Audit fixes:** a network outage asks the user to check the network instead of going to IT; a refused token
  refresh means signing in again; a version with nothing saved simply moves to the latest main branch; versions
  always start from the main branch; a version changed on the server is never overwritten when sending;
  `workspace_status` shows the version's proposal; the specialist signs in first and recognizes a proposal waiting
  for review.
- **`workspace_update`:** brings the project's latest changes on its own: saves unsaved work first, backs up
  before moving anything, returns to the main branch when the user's proposal was accepted (also after a squash
  merge), and adds new main-branch changes to an open version only when no file was changed on both sides.
- **Stops go to IT, not to the user:** when the connector is not certain, or an unexpected error happens, the user
  gets one plain sentence and IT a report, with an e-mail link when `support_email` is set.
- **New setting `support_email`.**
- **Dependencies follow the project's own rules:** the whole tree locked with nothing younger than two weeks
  unless it fixes a vulnerability (certifi 2026.10.19), truststore back to 0.10.4.
- **Launch with `uv run --frozen`:** users' computers install exactly the locked tree, each package checked
  against its hash; downloads use the operating system's certificate store; uv's configuration files on the
  computer are ignored; Python 3.12. The setting `uvx` becomes `uv`.
- **The specialist (first version):** the `specialist` skill guides a business user from a vague idea to a pull
  request (understand, shape, specify, build, deliver), writing OpenSpec files without its command-line tool.
- **Settings for the specialist:** `docs_language`, `code_language`, `free_development` (off by default),
  `allowed_technologies`, `projects`, `dependency_exceptions`; tool `specialist_settings`.
- **`dependency_check`:** which package version may be used, decided by rules (vulnerabilities, yanked,
  deprecated, origin, activity, age), deny by default.
- **Software bill of materials:** `connector/sbom.cdx.json` (CycloneDX 1.5) with versions, hashes, licenses and
  dependencies of every runtime package, shipped inside the plugin; `tools/sbom.py` regenerates it.
- **Daily dependency maintenance:** a workflow applies the project's rules, proposes updates as one pull request
  and opens an issue for vulnerabilities without an allowed fix; tests run on every pull request (Linux, Windows).
- **Compliance page** for audits: data protection, information-security controls, supply chain and licenses,
  and what remains the organization's responsibility.
- **Guard probe (diagnostics):** the diagnostic hook denies two test markers, as a JSON answer and as exit code 2,
  and logs input field names and timings, to validate the file guard (H9).

## 0.1.0 · 2026-10-24

First development version.

- **Plugin and local connector** for Claude Cowork, built per organization with `tools/build.py`.
- **Sign-in** with OAuth 2.0 public clients (git server, Entra ID); tokens encrypted per user.
- **Workspaces, versions, save points and pull requests** without Git installed (`workspace_*`, `version_*`).
- **Barriers** enforced in code: main branch protected, token only to the git server, HTTPS only, git hooks and
  unexpected `.git/config` entries disabled, the computer's git configuration ignored.
- **Diagnostics** (`diag_*`, validation skills, hook log) only in builds that enable them.
- **Tests** against a fake git server; **docs** for IT, security and repository owners; design decisions.
