---
type: decision
title: Decisions
description: "Why eunomai-business is built the way it is: a local connector, public sign-in clients, git without Git, configuration at build time, no project rules, no technical problem left to the user, nothing run on the user's computer, a project context that belongs to IT, a runtime IT provides, projects that bring their own capabilities, project plugins made from a template, organization rules in Claude Code's permission syntax, one recommended stack, its visual layer with a base application to clone, and new projects that IT creates from a request."
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
  would have to be published to the internet or reached through an MCP tunnel, which is Enterprise-only, by request
  and in research preview ([sources](sources.md#plugins-connectors-and-extensions)). And a remote server cannot act
  on the workspace folder on the user's computer.
- **Requires:** the desktop app open, Cowork tasks on the user's computer, and uv on every computer, deployed by
  IT ([decision 9](#9--it-provides-the-runtime-the-plugin-carries-everything-else)). A task in the cloud cannot reach
  the connector, the workspace folders or internal git servers, so the plugin refuses it
  ([barriers](barriers.md#between-claudes-sandbox-and-the-computer)).

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

## 7 · Nothing runs on the user's computer, except a preview IT turns on

The specialist never writes a launcher, a script or an installer for the user, never gives them a command, and a
save point never carries a file Windows would run on a double click. What it builds is proved in Claude's sandbox
and, for real, wherever IT runs it.

There is one exception, off by default: where IT turns it on and a project declares it, a person sees the real
application on their own computer, through the connector
([how it is held](barriers.md#the-preview-on-the-persons-computer)). Once running it belongs to a small detached
process, not to the connector: it keeps running until the person says stop or 60 minutes pass, even if the task or
Claude Desktop is closed, and the person is told so. The person keeps it open while it changes: a new version takes
the address of the one it replaces, with the data it had, and reloading the page shows it; the hour counts from the
latest version.

**What changed, and why.** This decision used to have no exception: a person tried a clickable prototype, and saw the
application through pictures from the sandbox. The product's owner decided that a person can see the real application
on their own computer, off by default and turned on by IT.

| Reason | Evidence |
|---|---|
| A person judges the real thing better than a drawing of it, and a prototype is a second thing to agree on that then differs from the application | Two business-user tests (H11, H12): the prototype worked, the "screenshots" of the application could not be used, and the user tried to click them |
| A preview cannot end with the connector, so the risk now lasts up to 60 minutes beyond the task. Nothing less shows anything: a person sees the answer after the turn, and the turn is when it would end | Cowork starts a process per turn, and the connector, a child of it, lives one turn. On 2026-11-01 the application was ready 12.5 and 11 seconds after being asked for, served a few requests, and was gone seconds after the turn ended ([H22](validation/hypotheses.md)) |
| A change is seen in the tab already open, with what the person entered, in seconds: the address, the data and the installed packages stay while nothing they depend on changed. What the application writes then outlives a version, until a stop or the hour | The goal of a person who asks for a change and checks it. Measured times are in [sources](sources.md#measured-on-real-installations) |
| The tests the sandbox cannot run, such as those in a browser, run on the person's computer too, with `app_tests`: the same barriers, a key of their own, and only a summary back | A browser the sandbox lacks, and a version proved where it will be seen. The sandbox keeps running the rest |
| The sandbox cannot show it: it has only 127.0.0.1, and no process outlives its command | Measured on 2026-11-01 ([H21](validation/hypotheses.md), failed) |
| The connector already runs on the user's computer and already uses uv | Decisions 1 and 9: nothing new is installed, nothing is written for the person to run, and every limit is enforced in code outside the sandbox |

**The risk stays.** This runs code an AI wrote and nobody has reviewed yet, on the person's computer, with their
rights, outside any sandbox. That code can do what the person can: read their files, use their network, and take
their sign-in, since a program running as them can read what DPAPI protects. The limits reduce that risk and do not
remove it: a program with those rights can undo most of them. They keep a mistake from becoming an incident; they do
not stop code written to do harm. An organization that turns this on accepts that.

**Rejected:**

| Alternative | Why not |
|---|---|
| A launcher or script in the workspace | It ran a package installation from the internet on the user's computer, outside every barrier, from a file the sandbox can rewrite |
| Asking the user to run commands, even to get past a stop | Decision 6; a business user cannot judge what a command does |
| A server in the sandbox, opened from the computer | It cannot be reached (H21) |
| Running the working folder | Anything the sandbox just wrote would run, saved or not, audited or not. It runs a copy of what was saved |
| The commands in the workspace, or in the build | The sandbox can rewrite the workspace. A build would need a new base version per project (decision 10). They are in the project's declaration, on the main branch, read from the server |
| Running commands through a shell | One string can be many commands. Each is a list of words, run as `uv run --frozen <words>` |
| On for everyone, or on by the project's word alone | Two keys, so neither an organization's build nor one project's declaration turns it on by itself |
| A container or virtual machine on the computer | It would be the real boundary, and it needs software and rights business users' computers do not have (decisions 6, 9). To look at again if Cowork offers one |

- **Consequence:** where a project has a [test environment](project-practices.md#a-test-environment-without-waiting-for-it),
  that carries none of this risk for the computer, and it stays the better place to try a version.
- **Consequence:** the specialist builds real screens early instead of a prototype where it can show them
  ([guided flows](guided-flows.md)).
- **To validate:** on a business user's computer, in Cowork ([H22](validation/hypotheses.md)).
- **Set aside for now:** Claude Managed Agents with self-hosted sandboxes, which runs the tools on the
  organization's own servers. It uses the API with an API key, so its use would be paid through the API, apart
  from the subscription (the pages read state no price); it has no user interface, so one would have to be built;
  it is in beta and not eligible for zero data retention ([sources](sources.md#plugins-connectors-and-extensions)). To look at again if an organization's
  policies block what Cowork needs, or a preview on the person's computer is not acceptable.

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

| Decided | How | Why |
|---|---|---|
| Project plugins are made from a [template](../templates/project-plugin/README.md) | IT copies it into the project, configures it, writes the project's tools in one file and builds the zip | It brings decision 10's rules built in: the dependency on eunomai-business, a hook that only denies in the project's own workspaces, tools that start from those workspaces, no secrets in the build |
| The project's tools run in a **local** server | The same way as the connector, on the user's computer | A remote server is reached from Anthropic's cloud, so the project's internal servers would have to be on the internet or behind an MCP tunnel (Enterprise, by request, research preview) ([sources](sources.md#plugins-connectors-and-extensions)) |
| A project declares its own development in **`.eunomai/project.toml`** on its main branch | `[development]`: `code`, `technologies`; read from the server, never from the folder; protected like `AGENTS.md` | One home for the permission, kept by IT through the git server; a new project needs no new build of the base |
| Real changes travel **through the git server** | A tool prepares and checks a change; the user saves it as a version; IT reviews it | No credentials to databases or deployments on users' computers |
| A **test environment** users can update without waiting for IT | `[test]` declares a branch; `version_to_test` replaces it with the user's saved version; the test server pulls it ([agent](../templates/test-environment-agent/README.md)) | Speed where it is safe: the git server decides who may (a protected branch for a team), the credentials stay on the test server, production still takes review ([how to set it up](project-practices.md#a-test-environment-without-waiting-for-it)) |

**Rejected:**

| Alternative | Why not |
|---|---|
| The project's tools as a remote server in its application | The application would have to be on the internet |
| The `projects` setting in the base | A new build of the base for every project, and the permission in two homes |
| Tools that write to the test database or deploy from the user's computer, even for a trusted profile | Credentials on laptops, and a record that stays there |
| Applying the test branch from the git server's CI with repository secrets | Anyone who can push a branch can read those secrets ([sources](sources.md#outside-claude)) |

How each part holds against misuse is in the template's and the agent's pages, and in
[barriers](barriers.md).

## 12 · Organization rules in Claude Code's permission syntax, applied by the guard

| Decided | How | Why |
|---|---|---|
| IT adds deny rules by **configuration**, in the base and in each project plugin | `deny`: `{rule, reason, examples}` in the build's configuration, packaged as data the guard reads ([how](hooks.md)) | No code to write or review for a common need; the build checks every rule against its examples |
| Rules use **Claude Code's permission syntax**, `Bash(<command>)` and `Edit(<path>)` | [Anthropic's](https://code.claude.com/docs/en/permissions) wildcards and gitignore paths, tested against its own examples; a deny errs on the side of denying, and the few differences are listed ([hooks and rules](hooks.md#where-they-differ-from-claude-codes-rules)) | One way to read a rule; they would move to `permissions.deny` with little change if that ever reaches every Cowork task |
| The **plugin's guard** applies them | `PreToolUse`, with `onFailure: "block"`, in a plugin made Required | It is the one control that reaches every Cowork task: managed settings reach only computers IT manages, server-managed settings are not read by Cowork, a plugin cannot carry permission rules, and policy mods are Claude Code only ([sources](sources.md#hooks)) |

**Rejected:**

| Alternative | Why not |
|---|---|
| Hook scripts of IT's own in the plugin | Each brings an interpreter, paths and shell differences between Windows and the cloud, the failures seen in Anthropic's open issues |
| Prompt or agent hooks as a control | Not deterministic; agent hooks are experimental |
| A central policy server called by hooks | A network dependency every tool call would wait on |
| A rule language of our own | Two ways to read the same rule, and nothing to migrate to |

- **Consequence:** the rules are guidance, not a boundary, as Anthropic says of its own: the boundaries stay the
  connector's barriers, IT's review and the network ([limits](hooks.md#limits)).

## 13 · One recommended stack: pages made on the server

| Decided | How | Why |
|---|---|---|
| Business users' applications use **one stack**: Python with FastAPI, PostgreSQL, and pages made on the server with Jinja2 and htmx | The [recommended stack](recommended-stack.md), the recommended value for `technologies` | About 25 Python packages and 3–5 copied JavaScript files, against about 200 to 590 npm packages for a React page ([measured](sources.md#measured-on-real-installations)); one language for IT to review |
| **Exact numbers** end to end | `Decimal` from the database to the page, with a decimal context above the data's precision; one formatter of the application's own; Excel rounded by the application's rules | JavaScript has no decimal type; formatting on the server keeps decimals exact without trusting the browser |
| An **organization's layer** on top | Its plugin was to hold brand variables (shadcn's names), Jinja macros with a catalogue and a skill; it is now a base application to clone ([decision 14](#14--tailwind-with-daisyui-behind-macros-the-organizations-layer-is-a-base-application)) | Every application looks like the organization's, and a component is one macro |
| **React only for IT**, case by case | Its own decision and supply-chain controls | Rich clients are sometimes needed; business users' applications do not carry npm |

**Rejected:**

| Alternative | Why not |
|---|---|
| React, TypeScript and shadcn/ui as the base | Hundreds of npm packages, where the largest supply-chain attacks of 2025 and 2026 happened (one published 84 malicious versions of 42 TanStack packages); decimals to protect in the browser |
| Two tracks of equal standing | Every component twice, and npm in every application |
| Web Components as the shared layer | A library IT cannot maintain, or a paid one (Web Awesome's data grid and charts are in its paid Pro edition) |
| Streamlit, NiceGUI, Reflex, Dash | Their own look and state model; Reflex builds a Node front end underneath |

- **Consequence:** the application and organization-plugin templates became one base application to clone
  ([decision 14](#14--tailwind-with-daisyui-behind-macros-the-organizations-layer-is-a-base-application)), validated
  on the first application that uses it ([open checks](recommended-stack.md#open-checks)).

## 14 · Tailwind with daisyUI behind macros; the organization's layer is a base application

| Decided | How | Why |
|---|---|---|
| **Tailwind with daisyUI** is the recommended visual layer | Tailwind CSS 4 and daisyUI 5, both MIT, behind Jinja macros: screens call macros, so an organization can replace the layer without touching a screen | Components free to customise: a utility overrides a component without fighting global styles, and a theme is a set of variables |
| **No Node and no npm** for it | Tailwind's standalone executable and daisyUI's two files, each pinned by version and hash ([recommended stack](recommended-stack.md#the-stylesheet), [sources](sources.md#recommended-stack)) | The npm, Node and React rules of [decision 13](#13--one-recommended-stack-pages-made-on-the-server) stay as they are: business users' applications do not carry npm |
| **The generated CSS is committed** | Generated wherever templates change: a developer's computer, the assistant's sandbox, CI | Servers need neither Node nor the executable, and a business user runs nothing ([decision 7](#7--nothing-runs-on-the-users-computer-except-a-preview-it-turns-on)). The executable ran in a real local Cowork sandbox ([measured](sources.md#measured-on-real-installations)) |
| **Colours exist only in the organization's theme** | Tailwind's own palette is removed; a test refuses invented values such as `bg-[#ff0000]` | Removing the palette takes `bg-red-500` away but not an arbitrary value, so the test closes what is left |
| The organization's layer is a **base application to clone**, not a plugin holding components | `business-app-base`, a separate repository: an organization clones it once and adds its brand, then clones that per application and deletes the demo | Each organization and application can change anything, with nothing to stay tied to |

**Rejected:**

| Alternative | Why not |
|---|---|
| Bootstrap | Not for a build or an npm tree: it is published compiled. Its global styles force custom classes for anything different, a judgement from experience, not a measurement |
| Every component written by hand | All their behaviour and accessibility to maintain |
| Tailwind or daisyUI through npm | Business users' applications do not carry npm, and the executable does the same job without it |
| Generating the stylesheet on the server | The server would need the executable |
| Components as a package, in a plugin or published by tag or registry | Updates would reach everyone, but it ties applications to the package and limits what they can change (Gitea's registry hosts Python, GitHub Packages does not) |
| The paid parts of Tailwind and daisyUI: Tailwind Plus, daisyUI's store, Blueprint MCP | Not needed: for component classes, assistants have daisyUI's official `llms.txt` |

- **Consequence:** the brand's variables use daisyUI's names, not shadcn's; how they map for a React application of
  IT's is settled with that application.
- **Consequence:** there is no update mechanism: when the base improves, an application compares versions and takes
  what it wants.
- **Consequence:** generating the stylesheet in Cowork needs the sandbox to download the executable, under the
  organization's network settings, and has been shown on one sandbox only. Where it cannot, a developer's computer
  or CI generates it, as a case for IT ([decision 6](#6--the-user-never-resolves-a-technical-problem)).
- **Consequence:** `dependency_audit` reads `uv.lock` and `vendor.json` as well as `requirements*.txt` and
  `package-lock.json`, by the same rules and with no library named in them
  ([barriers](barriers.md)).

## 15 · A business person never creates a repository

When someone wants a new application and no project exists, the specialist understands the idea in conversation, with
no repository and no files written, and the connector turns it into a request for IT. IT creates the repository from
the organization's template; the person comes back, the specialist clones it and carries on from the request.

| Step | Who | What |
|---|---|---|
| 1 Understand | The specialist, in conversation | Goal, users, how it is done today, what the first version includes, open questions. Nothing is written anywhere |
| 2 Request | The connector prepares it, the person sends it | `project_request` builds a message with a fixed format, in the organization's documentation language (`docs_language`: Spanish, Catalan or English, otherwise English): a suggested name, what it is for, who will use it, what was understood and the open questions. It returns an e-mail link to `support_email` and the same text to copy, and keeps a copy on the person's computer. Nothing is sent automatically |
| 3 Create | IT | A repository from the organization's template, with `main` protected ([how](project-practices.md#creating-a-project-from-the-template)). IT decides the name |
| 4 Carry on | The specialist, in the same task or a new one | `workspace_list` lists the pending request; once the person says the project exists, the specialist clones it, seeds the first proposal from the request, so Understand is not asked again, and marks the request done with `project_request_done`. It is kept, not deleted |
| Or withdraw it | The person, through the specialist | When IT refused it or the person changed their mind, `project_request_withdraw` marks it withdrawn: kept, and no longer asked about at the start of a session |

**Why.**

| Reason | Evidence |
|---|---|
| IT controls which projects exist and what they are called | A repository is where permissions, protection, review and the project's context live ([decisions 8](#8--the-projects-context-belongs-to-it) and [10](#10--a-base-that-holds-for-everyone-projects-bring-their-own-capabilities)); each one is IT's to run |
| The person does not wait for the part that needs no code | Understand happens while the request is with IT, and the request carries it, so nothing is asked twice |
| Asking IT is a sentence the person already knows how to send | [Decision 6](#6--the-user-never-resolves-a-technical-problem): the specialist never offers to create a repository and never asks the person to do anything technical with IT beyond sending the prepared request |

**Rejected:**

| Alternative | Why not |
|---|---|
| The connector creates the repository from the template, as the person | Gitea's documentation of [template repositories](https://docs.gitea.com/usage/repository/template-repositories/) and of [generating from one](https://docs.gitea.com/api/1.24/operations/generate-repo/) does not say which permission the caller needs, nor whether new repositories get a default protection; a repository nobody protected would take changes to `main` directly. To look at again once a real Gitea shows both ([H24](validation/hypotheses.md)) |
| The specialist sends the request itself | Nothing leaves the computer in the person's name without them seeing it; an e-mail link is the way stops already reach IT |
| Writing the Understand summary into a folder before the project exists | A folder that is not a workspace has no versions, no barriers and no place in the registry; the connector's own folder holds the request instead |

- **Consequence:** a request is a file in the connector's folder, pending, done or withdrawn, and never deleted
  ([data on computers](data-on-computers.md#on-the-users-computer)); the same name while it is pending replaces it.
- **Consequence:** the subject always starts `eunomai-business:`, whatever the language, so a mailbox rule can
  recognise a request; the person's own words are never translated.
- **Consequence:** without `support_email` the person copies the text and sends it to IT as they usually do.
