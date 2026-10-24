---
type: decision
title: Decisions
description: "Why eunomai-business is built the way it is: a local connector, public sign-in clients, git without Git, configuration at build time, no project rules, no technical problem left to the user, nothing run on the user's computer, and a project context that belongs to IT."
tags: [decisions, architecture]
audience: [it, developers]
related: [architecture.md]
---

# Decisions

Why eunomai-business is built this way, and what was rejected.

## 1 · A local connector on the user's computer

The plugin ships an MCP server that Claude Desktop starts on the user's computer for each session (stdio, `uv run`,
per user, no administrator rights). It runs outside Claude's sandbox, with the user's network, certificate store
and browser; hence the [barriers](barriers.md).

- **Rejected:** a remote connector. Claude calls remote connectors from Anthropic's cloud, so internal servers
  would have to be published to the internet.
- **Requires:** the desktop app open, Cowork tasks on the user's computer until check H16 shows the cloud works
  too, and `uv` installed once per user.
- **Considered: a Node.js connector** (2026-10-25), to remove uv and Python from users' computers. Not now: a
  plugin's local server gets no Node from Claude Desktop (only MCPB extensions do), and the JavaScript git library's
  package tree fails this project's dependency rules
  ([research](../research/node-connector/README.md)). To look at again if plugins get Desktop's runtime.

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
