---
type: explanation
title: Architecture
description: "How eunomai-business is split into plugin, local connector and build tool, what is generic and what depends on the git hosting, and what is planned."
tags: [architecture, git, sign-in]
audience: [it, developers]
related: [decisions.md, barriers.md]
---

# Architecture

How eunomai-business is split, what is generic and what depends on a particular server. Each part is marked
**built** or **planned**.

## At runtime

Three places are involved. Claude works inside Cowork's sandbox; the local connector runs on the user's
computer, outside it; the organization's servers stay inside the corporate network. The workspace folder is the
only thing the sandbox and the connector share.

```mermaid
flowchart LR
    user([Business user])
    subgraph computer["User's computer"]
        subgraph sandbox["Cowork sandbox"]
            claude["Claude<br/>file tools, shell"]
        end
        workspace[("Workspace folder<br/>clone of the repository")]
        connector["Local connector<br/>sign-in, versions, barriers"]
        store[("Encrypted sign-in records")]
        browser["Browser"]
    end
    subgraph org["Organization's network"]
        idp["Identity provider<br/>Entra ID, git server"]
        git["Git server"]
    end
    reviewer([IT reviewer])

    user --> claude
    claude -- "edits files" --> workspace
    claude -- "MCP tools" --> connector
    connector -- "saves, sends" --> workspace
    connector --> store
    connector -- "opens sign-in" --> browser
    browser --> idp
    connector -- "HTTPS, user's token" --> git
    reviewer -- "reviews pull requests" --> git

    classDef action fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef safeguard fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef data fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef external fill:#f3f4f6,stroke:#6b7280,color:#111827
    class claude,browser action
    class connector safeguard
    class workspace,store data
    class idp,git external
```

## How a version reaches a pull request

The user asks for a change in plain language; Claude edits the files and calls the connector, which does every
git operation and enforces the barriers.

```mermaid
sequenceDiagram
    actor User as Business user
    participant Claude as Claude (Cowork)
    participant Connector as Local connector
    participant Git as Git server
    actor IT as IT reviewer

    User->>Claude: Describe the change
    Claude->>Connector: version_create
    Note over Connector: never on the main branch
    Claude->>Claude: Edit files in the workspace
    Claude->>Connector: version_save
    Note over Connector: hooks off, .git/config checked
    Claude->>Connector: version_send
    Connector->>Git: Push the version (HTTPS, user's token)
    Claude->>Connector: version_propose
    Connector->>Git: Open the pull request
    Git-->>IT: Review, then merge into main
```

## Bringing the latest changes

`workspace_update` decides on its own, and stops whenever it is not certain. The full rules are in
[barriers.md](barriers.md#bringing-the-latest-changes).

```mermaid
flowchart TD
    start([workspace_update]) --> keep["Save unsaved changes<br/>(new version if on main)"]
    keep --> fetch["Fetch the server's branches"]
    fetch --> where{"On the main branch?"}
    where -- yes --> ff{"Fast-forward<br/>possible?"}
    ff -- yes --> moved["Back up, then move to the<br/>latest main branch"]
    ff -- no --> stop
    where -- no --> accepted{"Version accepted?<br/>in main, or its PR merged"}
    accepted -- yes --> retire["Back up, back to the main<br/>branch, retire the version"]
    accepted -- no --> clean{"Combines without<br/>conflicts?"}
    clean -- yes --> combine["Back up, add the latest<br/>main changes to the version"]
    clean -- no --> stop["Stop: nothing changes<br/>user message + report for IT"]

    classDef action fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decision fill:#f3e8ff,stroke:#9333ea,color:#581c87
    classDef safeguard fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef halt fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    class keep,fetch action
    class where,ff,accepted,clean decision
    class moved,retire,combine safeguard
    class stop halt
```

## Sign-in

Once per provider, and again only if the stored record is lost or revoked. Refreshing an expired token needs no
browser.

```mermaid
sequenceDiagram
    participant Connector as Local connector
    participant Browser
    participant IdP as Identity provider

    Connector->>Browser: Open the authorization page (PKCE challenge, state)
    Browser->>IdP: User signs in (single sign-on when available)
    IdP-->>Browser: Redirect to 127.0.0.1 or localhost with a code
    Browser->>Connector: Code and state, on the loopback port
    Connector->>IdP: Exchange the code with the PKCE verifier
    IdP-->>Connector: Access and refresh tokens
    Note over Connector: stored encrypted per user and provider, never shown to Claude
```

## Pieces

| Piece | What it is | Status |
|---|---|---|
| Plugin (`plugin/`) | What Claude Desktop installs: the connector's launch settings, plus validation skills and hooks when diagnostics are on. Built per organization from its configuration | Built |
| Local connector (`connector/`) | A Python program started with `uvx` on the user's computer. Claude talks to it through MCP; it runs outside Claude's sandbox ([decision 1](decisions.md#1--a-local-connector-on-the-users-computer)) | Built |
| Build tool | `tools/build.py`: organization configuration + source → `eunomai-business.zip`, after validating the configuration | Built |
| Tests | `connector/tests/`: sign-in, workspaces, versions, barriers, build and tool list against a fake git server (`uv run --group dev pytest` in `connector/`) | Built |

## Connector modules

| Module | Does | Depends on |
|---|---|---|
| `auth` | Sign-in with any OAuth 2.0 provider (authorization code + PKCE, loopback redirect), token refresh | Standard OAuth 2.0; nothing server-specific |
| `store` | Keeps sign-in records encrypted per user | The operating system (DPAPI on Windows, keyring elsewhere) |
| `gitops` | Workspaces, versions, save points, sending, pull requests | Standard git over HTTPS (dulwich), except two Gitea-specific parts below |
| `server` | Exposes the tools to Claude (MCP over stdio): `sign_in_*`, `whoami`, `sign_out`, `workspace_*`, `version_*`; `diag_*` only with diagnostics. Turns every stop into a plain message for the user and a report for IT | MCP |
| `support` | The stop: the user's message, IT's report, the e-mail link | — |
| `hook` | Entry point for the plugin's hooks; today it only logs, with diagnostics on | — |
| `probe` | Diagnostic measurements (`diag_environment`, `diag_reach`) | — |

## Facts the design relies on

- **The workspace is named by its path.** Under the current MCP protocol (`2026-07-28`) the client does not share
  its folders with the connector (roots are deprecated), so the connector cannot discover the folder selected in
  Cowork. It keeps workspaces in its own folder and returns their path; in a local Cowork session on Windows,
  Claude's file tools and the connector see the same path.
- **Per-user data lives in `%LOCALAPPDATA%\eunomai-business`**, not in `CLAUDE_PLUGIN_DATA`, which points inside
  each task's folder and does not outlive the task.

## What is tied to a git hosting

| Part | Today | Generic? |
|---|---|---|
| Clone, send, branches, save points | Standard git over HTTPS | Yes |
| Git sign-in | OAuth 2.0 public client with PKCE; user endpoint and login field configurable | Yes in principle; tested only with Gitea |
| Sending the token | HTTP basic auth (login + OAuth token) | Works with Gitea; to be checked per hosting |
| Pull request, its merged state, and branch link | Gitea API (`/api/v1/repos/.../pulls`) and Gitea web paths | **No**: Gitea only; without it, an accepted version is recognized only by its history (not after a squash merge) |
| Check that the token only goes to the git host | Compares the repository's origin (scheme, host, port) with the `userinfo_url` origin | Works when both share an origin (Gitea); GitHub uses a separate API host |

**Planned:** a hosting adapter per server type (Gitea first, then GitHub and GitHub Enterprise), chosen in the
organization's configuration. Only the hosting-specific rows above move into it.

## Hooks

**Built:** hooks run on the user's computer in Cowork (SessionStart and PreToolUse), through Git Bash if
installed. Today they only log, for measurement, and ship only with diagnostics on.

**Planned: file guard.** A PreToolUse hook that stops Claude from reading or writing sensitive files on the
user's behalf:

- **Base rules shipped with the plugin**, in two kinds:
  - *fixed*: protect eunomai-business itself, such as no writing inside `.git`, which backs the connector's
    sandbox barriers ([barriers.md](barriers.md)); no configuration removes them;
  - *defaults*: common sensitive files (`.env`, keys, certificates, credential files).
- **Organization rules** added in the build configuration: more paths or patterns to deny or to ask about.
  Organizations extend the defaults; they cannot remove the fixed rules.

Before it is built, validation must show (check H9 in
[validation/hypotheses.md](validation/hypotheses.md)):

- the hook receives the tool's input in Cowork (the file path, the shell command);
- a *deny* answer really stops the tool;
- the hook is quick enough to run on every tool call;
- it works without Git on the computer.

**Limits, stated now:** a hook sees a shell command as text. Reading a file by path is easy to catch; a command
built to hide it is not. The guard reduces mistakes and casual exposure; the real boundary for secrets is not
putting them where Claude works. And if the hook cannot start (uv missing, for example), Claude Desktop
treats it as an error and the tool call goes ahead. That limit has to be measured and documented, not assumed.

## Plugin per project

**Planned:** a base plugin (`eunomai-business`) plus one plugin per project for its own skills and knowledge,
sharing the base connector. How one plugin relies on another in Cowork is not yet tested (check H10 in
[validation/hypotheses.md](validation/hypotheses.md)).

A project plugin is also where **project-specific guard rules** would go (for example, "this module is
maintained by another team"), possibly per group of the organization's directory, using the base plugin's
guard. That keeps them out of the project's files and out of the base plugin. Like every hook, these rules
prevent mistakes; they are not permissions (see
[project-practices.md](project-practices.md#who-can-read-and-change-what)).
