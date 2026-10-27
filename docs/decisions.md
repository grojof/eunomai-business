---
type: decision
title: Decisions
description: "Why eunomai-business is built the way it is: a local connector, public sign-in clients, git without Git, configuration at build time, no project rules, no technical problem left to the user, nothing run on the user's computer, a project context that belongs to IT, a runtime IT provides, projects that bring their own capabilities, and project plugins made from a template."
tags: [decisions, architecture]
audience: [it, developers]
related: [architecture.md, sources.md]
---

# Decisions

Why eunomai-business is built this way, and what was rejected. The official sources and measurements behind
each decision are in [sources and evidence](sources.md).

## 1 · A local connector on the user's computer

The plugin ships an MCP server that Claude Desktop starts on the user's computer for each session (stdio, `uv run`,
per user, no administrator rights). It runs outside Claude's sandbox, with the user's network, certificate store
and browser; hence the [barriers](barriers.md).

- **Rejected:** a remote connector. Claude calls remote connectors from Anthropic's cloud, so internal servers
  would have to be published to the internet.
- **Requires:** the desktop app open, Cowork tasks on the user's computer until check H16 shows the cloud works
  too, and uv on every computer, deployed by IT ([decision 9](#9--it-provides-the-runtime-the-plugin-carries-everything-else)).

## 2 · Public sign-in clients, tokens encrypted per user

Every sign-in is an OAuth 2.0 public client (authorization code with PKCE, system browser, loopback redirect). No
secret or certificate ships anywhere. Tokens are kept per user and per provider, encrypted (DPAPI file on
Windows, OS keyring elsewhere), and never reach Claude.

- **Rejected:** confidential clients (the secret would ship to every computer); the Windows Credential Manager
  (2,560-byte cap per credential; an Entra ID token set is about 5 KB).
- **Limits:** DPAPI stops other users, not software running as the same user. Signing out does not revoke
  tokens on the server.

## 3 · Git inside the connector, independent of any Git on the computer

The connector uses dulwich (pure-Python git), pinned to a version at least two weeks old with no known
vulnerabilities, and ignores the computer's git configuration. Business users' computers have no Git; developers'
computers have Git with settings of their own (Git for Windows's `core.autocrlf=true` turned checkouts into CRLF).

- **Rejected for now:** requiring Git for Windows (installation, varying settings). **To reconsider before 1.0:**
  MinGit, a portable Git distributed per user.
- **Consequence:** dulwich runs some hooks whatever it is told, so the connector disables them all itself.
- **No line-level merging:** combining two edits of the same file needs a merge library, and two edits that do
  not collide as text can still break each other. The connector combines only changes to different files; the
  rest goes to IT.

## 4 · Configuration at build time, by IT

Everything that varies between organizations is set by IT in one file and built into the plugin
([configuration](configuration.md)). Users configure nothing. Diagnostics ship only when the build enables them.

- **Rejected:** per-user settings (breaks "install and sign in").
- **Consequence:** a configuration change means rebuilding and publishing the plugin; the zip carries internal
  host names and stays inside the organization.

## 5 · The plugin manages no project rules

eunomai-business enforces its own barriers only. Its file guard refuses to save the files that steer Claude or run
on the user's computer ([decision 8](#8--the-projects-context-belongs-to-it)); it writes no rule into a project. Rules for a project's files (line endings, ignored files) are
[good practices](project-practices.md) owned by the project, valid for any git hosting. Project-specific rules for
Claude go in a project plugin ([architecture](architecture.md#plugin-per-project)).

- **Rejected:** managed blocks in each project's `.gitattributes` and `.gitignore` (mixes the plugin's logic
  into every repository and needs maintenance in each).

## 6 · The user never resolves a technical problem

Business users do not handle git, merges or errors. Each situation is either resolved by the connector on its own,
with certainty and without losing anything, or the connector stops, keeps the user's work, tells the user in
plain words, and hands IT a report with an e-mail link ready to send ([barriers](barriers.md#when-the-connector-stops)).

- **Rejected:** asking business users to resolve conflicts or read error messages; resolving doubtful cases
  automatically "most of the time".
- **Consequence:** the rules for projects and for the connector aim to make stops rare; every stop is a case for
  IT, never a dead end for the user.

## 7 · Nothing runs on the user's computer

What the specialist builds is tried in Claude's sandbox and, for real, wherever IT runs it. The user tries a
clickable prototype in the browser before anything is built, and sees the application through screenshots and
results from the sandbox. The specialist never writes a launcher, a script or an installer for the user, never
gives them a command, and a save point never carries a file Windows would run on a double click.

- **Rejected:** a launcher in the workspace so the user can try the application (it ran a package installation
  from the internet on the user's computer, outside every barrier); asking the user to run commands, even to get
  past a stop.
- **Consequence:** trying the real application needs a place IT provides (a preview environment per proposal is
  the natural next step); until then, the prototype and the sandbox's evidence carry the review.

## 8 · The project's context belongs to IT

The specialist's context comes from IT, not from each user's session: the organization's (build configuration)
and the project's (an `AGENTS.md` on the main branch, read by the connector from there). Claude never writes it,
and a save point never carries a change to it.

- **Rejected:** relying on Cowork reading the folder's `CLAUDE.md` (not documented for Cowork) or on each user
  setting up a Cowork project with instructions (unreliable for the least technical user).
- **Consequence:** the connector reads the context from the server each time it is asked, never from the folder
  or from references the sandbox could rewrite. Organizations on Team and Enterprise back this with one line of
  organization instructions, which take precedence over a user's own
  ([configuration](configuration.md#whose-context-counts)).

## 9 · IT provides the runtime; the plugin carries everything else

eunomai-business is one plugin: the specialist and `review-skills` (skills), the file guard (a hook) and the
connector (a local MCP server). The connector runs on uv, which IT deploys on every computer with its own software
management, at a version it fixes. uv then runs the locked packages, hashes verified, on its own Python 3.12
(`--managed-python`), never on whatever Python the computer has. Business users install nothing themselves.

**Why one plugin.** The plugin is the unit Anthropic builds for: plugins "are the main way to build third-party
extensions for Claude" ([Build plugins for Claude](https://claude.com/blog/build-plugins-for-claude)), and "When you
build for people who use Claude, you build a plugin"
([what to build](https://claude.com/docs/connectors/building/what-to-build)). Only a plugin carries skills and hooks,
and only a plugin gives the organization **Required**, per-group availability (Enterprise), version history and
rollback ([plugins admin](https://claude.com/docs/plugins/admin)).

**Why IT deploys uv.** Claude Desktop lends a runtime only to standalone desktop extensions (MCPB): their Node, or,
for the `uv` type, a uv it downloads at installation. A plugin's local server gets none: its command must already be
on the computer. Measured in Cowork on 2026-10-26: without uv, the plugin's server does not start
([research](../research/mcpb-uv/README.md)). No organization policy changes that
([enterprise configuration](https://support.claude.com/en/articles/12622667-enterprise-configuration-for-claude-desktop)).
Deploying one executable is routine for IT, keeps its version under IT's control and needs no download from
GitHub on users' computers.

**Rejected, after testing:**

| Alternative | Why not | Evidence |
|---|---|---|
| A Node.js connector, on Claude Desktop's Node | A plugin's server gets no Node from Claude Desktop; the JavaScript git library's tree fails this project's dependency rules | [Node research](../research/node-connector/README.md), 2026-10-25 |
| The connector as a separate MCPB extension of type `uv`, next to the plugin | It works and needs no uv installed, but: two pieces; the extension can only be made available (allowlist), each member installs it and can turn it off, and "users will need to install updated .mcpb files manually" ([local MCP servers](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)); the guard would become an `mcp_tool` hook, which lets writes through when the extension is down; Desktop picks the uv (a computer's own first, otherwise its 0.9.7, which uv's own advisories list as affected by five vulnerabilities, one high: [GHSA-hq85-5cpj-mr62](https://github.com/astral-sh/uv/security/advisories/GHSA-hq85-5cpj-mr62)) and nothing can force it ([mcpb#203](https://github.com/modelcontextprotocol/mcpb/issues/203)) | [MCPB research](../research/mcpb-uv/README.md), 2026-10-26 |
| The MCPB bundle inside the plugin (`"mcpServers": "./server.mcpb"`) | Documented ([manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference)) and listed for Cowork ([platform support](https://claude.com/docs/plugins/platform-support)), but in Cowork the bundle was never extracted or started | [MCPB research](../research/mcpb-uv/README.md), 2026-10-26 |

**Where Anthropic is heading, as of 2026-10-26.** Plugins are the distribution unit: desktop-extension listings in
the directory "are deprecated, and the directory no longer accepts local servers packaged as MCP Bundles (MCPB). To
distribute a local server through the directory, include it in a plugin"
([submission](https://claude.com/docs/connectors/building/submission.md)). MCPB stays for private distribution and
is, in Anthropic's own skill, "the sanctioned way to distribute local MCP servers", "packaged with its runtime"
([build-mcpb skill](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/mcp-server-dev/skills/build-mcpb/SKILL.md)).
The two meet in a plugin that carries a `.mcpb`, which is the variant that does not run in Cowork yet. The MCPB
repository's last release is v2.1.2 (2025-12-04) and its last commit 2026-04-22.

- **Consequence:** IT's deployment includes uv, at a fixed version and an absolute path in the build
  ([configuration](configuration.md#installing-uv-in-an-organization)); `--system-certs` and `--managed-python` make
  its behaviour the same on every computer.
- **To look at again** when a `.mcpb` inside a plugin runs in Cowork with its runtime managed by Claude Desktop,
  or when plugins get Desktop's runtime: the connector would then ship as that bundle, unchanged, and IT would no
  longer deploy uv. The research spikes stay under `research/` to repeat the tests.

## 10 · A base that holds for everyone; projects bring their own capabilities

eunomai-business carries only what holds for every organization and every project: the specialist and its rules,
the connector (sign-in, workspaces, versions and their barriers, proposals, IT's review, the dependency audit) and
the file guard (executables, the project's context, the repository's configuration). IT configures what varies by
organization: languages, the organization's context and skills, sign-in providers, allowed technologies. It holds
no project's rules (one setting per repository remains for now: see the consequences).

What a project needs beyond that belongs to the project:

| Need | Where | Why there |
|---|---|---|
| Context, domain rules and limits; which project skills and tools to use, and for what | The project's `AGENTS.md` on the main branch, kept by IT ([decision 8](#8--the-projects-context-belongs-to-it)) | The specialist already reads it from the server and puts it before everything but its own rules |
| Who may approve which changes | The git server: protected branch, required reviews, code owners | The only real permission: it holds for everyone, inside Cowork or not |
| Tools and data (query, simulate, create a field in a test database), procedures that use them, hooks for its own folders | A **project plugin** that depends on eunomai-business, made from a template | Capabilities are code: they cannot live in a text file, and they are not every organization's |

**Why this split.**
- A capability is made safe by the capability itself: a tool that changes data enforces its own limits (test
  environment only, allowed operations, a simulation first, a versioned change that IT reviews). A hook prevents
  mistakes; it does not make a dangerous tool safe.
- A project plugin's hook cannot turn eunomai-business's deny into an allow: "When multiple PreToolUse hooks return
  different decisions, precedence is `deny` > `defer` > `ask` > `allow`"
  ([hooks reference](https://code.claude.com/docs/en/hooks)).
- On Team a plugin cannot be limited to a group ("Group access…" is Enterprise only,
  [plugins admin](https://claude.com/docs/plugins/admin#limit-to-user-groups-on-enterprise)), so whoever has a
  project plugin may work on other projects too.

**Rules for a project plugin**, checked by IT before it is published (`review-skills` covers skills and hooks):
- its hooks act only in its own project's workspaces, judged by the repository, not by who has the plugin;
- its hooks only deny: never `allow` with a rewritten input (`updatedInput`), which the documentation does not say
  the other hooks check again;
- its tools enforce their own limits, because eunomai-business's guard does not watch them;
- it declares eunomai-business in `dependencies`.
- Plugins declare the plugins they need (`dependencies`,
  [manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference#dependencies)). How Cowork
  resolves one for a plugin uploaded to an organization is not documented. With a member's own upload, a bare name
  works and the project plugin does not load while eunomai-business is off (H10, 2026-10-27,
  [research](../research/project-plugin/README.md)); the organization's upload is still to check.

**Rejected:**

| Alternative | Why not |
|---|---|
| Per-project path rules in eunomai-business's configuration, applied by its guard and its save | One rule in two homes (prose in `AGENTS.md`, a list in the build), a new base version for every project change, and still not a permission: the git server is |
| One self-contained plugin per project, without eunomai-business | Each would repeat sign-in, git, barriers and the specialist, and drift from them |

- **Consequence:** the `projects` setting (code allowed and technologies per repository) was the base's last
  project-specific setting; each project now declares that itself ([decision 11](#11--project-plugins-from-a-template-a-project-declares-its-own-development)).
- **Consequence:** on Team, a project plugin is either Required for everyone (every user loads every project's
  plugin) or one members can turn off. Turning it off removes the project's capabilities and its extra hooks, not
  safety: eunomai-business stays Required, the tools carry their own limits and the git server keeps the
  permission.

## 11 · Project plugins from a template; a project declares its own development

Decided 2026-10-27.

- **A template** (`templates/project-plugin/`, [how to use it](../templates/project-plugin/README.md)). IT copies it
  into the project's repository, configures it, writes the project's tools in one file and builds the zip. What
  decision 10 requires of a project plugin comes with it:
  - it depends on eunomai-business;
  - its hook only denies, and only in the workspaces eunomai-business registered as cloned from the project's
    repositories;
  - every tool starts from the project's own workspaces;
  - the build refuses obvious secrets in its settings.
- **A local server, not a remote one.** "Claude connects to your remote MCP server from Anthropic's cloud
  infrastructure, rather than from your local device… This is true across every Claude client, including
  claude.ai, Claude Desktop, Cowork"; such a server "must be reachable over the public internet"
  ([custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)).
  A plugin's remote server is connected from its *Connectors* tab in Cowork
  ([platform support](https://claude.com/docs/plugins/platform-support)); where that connection starts is not
  documented separately. Internal servers stay off the internet, so the project's server runs on the user's
  computer, like the connector: a plugin's local server "Loads when the Cowork session runs on your computer"
  (same page). The support article's note that servers in `claude_desktop_config.json` "aren't available in
  Cowork" is about that file, not about plugins.
- **A project declares its own development** in `.eunomai/project.toml` on its main branch:

  ```toml
  [development]
  code = true                                  # the specialist may write code here
  technologies = ["Python", "HTML, CSS and JavaScript"]   # empty: any
  ```

  The connector reads it from the server in the same fetch as `AGENTS.md`, never from the folder; the guard keeps
  Claude from writing `.eunomai/`, and a save puts it back. The declaration decides; a project without a
  `[development]` section is left to the build's `free_development`; if the server cannot be reached, no code is
  written. It replaces the `projects` setting: a new project no longer needs a new build of the base, and the
  permission has one home, the project's repository, changed by IT through the git server.
- **Real changes travel through the git server.** A project's tool prepares and checks a change in the workspace
  (a migration, a field's definition); the user saves it as a version; IT reviews it; the project's CI applies it.
- **Next: a profile that works in the test environment without waiting for IT.** A user whom IT puts in a team of
  the git server updates the project's test branch with their version; the project's CI applies it to the test
  environment at once, with credentials only the server holds; production still takes IT's review. Gitea limits
  who may push, and who may force-push, to a protected branch by team (`push_whitelist_teams`,
  `force_push_allowlist_teams`, Gitea 1.27.1 API). It will be declared in a `[test]` section of the same file, and
  blocks only clear cases: production, deleting data, secrets, another project.

**Rejected:**

| Alternative | Why not |
|---|---|
| The project's tools as a remote server in its application | Reached from Anthropic's cloud: the application would have to be on the internet |
| The `projects` setting in the base | A new build of the base for every project, and the permission in two homes |
| Tools that write to the test database or deploy from the user's computer | Credentials on every computer that runs them, and a record that stays there |
| For the profile that works without waiting: its own credentials on its computer | The same: a secret on a laptop. The test branch gives the same speed with the credentials on the server |

- **Consequence:** a build whose configuration still has `projects` stops with a message; IT moves each entry to
  that project's `.eunomai/project.toml`.
- **Consequence:** a project plugin tells its workspaces by eunomai-business's register of workspaces (written on
  the user's computer when each one is cloned, out of the sandbox's reach), never by `.git/config`, which the
  sandbox can rewrite. The register's shape is now shared with project plugins. Like every hook, theirs prevent
  mistakes; the permission is the git server's.
- **Consequence:** a project plugin's hook runs with Python's standard library only, so it does not depend on
  installing anything; set to block when it cannot run, a damaged project plugin stops writes until IT fixes it.
