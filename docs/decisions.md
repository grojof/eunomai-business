---
type: decision
title: Decisions
description: "Why eunomai-business is built the way it is: a local connector, public sign-in clients, git without Git, configuration at build time, no project files, and no technical problem left to the user."
tags: [decisions, architecture]
audience: [it, developers]
related: [architecture.md]
---

# Decisions

Why eunomai-business is built this way, and what was rejected.

## 1 · A local connector on the user's computer

The plugin ships an MCP server that Claude Desktop starts on the user's computer for each session (stdio, `uvx`,
per user, no administrator rights). It runs outside Claude's sandbox, with the user's network, certificate store
and browser; hence the [barriers](barriers.md).

- **Rejected:** a remote connector. Claude calls remote connectors from Anthropic's cloud, so internal servers
  would have to be published to the internet.
- **Requires:** Cowork running on the user's computer, and `uv` installed once per user.

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

## 4 · Configuration at build time, by IT

Everything that varies between organizations is set by IT in one file and built into the plugin
([configuration](configuration.md)). Users configure nothing. Diagnostics ship only when the build enables them.

- **Rejected:** per-user settings (breaks "install and sign in").
- **Consequence:** a configuration change means rebuilding and publishing the plugin; the zip carries internal
  host names and stays inside the organization.

## 5 · The plugin never manages files in a project

eunomai-business enforces its own barriers only. Rules for a project's files (line endings, ignored files) are
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
