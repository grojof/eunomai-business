---
type: reference
title: Configuration
description: "Every setting IT sets when building the plugin, how to register the sign-in clients, and what users need on their computer."
tags: [configuration, sign-in, it]
audience: [it]
related: [barriers.md, data-on-computers.md]
---

# Configuration

Everything that varies between organizations is set **once, by IT, when building the plugin**. Users install the
plugin and sign in; they configure nothing. Why: [decision 4](decisions.md#4--configuration-at-build-time-by-it).

## How it works

1. Copy `config.example.json` to `config.local.json` and fill it in. Git ignores `config.local.json`.
2. Run `python tools/build.py` (Python 3.10 or later, standard library only). It checks the configuration,
   reports every problem at once, and writes `dist/eunomai-business.zip` with your values built in.
3. Publish the zip to your Claude organization (Team or Enterprise, by an Owner), or install it on one computer
   for testing: *Customize → Plugins → Upload plugin*.

Nothing in the file is a secret: every sign-in client is public (no client secret, no certificate). It does
contain internal host names, so keep the built zip inside the organization.

## Settings

| Key | Default | What it does |
|---|---|---|
| `uvx` | `uvx` | Command that starts the connector. Keep the default when possible: hooks run through whichever shell Claude Desktop uses, and the bare command works in all of them. A full path to `uvx.exe` is a fallback; if it contains spaces it is quoted, which PowerShell does not accept. |
| `connector_source` | `bundled` | `bundled`: the connector ships inside the zip. `path`: it runs from `connector_path` (development only). Any other value is an error. |
| `connector_path` | — | Folder of the connector source; required when `connector_source` is `path`. |
| `workspaces_root` | `~/eunomai-business-workspaces` | Where each user's workspaces (local clones) go. `~` is the user's profile; `%VAR%` is expanded. Must be absolute after expansion. |
| `support_email` | — | The address users send to when the connector stops and needs IT. Optional; without it users get the report but no e-mail link. |
| `diagnostics` | `false` | `true` adds the diagnostic tools (`diag_*`), the validation skills and a hook log. For validating an installation; keep `false` for users. |
| `providers` | — | Sign-in providers, by name. Must include `git`. See below. |

### The specialist

| Key | Default | What it does |
|---|---|---|
| `docs_language` | `en` | Language of documentation, specifications and pull request summaries (`es`, `en`, ...) |
| `code_language` | the documentation's | Language of identifiers and comments. Technical terms stay in English |
| `free_development` | `false` | `true` lets the specialist write code in any workspace, with `allowed_technologies`. For IT profiles, not for business users |
| `allowed_technologies` | `[]` | With free development, the technologies allowed; empty means any |
| `projects` | `{}` | Repository address → `{"technologies": [...]}`: the projects where code may be written, and with what |
| `dependency_exceptions` | `[]` | `{"package": "pypi:<name>" or "npm:<name>", "reason": "..."}`: packages IT vetted despite failing the origin or activity rules. A known vulnerability is never excepted |

Without a project entry or free development, the specialist analyses, shapes and specifies, and delivers that to
IT as a proposal, but writes no code.

Keys starting with `_` are comments. Any other unknown key is an error, so a typo does not go unnoticed.

**`workspaces_root`:** avoid folders synced by OneDrive (a synced `.git` folder breaks) and anything under
`AppData` (Claude Desktop may redirect it). The folder holds the users' work; see
[data-on-computers.md](data-on-computers.md).

## Sign-in providers

Each entry under `providers` is one OAuth 2.0 authorization-code client with PKCE.

| Field | Required | Meaning |
|---|---|---|
| `authorize_url` | yes | Authorization endpoint. `https` |
| `token_url` | yes | Token endpoint. `https` |
| `client_id` | yes | Public client ID |
| `scopes` | no | Space-separated scopes; empty sends none |
| `redirect_uri` | yes | `http://127.0.0.1:<port>/...` or `http://localhost:<port>/...`. The connector listens on that port during sign-in. One port per provider |
| `userinfo_url` | yes | Endpoint that returns the signed-in user (also used to check the token works). `https` |
| `login_field` | no (`login`) | Field of the `userinfo_url` answer shown as the user's login |

Plain `http` is accepted only for `127.0.0.1` and `localhost` (tests): tokens never travel in clear text.

Provider names with a meaning:

| Name | Used by | Needed |
|---|---|---|
| `git` | Workspaces, versions, save points, pull requests. Its host is the only one the git token is sent to | Yes |
| `directory` | The organization's directory (Entra ID). Today only the validation skill uses it | No |

## Registering the clients

### Entra ID (`directory`)

*Entra admin center → App registrations → New registration*

| Setting | Value |
|---|---|
| Supported account types | This organization only |
| Platform | Mobile and desktop applications |
| Redirect URI | `http://localhost` (Entra accepts any port on `localhost`) |
| API permissions | Microsoft Graph, delegated: `openid`, `profile`, `offline_access`, `User.Read`; then *Grant admin consent* |
| Secrets and certificates | None |

Optional: *Enterprise applications → the app → Properties → Assignment required = Yes*, and assign a group, to
limit who can sign in.

`authorize_url` and `token_url` are
`https://login.microsoftonline.com/<tenant id>/oauth2/v2.0/authorize` and `.../token`.

### Gitea (`git`)

*Site Administration → Integrations → Applications*, so the application belongs to the instance, not to a
person. Create one named `eunomai-business`; do not reuse the applications Gitea ships with (such as
`git-credential-oauth`): users would authorize another tool's name, and Gitea's own configuration controls them.

| Setting | Value |
|---|---|
| Redirect URI | Exactly the `redirect_uri` of the `git` provider, for example `http://127.0.0.1:53682/callback` |
| Confidential client | **Unchecked** |

`authorize_url`, `token_url` and `userinfo_url` are `https://<gitea>/login/oauth/authorize`,
`.../login/oauth/access_token` and `https://<gitea>/api/v1/user`. Leave `scopes` empty.

The git sign-in belongs to whoever is signed in to the git server in the browser. With single sign-on that is
the user's own account; on a shared or test browser, check who is signed in first.

### Other git hosting

Only **Gitea** is tested. Plain git operations (clone, send) use standard HTTPS and are not tied to Gitea;
sign-in details and the pull-request call are. GitHub, GitHub Enterprise and GitLab are **not supported yet**.
See [architecture.md](architecture.md#what-is-tied-to-a-git-hosting).

## What users need on their computer

- **uv**, installed per user without administrator rights:
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, then quit Claude Desktop
  completely and open it again. uv fetches a Python itself if none is installed.
- **Nothing else.** Git is not needed: the connector carries its own git implementation and ignores any Git
  installed on the computer ([decision 3](decisions.md#3--git-inside-the-connector-independent-of-any-git-on-the-computer)).
- Network access (office or VPN) to the configured hosts. The connector trusts the Windows certificate store, so
  an internal CA works without extra steps.

## Environment variables the plugin sets for its connector

Set by the plugin from the build; listed so nothing is hidden. Users never set them.

| Variable | Content |
|---|---|
| `EUNOMAI_PROVIDERS` | The `providers` object, as JSON |
| `EUNOMAI_WORKSPACES_ROOT` | `workspaces_root` |
| `EUNOMAI_DIAGNOSTICS` | `1` or `0`, from `diagnostics` |
| `EUNOMAI_SUPPORT_EMAIL` | `support_email` |
| `EUNOMAI_SPECIALIST` | The specialist's settings, as JSON |
| `EUNOMAI_EXPANSION_PROBE` | Lets the diagnostics check that `${CLAUDE_PLUGIN_ROOT}` is expanded |

The connector also changes `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_NOSYSTEM` and `GIT_CONFIG_GLOBAL` **for its own
process only**, so the computer's Git configuration never applies.
