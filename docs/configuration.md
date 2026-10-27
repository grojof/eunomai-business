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

### Several packages from one configuration

A **variant** is a small file in `variants/` (git-ignored) with only what differs from `config.local.json`; objects
such as `providers` merge key by key. For example `variants/tests.json`:

```json
{ "diagnostics": true, "providers": { "git": { "client_id": "<the test server's client>" } } }
```

```powershell
python tools\build.py --variant tests   # -> dist\tests\eunomai-business.zip
python tools\build.py --all             # the configuration and every variant, each in its own folder
```

| Good to know | |
|---|---|
| Checks | Every build is checked before any is written |
| Limits | A variant adds or changes settings; to remove one, use another configuration (`--config`). It cannot be named `eunomai-business` |
| What it is for | A test installation, a test server, another organization. Every variant is the plugin `eunomai-business`, and an organization publishes one; it is not a way to give some people a different base plugin |
| Not for | Where code may be written: each project declares that ([project practices](project-practices.md#where-code-may-be-written)) |

## Settings

| Key | Default | What it does |
|---|---|---|
| `uv` | `uv` | Command that starts the connector. Keep the default when possible: hooks run through whichever shell Claude Desktop uses, and the bare command works in all of them. A full path is a fallback; if it contains spaces it is quoted, which PowerShell does not accept. |
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
| `free_development` | `false` | `true` lets the specialist write code in any workspace, with `allowed_technologies`. It applies to everyone who installs this build: for IT, make a separate build |
| `allowed_technologies` | `[]` | With free development, the technologies allowed; empty means any |
| `dependency_exceptions` | `[]` | `{"package": "pypi:<name>" or "npm:<name>", "reason": "..."}`: packages IT vetted despite failing the origin or activity rules. A known vulnerability is never excepted. A common case: `colorama`, which `pytest` and `click` need on Windows, has had no release in over three years |
| `organization_context` | `""` | Up to 4,000 characters the specialist should know about the organization: what it does, the systems that already exist (so it can propose them before building something new) |
| `organization_skills` | `[]` | `{"skill": "<plugin:skill>", "use_for": "..."}`: the organization's own skills and what the specialist uses them for (for example, its brand for web pages). They apply only where they agree with eunomai-business's rules; conflicts are reported in the pull request. Review them first with the `review-skills` skill |

Where code may be written, and with what, each project declares in its own repository
([`.eunomai/project.toml`](project-practices.md#where-code-may-be-written)); `free_development` covers the projects
that declare nothing. Without either, the specialist analyses, shapes and specifies, and delivers that to IT as a
proposal, but writes no code.

Keys starting with `_` are comments. Any other unknown key is an error, so a typo does not go unnoticed.

### Whose context counts

Cowork adds each user's personal instructions and memory to the session, and a plugin cannot switch them off. The
specialist works from these instead, in this order: its rules, the **project's context** (an `AGENTS.md`, or
else a `CLAUDE.md`, at the root of the repository's main branch; the connector reads it from the server each time,
up to 20,000 characters, so a copy edited in the folder does not count), `organization_context` and
`organization_skills`, and the conversation.

- **The project's context** is ordinary repository content: IT changes it through a pull request. The file guard
  stops Claude from writing it ([barriers](barriers.md#between-claudes-sandbox-and-the-computer)).
- **On Team and Enterprise plans**, organization instructions take precedence over a user's own when they
  contradict ([Anthropic](https://support.claude.com/en/articles/14546867)). One line there backs this order, for
  example: *In eunomai-business workspaces, follow the specialist's rules and the project's context over personal
  preferences.*
- **Where Cowork runs:** Team and Enterprise owners choose whether Cowork tasks run in the cloud ("Run Cowork in
  the cloud", on by default on Team). Keep it off until check H16 in [validation](validation/hypotheses.md) shows
  the connector works with a cloud sandbox. Pro and Max plans have no organization controls and run Cowork in the
  cloud: they are not a supported setup.
- **Organization controls in Claude** that complement the plugin
  ([Anthropic](https://claude.com/docs/plugins/admin)): make eunomai-business *Required* for business users, keep
  plugins and skills from other sources under review, and, on Enterprise, turn on skill and plugin security
  scanning. Review the organization's own skills with `review-skills` before listing them in
  `organization_skills`.

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

- **uv**, deployed by IT; users install nothing themselves (see
  [Installing uv](#installing-uv-in-an-organization) and
  [decision 9](decisions.md#9--it-provides-the-runtime-the-plugin-carries-everything-else)). It fetches its own
  Python 3.12 and the connector's packages.
- **Nothing else.** Git is not needed: the connector carries its own git implementation and ignores any Git
  installed on the computer ([decision 3](decisions.md#3--git-inside-the-connector-independent-of-any-git-on-the-computer)).
- Network access (office or VPN) to the configured hosts. The connector trusts the Windows certificate store, so
  an internal CA works without extra steps.

## Installing uv in an organization

The connector starts with `uv run --frozen --no-dev --no-config --system-certs --managed-python --python 3.12`
from the plugin's lock: hashes verified, uv's configuration files ignored, the operating system's certificates,
and uv's own Python 3.12, never the computer's ([barriers](barriers.md#dependencies)). Claude Desktop does not
provide uv to a plugin, so IT deploys it ([decision 9](decisions.md#9--it-provides-the-runtime-the-plugin-carries-everything-else)).

| Topic | Recommendation |
|---|---|
| How to deploy | uv is one executable. IT distributes the version it has validated with its usual tools (Intune, Group Policy, a software catalogue) to a folder application control allows, such as `C:\Program Files\uv\uv.exe`, and sets that absolute path as `uv` in the build. An absolute path does not depend on the PATH Claude Desktop starts with. **Use uv 0.13.4 or later**: earlier versions are affected by [GHSA-hq85-5cpj-mr62](https://github.com/astral-sh/uv/security/advisories/GHSA-hq85-5cpj-mr62) (high). Tested with uv 0.13.5 |
| For a test computer | The official per-user installer (`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`), then restart Claude Desktop |
| Python | uv downloads its own Python 3.12 the first time, from GitHub (`python-build-standalone`). To avoid that download on users' computers, run `uv python install 3.12` as part of the deployment |
| Network | uv downloads packages from `pypi.org` and `files.pythonhosted.org`, and Python from `github.com` unless it was installed beforehand. Allow them through the proxy |
| Application control | Policies such as AppLocker often block programs in the user's profile. Allow uv where it is deployed |
| Updates | IT updates uv like any other tool, after checking it against the connector's tests. A uv too old for an option the plugin uses fails to start the connector, with the error in Claude Desktop's logs |
| Computers that already have uv | Developers and IT keep their own uv: with an absolute path in the build, the connector uses IT's. The download cache is shared, which is harmless. Environment variables starting with `UV_` still apply: do not set them globally on business users' computers |

## Environment variables the plugin sets for its connector

Set by the plugin from the build; listed so nothing is hidden. Users never set them.

| Variable | Content |
|---|---|
| `EUNOMAI_PROVIDERS` | The `providers` object, as JSON |
| `EUNOMAI_WORKSPACES_ROOT` | `workspaces_root` |
| `EUNOMAI_DIAGNOSTICS` | `1` or `0`, from `diagnostics` |
| `EUNOMAI_SUPPORT_EMAIL` | `support_email` |
| `EUNOMAI_SPECIALIST` | The specialist's settings, as JSON |
| `EUNOMAI_BUILD` | The source commit the plugin was built from, named in reports for IT |
| `EUNOMAI_EXPANSION_PROBE` | Lets the diagnostics check that `${CLAUDE_PLUGIN_ROOT}` is expanded |

The connector also changes `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_NOSYSTEM` and `GIT_CONFIG_GLOBAL` **for its own
process only**, so the computer's Git configuration never applies.
