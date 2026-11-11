---
type: reference
title: Data on computers and servers
description: "What eunomai-business stores on users' computers and on servers, what is sensitive, and how to uninstall leaving nothing behind."
tags: [data, security, sign-in]
audience: [it, security, data-protection]
related: [barriers.md, configuration.md]
---

# Data on computers and servers

Everything eunomai-business creates, where it lives, whether it is sensitive, and what is left after
uninstalling. Paths are for Windows; *measured* means observed on a real computer on the date given.

**`<data>`** below is the connector's folder, `%LOCALAPPDATA%\<plugin_name>` (`eunomai-business` by default). Claude Desktop installed as a
Windows package (MSIX, as from the Microsoft Store) redirects *new* folders under `AppData\Local` to
`%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local\<plugin_name>` (measured 2026-10-24,
`Claude_pzs8sxrjxfjjc`); if the folder already exists in the real location, for example from an earlier run
outside Claude Desktop, it is used there, new files inside it included (measured 2026-10-26; Windows
[redirects new files and folders](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes#appdata-operations-on-windows-10-version-1903-and-later), and allows changing existing ones).
Look in both. Folders outside
`AppData`, such as the workspaces, are not redirected.

## On the user's computer

| What | Where | Content | Sensitive | Left after uninstalling the plugin |
|---|---|---|---|---|
| The plugin | Managed by Claude Desktop (measured 2026-10-24: `%LOCALAPPDATA%\Claude-Data\claude_<id>\rpm\...\plugin_<id>`) | The zip's files: skills, connector source, the file guard hook, and measurement hooks when diagnostics are on | No | No: Claude Desktop removes the folder, also while the connector runs, since the connector's environment lives in `<data>` (measured 2026-11-11). Before that it stayed while the connector ran |
| Sign-in records | `<data>\signin-<hash>.dpapi`, one per provider (measured; the hash comes from the provider name and client ID) | Access token, refresh token, expiry times. Encrypted with DPAPI for that Windows user | **Yes** | **Yes**: delete them (below) |
| Workspace registry | `<data>\workspaces.json` | Each workspace's folder, repository address and main branch, so the connector protects them | No | **Yes** |
| Project requests | `<data>\project-requests\<request>.json` | A request for a new project: the suggested name, what it is for, who will use it, how it is done today, the first version, open questions, the message for IT and its dates; once its project is cloned, `done` with the workspace and repository, or `withdrawn` when the person no longer wants it. Kept, not deleted | Low: what the person told the assistant about their work | **Yes** |
| Operation locks | `<data>\locks\` | Empty files that exist only while an operation runs | No | Normally empty |
| Hook log (only with `diagnostics: true`) | `<data>\hooks.log`, and `hooks.log.1` after rotation (measured) | One JSON line per tool call: time, event, tool name, the names (not values) of its input fields, whether a guard-test marker matched, launch and run times, computer name, OS, shell, working folder, plugin folder, session ID. No file contents, no tokens | Low: paths include the Windows user name | **Yes**; rotated at 1 MB, so at most about 2 MB (a short session wrote 41 KB) |
| Workspaces | `workspaces_root`, default `%USERPROFILE%\eunomai-business-workspaces\<name>` (measured) | Clones of the repositories: the user's work, versions not yet sent included | **As sensitive as the repositories** | **Yes, on purpose**: it is the user's work |
| Backups before an update | Inside each workspace's `.git`, as `refs/eunomai/backup/<time>/<branch>` | Where each branch was before `workspace_update` moved it | As the workspace | With the workspace |
| uv | `%USERPROFILE%\.local\bin\uv.exe`, `uvx.exe`, `uvw.exe`; `%LOCALAPPDATA%\uv\uv-receipt.json`; user `PATH` entry (measured) | The uv program, installed per user | No | Yes; it is a separate program |
| The connector's environment | `<data>\environments\<hash>`, one for each connector folder and set of locked packages, and `<hash>.used` beside it (measured 2026-11-11). `connector/start.py` sets it; never inside the plugin's folder, which Windows would then not let go while the connector runs | The locked packages, installed from uv's cache: about 60 MB | No | **Yes**: removed with `<data>` (step 5). While the plugin is installed, one nobody started for a week is removed once nothing runs from it |
| uv cache | `%LOCALAPPDATA%\uv\cache`; with Claude Desktop installed as a Windows package, the uv the app starts writes to `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local\uv\cache` instead (measured 2026-11-11: 54 MB, several copies of the connector) | Built connector versions and their dependencies (`mcp`, `httpx`, `dulwich`, ...) | No | Yes; the first is shared with any other use of uv, the second holds what the app's processes downloaded |
| Python | `%APPDATA%\uv\python` (measured 2026-11-11, not redirected) | The connector starts with `--managed-python`, so uv always uses a Python it downloaded itself, whatever the computer has | No | Yes; shared with any other use of uv's Python |
| A preview (only with `app_preview`) | `%TEMP%\eunomai-preview-<random>`: `app`, a copy of the saved version; `environment`, its packages; `home`, `temp`, and `preview.log` | The application's files, its example data and its output, for as long as it runs | **As sensitive as the repository**, and whatever the application writes | No: it stays while the preview runs, even with Claude Desktop closed, and goes when it stops, at the latest after 60 minutes. If its watcher is killed, the next preview removes it. What the application wrote elsewhere stays: it runs as the person |
| A workspace's kept preview data (only with `app_preview`) | `%TEMP%\eunomai-preview-keep-<hash>`: `data`, what the application writes where the declaration says `{data}`; `environment`, its installed packages | What the person entered in the application, and its packages | **As sensitive as what they entered** | No: removed on stop, at the time limit and by the sweep after two hours unused; kept across new versions |
| The tests' last output (only with `app_tests`) | `<data>\tests\<hash>.log`, one a workspace, replaced by its next run | Everything the tests printed, up to 5 MB: names, values, whatever they show; for a run of some test files, which ones first | As sensitive as the repository | No: kept for IT, until the next run |
| An audit a preview keeps (only with `app_preview`) | `<data>\audits\<hash>.json` | The last `allowed` answer of the dependency audit for a workspace's preview, and a fingerprint of what it read | No | Used for an hour, replaced by the next |
| A preview's state | `<data>\previews\<hash>.json`, with `.alive`, `.stop`, `.ended` and `.kept` beside it | Its workspace, saved version, a fingerprint of the declaration, folder, port, end time, process groups where there are any, and its watcher's number, program and start time, so any task's connector can find it and stop it; `.ended` holds why it ended by itself | No | Empty when no preview runs, but for an `.ended` nobody has read, removed after two hours |
| Browser sessions | The default browser | Sign-in cookies of Entra ID and the git server | Yes, as any sign-in | Until signing out in the browser |

The connector writes nothing to the registry or outside the user's profile, and nothing needs administrator rights.
A preview's code runs with the person's rights, so it could
([what it does not stop](barriers.md#the-preview-on-the-persons-computer)).

## Reports for IT

When the connector stops, the report the user can send to IT contains the workspace's folder and repository,
the version, its last save point and the main branch, the files involved, the error text for unexpected errors,
the connector version and build, the computer's OS and the time. It never contains
tokens. It travels only if the user sends the e-mail. A request for a new project travels the same way: the
person sends it, or copies its text; the connector sends nothing.

## Calls to public services

`dependency_check` and `dependency_audit` ask PyPI, npm and OSV (`api.osv.dev`) about packages, and open the
web address of each package's source repository to check it exists. They send package names and versions only;
nothing about the user or the project.

A preview's installation asks `files.pythonhosted.org` for the project's packages, through uv, and for a Python, if the
computer lacks it, `releases.astral.sh` or `github.com` ([addresses](configuration.md#installing-uv-in-an-organization)). What the
application itself calls is the application's business: it runs with the person's network.

## On servers

| What | Where | Lasts | How to end it |
|---|---|---|---|
| The git sign-in grant | Git server, user settings (Gitea: *Settings → Applications → Authorized OAuth2 applications*) | Until revoked | Revoke it there |
| Git refresh token | Git server | Until revoked or expired (server policy) | Revoke the grant |
| Entra ID sign-in and refresh token | Entra ID; sign-ins appear in the sign-in logs | Microsoft's default policy for refresh tokens (90 days of inactivity for this kind of client, per Microsoft's documentation) | *Revoke sessions* on the user in Entra (all apps), or wait |
| Versions, save points, pull requests | Git server | As any git history | As any git history |

## Uninstalling

To leave nothing behind, in this order:

1. **Check the workspaces.** For each one, ask Claude for `workspace_status`; anything not sent is lost when the
   folder is deleted.
2. **Sign out:** ask Claude for `sign_out` for each provider. This deletes the local tokens only.
3. **Revoke on the servers** (the table above) if the tokens must stop working now and not at expiry.
4. **Uninstall the plugin** in Claude Desktop.
5. **Delete** the connector's folder, `<data>` above: `%LOCALAPPDATA%\<plugin_name>` and, with Claude Desktop
   installed as a Windows package, `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local\<plugin_name>`.
   Check both.
6. **Clean uv's cache** of the connector: `uv cache clean eunomai-business`, and, with Claude Desktop installed as a
   Windows package, delete `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local\uv\cache`: that command does not
   reach it, and only the app's processes use it. If uv is used for nothing else, remove uv itself, and its Python,
   following uv's uninstall guide.
7. **Delete the workspaces** folder if the work is no longer needed.

If step 2 is skipped, step 5 still removes the tokens from the computer.
