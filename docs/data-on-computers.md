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

## On the user's computer

| What | Where | Content | Sensitive | Left after uninstalling the plugin |
|---|---|---|---|---|
| The plugin | Managed by Claude Desktop (measured 2026-10-24: `%LOCALAPPDATA%\Claude-Data\claude_<id>\rpm\...\plugin_<id>`) | The zip's files: skills, hooks, connector source | No | Claude Desktop's business; not yet measured |
| Sign-in records | `%LOCALAPPDATA%\eunomai-business\signin-<hash>.dpapi`, one per provider (measured; the hash comes from the provider name and client ID) | Access token, refresh token, expiry times. Encrypted with DPAPI for that Windows user | **Yes** | **Yes**: delete them (below) |
| Workspace registry | `%LOCALAPPDATA%\eunomai-business\workspaces.json` | Each workspace's folder and its main branch, so the connector protects it | No | **Yes** |
| Hook log (only with `diagnostics: true`) | `%LOCALAPPDATA%\eunomai-business\hooks.log`, and `hooks.log.1` after rotation (measured) | One JSON line per tool call: time, event, tool name, computer name, OS, shell, working folder, plugin folder, session ID. No file contents, no tokens | Low: paths include the Windows user name | **Yes**; rotated at 1 MB, so at most about 2 MB (a short session wrote 41 KB) |
| Workspaces | `workspaces_root`, default `%USERPROFILE%\eunomai-business-workspaces\<name>` (measured) | Clones of the repositories: the user's work, versions not yet sent included | **As sensitive as the repositories** | **Yes, on purpose**: it is the user's work |
| uv | `%USERPROFILE%\.local\bin\uv.exe`, `uvx.exe`, `uvw.exe`; `%LOCALAPPDATA%\uv\uv-receipt.json`; user `PATH` entry (measured) | The uv program, installed per user | No | Yes; it is a separate program |
| uv cache | `%LOCALAPPDATA%\uv\cache` (measured) | Built connector versions and their dependencies (`mcp`, `httpx`, `dulwich`, ...) | No | Yes; shared with any other use of uv |
| Python, if the computer has none | `%APPDATA%\uv\python` (uv's documented default; not measured, the test computer had Python) | A Python runtime downloaded by uv | No | Yes |
| Browser sessions | The default browser | Sign-in cookies of Entra ID and the git server | Yes, as any sign-in | Until signing out in the browser |

Nothing is written to the registry or outside the user's profile, and nothing needs administrator rights.

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
5. **Delete** `%LOCALAPPDATA%\eunomai-business`. Some Claude Desktop versions redirect it to
   `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local\eunomai-business`; check there too.
6. **Clean uv's cache** of the connector: `uv cache clean eunomai-business`. If uv is used for nothing else,
   remove uv itself following uv's uninstall guide.
7. **Delete the workspaces** folder if the work is no longer needed.

If step 2 is skipped, step 5 still removes the tokens from the computer.
