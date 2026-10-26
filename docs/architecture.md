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
    where -- no --> saved{"Anything saved<br/>in the version?"}
    saved -- no --> moved
    saved -- yes --> accepted{"Version accepted?<br/>in main, or its PR merged"}
    accepted -- yes --> retire["Back up, back to the main<br/>branch, retire the version"]
    accepted -- no --> clean{"No file changed<br/>on both sides?"}
    clean -- yes --> combine["Back up, add the latest<br/>main changes to the version"]
    clean -- no --> stop["Stop: nothing changes<br/>user message + report for IT"]

    classDef action fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decision fill:#f3e8ff,stroke:#9333ea,color:#581c87
    classDef safeguard fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef halt fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    class keep,fetch action
    class where,saved,ff,accepted,clean decision
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
| Plugin (`plugin/`) | What Claude Desktop installs: the connector's launch settings, the `specialist` and `review-skills` skills and the file guard hook, plus validation skills and measurement hooks when diagnostics are on. Built per organization from its configuration | Built |
| Local connector (`connector/`) | A Python program started with `uv run --frozen` on the user's computer. Claude talks to it through MCP; it runs outside Claude's sandbox ([decision 1](decisions.md#1--a-local-connector-on-the-users-computer)) | Built |
| Build tool | `tools/build.py`: organization configuration + source → `eunomai-business.zip`, after validating the configuration | Built |
| Bill of materials | `tools/sbom.py` → `connector/sbom.cdx.json`, regenerated whenever `connector/uv.lock` changes | Built |
| Maintenance | GitHub workflows: tests on every pull request (Linux, Windows); daily dependency update (`tools/update_dependencies.py`) | Built |
| Tests | `connector/tests/`: sign-in, workspaces, versions, updates, barriers, the file guard, the dependency check and audit, the hooks, the build and the tool list, against a fake git server (`uv run --frozen --group dev pytest` in `connector/`) | Built |

## Connector modules

| Module | Does | Depends on |
|---|---|---|
| `auth` | Sign-in with any OAuth 2.0 provider (authorization code + PKCE, loopback redirect), token refresh | Standard OAuth 2.0; nothing server-specific |
| `store` | Keeps sign-in records encrypted per user | The operating system (DPAPI on Windows, keyring elsewhere) |
| `gitops` | Workspaces, versions, save points, sending, pull requests | Standard git over HTTPS (dulwich), except two Gitea-specific parts below |
| `server` | Exposes the tools to Claude (MCP over stdio): `sign_in_*`, `whoami`, `sign_out`, `workspace_*`, `version_*`, `specialist_settings`, `dependency_check`, `dependency_audit`; `diag_*` only with diagnostics. Turns every stop into a plain message for the user and a report for IT | MCP |
| `support` | The stop: the user's message, IT's report, the e-mail link | — |
| `settings` | The specialist's settings: languages, the organization's context and skills, where code may be written | — |
| `deps` | `dependency_check`: which package version may be used; `dependency_audit`: every package a workspace pins | PyPI, npm and OSV public APIs; the source repositories' web addresses |
| `guard` | The file guard: the PreToolUse hook, and the rules `version_save` enforces | — |
| `hook` | Measurement hook (diagnostics only): logs each tool call and denies two guard-test markers | — |
| `probe` | Diagnostic measurements (`diag_environment`, `diag_reach`) | — |

## Facts the design relies on

- **The workspace is named by its path.** Under the current MCP protocol (`2026-07-28`) the client does not share
  its folders with the connector (roots are deprecated), so the connector cannot discover the folder selected in
  Cowork. It keeps workspaces in its own folder and returns their path; in a local Cowork session on Windows,
  Claude's file tools and the connector see the same path.
- **Per-user data lives in `%LOCALAPPDATA%\eunomai-business`**, not in `CLAUDE_PLUGIN_DATA`, which points inside
  each task's folder and does not outlive the task. Claude Desktop installed as a Windows package (MSIX) redirects
  that folder for the processes it starts unless it already exists ([where](data-on-computers.md)).
- **Where the session runs.** Since 2026-10-06, new Cowork tasks on Pro and Max plans run on Anthropic's servers;
  on Team and Enterprise an owner decides it ("Run Cowork in the cloud": on by default on Team, off on Enterprise).
  Anthropic states that local connectors work through the open desktop app
  ([Anthropic](https://support.claude.com/en/articles/15520349)), but whether this connector and the shared
  workspace folder work when the sandbox is in the cloud is not yet validated (check H16 in
  [validation](validation/hypotheses.md)). Until it is, organizations keep Cowork tasks on users' computers.

## What is tied to a git hosting

| Part | Today | Generic? |
|---|---|---|
| Clone, send, branches, save points | Standard git over HTTPS | Yes |
| Git sign-in | OAuth 2.0 public client with PKCE; user endpoint and login field configurable | Yes in principle; tested only with Gitea |
| Sending the token | HTTP basic auth (login + OAuth token) | Works with Gitea; to be checked per hosting |
| Pull request, its merged state, and branch link | Gitea API (`/api/v1/repos/.../pulls`, the 250 most recently updated) and Gitea web paths | **No**: Gitea only; without it, an accepted version is recognized only by its history (not after a squash merge) |
| Check that the token only goes to the git host | Compares the repository's origin (scheme, host, port) with the `userinfo_url` origin | Works when both share an origin (Gitea); GitHub uses a separate API host |

**Planned:** a hosting adapter per server type (Gitea first, then GitHub and GitHub Enterprise), chosen in the
organization's configuration. Only the hosting-specific rows above move into it.

## Hooks

Hooks run on the user's computer, not in Cowork's sandbox: through Git Bash if installed, PowerShell otherwise.

**Built: file guard** (`eunomai-business-guard`, in every build). A PreToolUse hook on the file tools (`Write`,
`Edit`, `MultiEdit`, `NotebookEdit`) and the shell (`Bash`, `mcp__workspace__bash`) that denies, with a reason
Claude can act on:

| Kind | Files | Where | Why |
|---|---|---|---|
| Executables | `.bat`, `.cmd`, `.ps1`, `.vbs`, `.lnk`, `.exe`, `.jar`, `.chm`, `.msi` and other files Windows runs, installs or follows on a double click | Everywhere Claude writes | The files are on the user's computer: a double click would run what the sandbox wrote |
| Project context | `AGENTS.md`, `CLAUDE.md` | In workspaces | IT keeps them; the specialist reads the project's context from the server ([decision 8](decisions.md#8--the-projects-context-belongs-to-it)) |
| Configuration | `.claude/`, `.mcp.json`, `.git/`, and continuous integration (`.gitea/`, `.github/`, `.forgejo/`, `.gitlab-ci.yml`...) | In workspaces | They configure Claude, the repository, or what runs on IT's servers |

A path is a workspace's when one of its folders has a registered workspace's name. Names Windows treats as the
same file count as protected too: trailing dots and spaces, alternate streams (`run.bat::x`), 8.3 short names.
The guard is set to `onFailure: "block"`: a guard that cannot run stops the write instead of letting it through.

`version_save` enforces the same rules on the host, where the sandbox cannot reach: every path must be valid on
Windows and stay inside the workspace; context and configuration files go back to how the last save point has them
(matched regardless of case, never through a link); adding or changing an executable stops the save (removing one
is allowed); and the tree actually committed is checked again, so a file written in the meantime undoes the save
point. A prototype page is saved only with a Content-Security-Policy that loads nothing from other sites. The hook
keeps dangerous files off the computer; the save keeps them out of the repository.

**Built: measurement hooks** (diagnostics only): they log each tool call and deny two guard-test markers (H9).

**Planned:** default rules for common sensitive files (`.env`, keys, certificates, credential files), and
organization rules added in the build configuration; organizations extend the defaults and cannot remove the fixed
rules above.

**Limits:**

- A hook sees a shell command as text: a plain write to a protected name is caught, a command built to hide it
  is not. The save repeats the check for the repository; nothing repeats it for the disk.
- Script sources that Windows opens with an interpreter (`.js` through Windows Script Host, `.py` through the
  Python launcher) cannot be refused without refusing every web application. Disabling Windows Script Host on
  business users' computers is an operating-system control for IT ([barriers](barriers.md#what-eunomai-business-does-not-protect)).
- The guard reduces mistakes and casual exposure; the real boundary for secrets is not putting them where Claude
  works.

## Plugin per project

eunomai-business holds what is valid for everyone; a project brings its own capabilities (tools over its data,
procedures that use them, hooks for its own folders) as a **project plugin** that depends on eunomai-business, and
its context in `AGENTS.md` ([decision 10](decisions.md#10--a-base-that-holds-for-everyone-projects-bring-their-own-capabilities)).
A project plugin's hook cannot undo eunomai-business's deny; its own hooks act only on its project's workspaces and
its tools carry their own limits. Like every hook, its rules prevent mistakes; the permission is the git server's (see
[project-practices.md](project-practices.md#who-can-read-and-change-what)). How it relies on eunomai-business in
Cowork is H10 ([research](../research/project-plugin/README.md)).
