---
type: how-to
title: Run the validation
description: "Step by step: install, build with diagnostics, and check an installation of eunomai-business in Claude Cowork against the validation checks."
tags: [validation, configuration]
audience: [it, developers]
related: [hypotheses.md, ../configuration.md]
---

# Run the validation

How to check an installation against the hypotheses in [hypotheses.md](hypotheses.md), on a Windows computer
with Claude Desktop. It uses a build with diagnostics on. **Sending versions and opening pull requests write
to the git server**: use a test repository.

## 1 · Install uv for the current user (H7)

PowerShell, **without** "Run as administrator":

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv --version
```

It installs into `%USERPROFILE%\.local\bin` and adds it to the user `PATH`. **Quit Claude Desktop completely**
(also from the tray icon) and open it again, so it starts with the new `PATH`.

## 2 · Register the sign-in clients

Both providers of the example configuration: Entra ID (`directory`) and Gitea (`git`). Steps in
[configuration.md](../configuration.md#registering-the-clients).

## 3 · Prepare a test repository

On the git server, as its administrator:

1. Create the repository **initialized** (with a README), so it has a `main` branch.
2. Make a couple of changes on `main` from the web, to simulate a repository in use.
3. Give the test user **write** access.
4. Protect `main`: no direct pushes; 0 required approvals, so the test user can merge their own pull request.

## 4 · Build with diagnostics

```powershell
cd <your clone>\eunomai-business
copy config.example.json config.local.json   # first time; then fill in hosts and client IDs
# in config.local.json set "diagnostics": true
python tools\build.py                        # -> dist\eunomai-business.zip (diagnostics on)
```

## 5 · Install it in Claude Desktop

1. Remove any earlier version of the plugin.
2. *Customize → Plugins → Upload plugin* → `dist\eunomai-business.zip`.
3. For steps 6 to 8, make sure Cowork tasks run **on this computer**, not in the cloud (step 9 tries the cloud).

## 6 · Validate the setup (H1–H4, H6, H9)

New Cowork task:

> Validate the eunomai-business setup. URLs: `https://<git-server>/api/healthz` and `https://<another internal host>/`.

Complete each sign-in in the browser. Claude ends with a table per hypothesis.

## 7 · Validate workspaces and versions (H8)

New Cowork task:

> Validate eunomai git with `https://<git-server>/<owner>/<repo>`.

Claude clones it into the workspaces folder (default `%USERPROFILE%\eunomai-business-workspaces\<repo>`) and asks
you to open a **new task with that folder selected**. There write *"continue the git validation"*: Claude
creates a version, edits files with its own tools, and the connector saves, sends and proposes them. Open the
pull request, check the files, the accents and the author, and merge it.

## 8 · Robustness (H5)

- New task: *"Call whoami for each provider."* → same login, no browser.
- Quit Desktop, open it, new task, same request.
- After the token expires (about an hour): same request → `refreshed: true`.

## 9 · The business-user test and the newer checks (H11–H17)

1. **Build without diagnostics**, with `organization_context` set, and put an `AGENTS.md` on `main` of a test
   repository (H15).
2. **As a business user**, in a new task, ask for something vague (for example *"I need something to track the
   team's holidays"*) and follow the specialist to the pull request. Note: the questions, the prototype (it opens
   in the browser and responds to clicks), the specification, the tests, the pull request summary and the
   connector's checks at its end (H11–H14), and whether it used the project's context rather than anything
   personal (H15).
3. **The guard** (H17): ask Claude to write a `start.bat`, to edit `AGENTS.md`, and to do both through the shell;
   each is denied with a reason. Repeat on a computer without Git.
4. **The cloud** (H16): with "Run Cowork in the cloud" on, repeat steps 6 and 7.

## 10 · Write down the results

Update the **Status** column of [hypotheses.md](hypotheses.md) with what was observed, the plugin and Desktop
versions and the date.

## If something fails

| Symptom | Likely cause | What to do |
|---|---|---|
| The `eunomai-business` tools do not exist in the task | The connector did not start | Desktop logs in `%LOCALAPPDATA%\Claude\Logs` (search `eunomai-business`); note the error as a result |
| Log says `uv` not found | Desktop started before `uv` was installed, or does not read the user `PATH` | Quit and reopen Desktop; if it persists, set `uv` to the full path of `uv.exe` in `config.local.json`, rebuild, upload again |
| `diag_reach` fails only with `bundled_store` | Expected with an internal CA | Pass: the OS store is what counts |
| Sign-in never leaves `waiting` | The browser did not open, or the redirect URI differs | Open the `url` the tool returned by hand; check the redirect URI registered on the server |
| `AADSTS50011` | Redirect URI not registered in Entra | Add `http://localhost` under *Mobile and desktop applications* |
| `AADSTS65001` | Admin consent missing | *API permissions → Grant admin consent* |
| `version_create` refuses: "no main branch yet" | The repository is empty | Initialize it (step 3) |
| `unexpected entry in .git/config` | Something wrote a setting the connector does not accept | Expected barrier; remove the entry or clone again |
