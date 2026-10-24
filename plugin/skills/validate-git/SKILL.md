---
name: validate-git
description: Validate eunomai-business workspaces end to end (H8) - clone a repository with the local connector, then edit files in Cowork, save and send them as a version (branch) and propose it with a pull request, without Git installed. Only present in builds with diagnostics enabled. Use when the user asks to validate git, run the git test or the H8 test.
---

# Validate workspaces and versions (H8)

Reply in the language the user writes in; keep tool names, hypothesis numbers and error texts as they are.
Never print tokens. Never run `git commit`, `git push` or any command that changes the repository from a shell:
every change goes through the connector's `workspace_*` and `version_*` tools. Report error texts verbatim.

## Part A · Join the repository (any task)

1. `whoami("git")`. If not signed in: `sign_in_start("git")`, then `sign_in_status("git")` until
   it is no longer `waiting`.
2. `workspace_list`. If the repository is not there, `workspace_clone(repo_url)` (ask for the URL if the
   user did not give it). Note `path`, `branch`, `head`, `files`, `empty_repository`, `remote_branches` and `main_branch`.
   If `empty_repository` is true, stop: the repository must be initialized with a `main` branch by whoever
   manages it before versions can be created.
3. Tell the user: start a **new task** in Cowork with the folder `path` selected as the working folder, and
   write there "continue the git validation" (in their language). Stop here unless that folder is already shared
   with this task.

## Part B · Version, save, send, propose (in a task with the workspace folder selected)

4. With your own file tools, list the selected folder. Note the path **you** see for it and compare it with the
   connector's `path` from `workspace_list`.
5. `version_create(workspace, "test/<yyyymmdd-hhmm>")` with the current date and time.
6. With your own file tools (not the connector): add one line at the end of an existing file (`README.md` if
   there is one) and create `validation/hello.md` with three lines that include accented characters (for example:
   "Prueba de guardado", "Año, canción, pingüino", the date).
7. `workspace_status(workspace)`: the connector must list exactly the files you created or changed, and
   `crlf_in_changed_files` must be empty.
8. `version_save(workspace, "eunomai validation: first save point")`. Note `commit` and `files`.
9. `version_send(workspace)`. Note `web_url`.
10. `version_propose(workspace, "eunomai validation: proposal from Cowork", "<one line saying what changed>")`.
    Give the user the pull request `url` and ask them to open it, check the changes, the accents and the author,
    and merge it if they agree.
11. Read-only observation, only if you have a shell: `git -C <your path> status --short` and
    `git -C <your path> log --oneline -3`. Report the output or the error as it is.
12. `version_save(workspace, "nothing")` again: expected `saved: false` (nothing changed).

## Report

One table: step, what was observed, pass / fail. Then a verdict on each part of H8:

| # | Part | Passes when |
|---|---|---|
| H8a | Claude's edits in the selected folder are what the connector sees | step 7 lists exactly the edited files, no CRLF |
| H8b | Version and save point without Git installed, sent with the sign-in token | steps 5, 8 and 9 succeed |
| H8c | Text survives intact | accents correct and LF line endings on the server (the user confirms in step 10) |
| H8d | The sandbox and the host do not trip over each other's `.git` | step 11 output, or "no shell" |
| H8e | A user joining a repository in progress proposes changes through a pull request | step 2 clones `main` with its files; step 10 opens the pull request against `main` |

Facts only; mark anything inferred as inferred.
