# Changelog

## Unreleased

- **Decision 14, the visual layer and the organization's layer:** corrects the recommended stack, which refused
  Tailwind and Bootstrap for bringing a build or an npm tree. Neither needs an npm tree: Bootstrap is published
  compiled, and Tailwind's stylesheet is built by a standalone executable, with daisyUI's files. Tailwind with
  daisyUI is now the recommended layer, behind Jinja macros so an organization can replace it, with the generated CSS committed and colours only in
  the organization's theme. Bootstrap stays rejected, for its global styles. The organization's layer is a base
  application to clone (`business-app-base`), not a plugin holding components. The npm, Node and React rules do not
  change. `dependency_audit` does not read `uv.lock` or `vendor.json` yet. To validate in Cowork: H20, H21.
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
