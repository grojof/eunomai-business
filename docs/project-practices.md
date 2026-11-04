---
type: how-to
title: Good practices for project repositories
description: "How to set up and run a repository that business users work on: creating it from the organization's template, main branch, line endings, ignored files, permissions, content."
tags: [repositories, git]
audience: [repository-owners]
related: [barriers.md]
---

# Good practices for project repositories

eunomai-business writes no rule into a project; it only refuses to save the files listed below. These are
recommendations for whoever creates and runs a repository that business users work on. They apply to any git hosting (Gitea, GitHub, GitHub
Enterprise, GitLab).

## Creating a project from the template

Business people never create repositories ([decision 15](decisions.md#15--a-business-person-never-creates-a-repository)).
When someone wants a new application, IT receives a request by e-mail, with a subject that starts
with the plugin's name (in English, `<plugin_name>: new project request: <name>`): a suggested name, what it is for,
who will use it, what was understood and the open questions. Its fixed text is in the organization's
documentation language (`docs_language`: Spanish, Catalan or English, otherwise English); the person's words are
as they wrote them. IT decides the name, creates the repository from the organization's template,
gives the requester write access and replies with its address (`owner/name`). The person tells the assistant, which
carries on from the request.

**The template** is one repository with what every project starts from: a `main` branch with a README, the
`.gitattributes` and `.gitignore` below, the project's context and declaration, and `main` protected as below.
Its README is a skeleton the specialist fills in with the application's own map; where the template is made from
a base, the base's reference goes in a folder of its own that the project reads and never edits, so the
project's `docs/` holds only the application's pages.

**With `tools/new_project.py`**, in Gitea, IT does it in one command, always the same way:

1. Once: copy `new_project.example.json` to `new_project.local.json` (git-ignored) and fill in the server, the owner
   (the organization of the projects), the template and the file that holds the `Authorization: token …` header of
   an account that may create repositories there. Set `actions` to `false` when the server has no runner, so nothing
   waits in a queue. No secret goes in that file; the token is read from its own file and never printed.
2. For each request, save the e-mail as it arrived in a text file and run, with the name people will see:

   ```bash
   python tools/new_project.py --request request.txt --title "Asset inventory" --dry-run   # checks, changes nothing
   python tools/new_project.py --request request.txt --title "Asset inventory"
   ```

   `--name` sets the repository's name instead of the request's proposal; `--requester`, the requester's git user
   when the request names none (they were not signed in when it was prepared).
3. Send the requester the reply it prints, in the request's language.

| Step | What it does | Why |
|---|---|---|
| Read the request | Its fixed lines (proposed name, request, requester's git user), in English, Spanish or Catalan | They are the connector's own; nothing is typed again |
| Check first | The template exists and is a template; no repository has the name | A name in use stops everything before any change |
| Create | From the template, private, with its labels | Every project starts from the same files |
| Name it | One commit sets `APP_NAME` in `.env.example` and in the preview's environment | Before `main` is protected, so it needs no pull request; a template with no such line is refused, never guessed |
| Protect `main` | No direct push, one approval, up to date with `main`, blocked by a rejected review, stale approvals dismissed | What reaches `main` has been reviewed by IT |
| Give access | The requester gets write access | They work through versions and pull requests |
| Actions off | Only with `actions: false` | A server without a runner would queue every run forever |
| Check after | Reads back the protection, the access and the name | Says what to check by hand if any does not show |

Certificates are always verified; `ca_file` names an organization's own authority. If a step fails after the
repository exists, the tool says what was done and what is left, and never deletes it. Only Gitea is supported.

**In Gitea** (template repositories exist since 1.11):

| Step | Through the API (1.24) |
|---|---|
| Make the template | `PATCH /repos/{owner}/{repo}` with `"template": true` |
| Create a project from it | `POST /repos/{template_owner}/{template_repo}/generate`, with `name` and `owner` (required) and what to copy: `git_content` (the default branch's content), `protected_branch` (its protected branches), `labels`, `topics`, `avatar`, `webhooks`, `git_hooks`; also `description`, `private`, `default_branch`. It answers 201 with the repository, 409 when the name exists, 403, 404 or 422 |

```json
{"owner": "projects", "name": "alta-de-pedidos", "private": true,
 "git_content": true, "protected_branch": true, "labels": true,
 "webhooks": false, "git_hooks": false}
```

Generate with `protected_branch` so that `main`'s protection is copied, and leave out what the template should not
hand to every project: `git_hooks` copies hooks that run on the server. A `.gitea/template` file in the template
lists the files where `$REPO_NAME` and other variables are replaced; by default none are, and that file is not
copied.

**What Gitea's documentation does not say** (read 2026-11-02): the permission the caller needs, on the template or in
the owner organization (the API page lists ways to authenticate and a 403, not a permission); and whether new
repositories get any branch protection by default, organization-wide. Until a real Gitea shows both
([H24](validation/hypotheses.md)), check on each new repository that `main` is protected before anyone else gets
access.

**In GitHub**, a repository created from a template "starts with a single commit", with the template's files from
its default branch, or every branch with *Include all branches*. The page does not say whether branch protection or
other settings are copied. On GitHub Team and Enterprise, an organization's rulesets can "target all repositories in
your organization", or those matching a name or custom properties; the page does not say in so many words that a
ruleset for all repositories covers a repository created later, so check it on the first one.

## Before users join

- **Create the repository with a `main` branch** (a README is enough). eunomai-business refuses to create
  versions in an empty repository.
- **Protect `main` on the server:** no direct pushes, changes through pull requests. Decide how many approvals.
- **Delete branches after merging** (Gitea: the repository's *Delete pull request branch after merge by
  default*; GitHub: *Automatically delete head branches*), so the server does not pile up finished versions.
- **Give users write access** to the repository: they send versions and open pull requests; they cannot change
  `main` directly once it is protected.

## Line endings: `.gitattributes`

Pin line endings in the repository so every tool behaves the same, with or without Git on the computer.
A general starting point:

```gitattributes
# Text: stored and checked out with LF
* text=auto eol=lf

# Windows scripts need CRLF
*.bat  text eol=crlf
*.cmd  text eol=crlf

# Binary: never converted, never diffed as text
*.png  binary
*.jpg  binary
*.gif  binary
*.pdf  binary
*.zip  binary
*.docx binary
*.xlsx binary
*.pptx binary
```

## Files that should not be versioned: `.gitignore`

```gitignore
# Office lock files and OS clutter
~$*
Thumbs.db
desktop.ini
.DS_Store

# Secrets and local settings
.env
*.pfx
*.pem
*.key
```

## Who can read and change what

Real permissions live on the git server, not on the user's computer:

- **Reading:** git cannot hide part of a repository. Whoever can clone it has every file. If some content must
  not be readable by some users, it belongs in a separate repository with its own access.
- **Changing:** with `main` protected, nothing reaches it without a pull request. To require a specific team's
  review for some folders, use the hosting's code-owner rules (GitHub and GitHub Enterprise: `CODEOWNERS`;
  Gitea: check what your version offers).
- **The file guard** ([architecture.md](architecture.md#hooks)) keeps business users' work from changing the
  project's context (`AGENTS.md`, `CLAUDE.md`), its declaration (`.eunomai/`), Claude's configuration (`.claude/`,
  `.mcp.json`), continuous
  integration (`.gitea/`, `.github/`...) and files Windows runs (`.bat`, `.ps1`...): IT changes those through its
  own pull requests. It prevents mistakes; it does not replace the two points above.

## The project's context

Put an `AGENTS.md` at the root of `main`: what the project is for, who uses it, the domain's words, the systems it
touches, rules with their source, and what is out of bounds. The specialist reads it from the server at the start
of every session, before anything personal in the user's session. Keep it short (it is cut at 20,000 characters);
when the specialist proposes lines for it in a pull request, IT decides.

## Where code may be written

Whether the specialist may write code in the project, and with which technologies, the project declares in
`.eunomai/project.toml` on `main`:

```toml
[development]
code = true
technologies = ["Python", "HTML, CSS and JavaScript"]   # empty: any
```

The connector reads it from the server, never from the user's folder, and business users' versions cannot change
it. Protect it like `AGENTS.md`. Without a `[development]` section, the build's `free_development` decides
([configuration](configuration.md#the-specialist)); a file that is not valid allows no code, and says why.

## A test environment without waiting for IT

For users who change things often and need to see them working, a project can give them a test environment they
update themselves; everything else still goes through IT's review. Declare it in `.eunomai/project.toml` on `main`:

```toml
[test]
branch = "pruebas"                        # the branch the test environment follows
url = "https://app-test.example.internal" # where users see it (optional)
```

In Cowork the specialist offers it after a save whose tests pass (`version_to_test`), which refuses a version the
[dependency audit](barriers.md#dependencies) does not allow. What protects it is on the servers, so it holds whichever
way someone tries, from Cowork or not:

| Layer | What IT sets up | What it prevents |
|---|---|---|
| 1. The test environment is not trusted | A server apart from production, with no route to it, test or anonymised data, credentials that open only the test environment | Unreviewed code reaching production or real data |
| 2. The server pulls the branch | The [branch-following agent](../templates/test-environment-agent/README.md), with a read-only deploy key | The test environment's credentials being anywhere but on that server |
| 3. The git server's CI only tests | Workflows on users' branches run without secrets, on runners that deploy nothing | A branch's code reading secrets in CI |
| 4. The git server decides who updates the test branch | A protected branch only one team may push and force-push to: push and force-push allowlists (Gitea), a ruleset that team may bypass (GitHub), "Allowed to push and merge" and "Allowed to force push" (GitLab; groups need Premium) | Anyone else putting a version there, by any client |
| 5. Production takes `main` only | The same agent following `main` on the production server; `main` changes only through reviewed pull requests | Unreviewed code in production |
| 6. Least access | Write access only where needed; `AGENTS.md`, `.eunomai/` and workflow folders protected by code owners or protected file patterns | A valid account doing more than its job |

Deploying from the git server's CI with repository secrets is not recommended: anyone who can push a branch can
read them, and Gitea has no secrets per environment ([sources](sources.md#outside-claude)).

## Seeing the application on a person's computer

Where IT turned on [`app_preview`](configuration.md#seeing-the-application-on-a-persons-computer), a project can let
people see the real application on their own computer, for up to an hour. It runs code nobody has reviewed yet, with
their rights: [what that means](barriers.md#the-preview-on-the-persons-computer). Declare it in
`.eunomai/project.toml` on `main`:

```toml
[preview]
setup = [["python", "-m", "app.demo.generate"]]   # optional: commands that run before, in order
run = ["uvicorn", "app.main:app", "--no-proxy-headers", "--host", "127.0.0.1", "--port", "{port}"]

[preview.environment]
APP_ENVIRONMENT = "development"
APP_DATABASE_URL = "sqlite:///{data}/preview.db"   # kept across versions, until the person says stop
```

| Rule | Why |
|---|---|
| Each command is a list of words, run as `uv run --frozen <words>`, with no shell text (`&&`, `\|`, `;`, `>`, `$(`) in a word | What IT reviewed is what runs |
| The program is `python <a file of the project>`, `python -m <module>` other than `pip`, `ensurepip` or `venv`, or a console script of a package in `uv.lock`. Never `python -c`, nor a script as the program (`app.py`): write `python app.py` | The last is checked once the packages are installed. A script as the program would bring its own metadata and lockfile |
| `{port}`, in `run` only, and `run` must use it. `{data}`, in `run`, `setup` and `[preview.environment]` values: an absolute folder of the connector's, kept across versions, never a program. Nothing else in braces, but JSON's | The connector picks the port, and keeps the address for the next version when it can. Data written in `{data}` survives a change; anywhere else in the copy it goes with each version |
| `setup` runs on every version, on the data kept: make it a migration that leaves what is there | A setup that fails on that data runs once more on none, and the person is told the data was reset |
| `run` says `--host 127.0.0.1`, `--bind` or `-b 127.0.0.1:{port}`, or a bare `127.0.0.1:{port}`, and no other host, wildcard, socket or file descriptor. `-h` is not read: use the long option. The connector cannot know every option: IT does not declare `--ip 0`, and if it did, the listening table would catch it as the application starts | Nothing is offered to the network |
| `[preview.environment]` takes names and text. `GUNICORN_CMD_ARGS`, `FLASK_RUN_HOST`, `UVICORN_HOST`, `HOST` and `BIND`, if set, name 127.0.0.1. It cannot set `PATH`, the home and temporary folders, proxies, or `UV_*`, `PYTHON*`, `PIP_*`, `LD_*`, `DYLD_*`, `SSL_*`, `GIT_*`, `NODE_*`, `CONDA_*` | The connector builds the environment from a short list; no secrets here either, this file is in the repository |
| A `.python-version`, if the project has one, holds one plain version such as `3.13`; blank lines and `#` comments are ignored | It is the Python the preview installs and runs on. Without one, uv chooses |
| The project has a `uv.lock`, and what it needs at run time is in its main dependencies | Development packages are not installed, the project itself is not built, and only wheels are used |
| The application starts with example data and without credentials | A person's computer has no database or secrets of the project's. Production stays the default: development only when set explicitly |

A declaration that breaks a rule shows nothing and goes to IT. These rules catch slips, not malice: **IT reviews the
declaration**, so protect it like `AGENTS.md`.

## Running the tests on a person's computer

Where IT turned on [`app_tests`](configuration.md#running-the-tests-on-a-persons-computer), the specialist runs the
project's tests on the person's computer, those a sandbox cannot run included. Declare the command in
`.eunomai/project.toml` on `main`:

```toml
[tests]
run = ["pytest"]

[tests.environment]
APP_BROWSER_CHANNEL = "msedge"   # a browser the computer has; nothing is downloaded
```

| Rule | Why |
|---|---|
| `run` follows the rules of the preview's commands, with nothing in braces | What IT reviewed is what runs |
| `[tests.environment]` follows the preview's, and cannot set `PYTEST_*` | The connector sets `PYTEST_ADDOPTS` to read the summary |
| Browser tests use a browser the computer has, named by a variable the project reads, such as Edge (`msedge`) on Windows | Nothing is downloaded on a person's computer |
| The tests' output is pytest's | The specialist reads its counts and short summary; the rest stays on the computer |

## Checks on the server

What runs in a user's session is advisory for IT; what runs on the server is not:

- **Continuous integration on every pull request:** the tests, and a vulnerability scan of the pinned dependencies
  (for example OSV-Scanner).
- **Workflows from pull requests:** require approval before they run, so a version cannot change what runs on
  IT's runners with access to secrets.
- **Protected files:** where the hosting offers it, require IT's review for `AGENTS.md`, `.eunomai/`, `.claude/`,
  workflow folders and lockfiles (code owners or protected file patterns).

## Content

- **No secrets** in the repository, ever: passwords, keys, connection strings.
- **Large or frequently changing binaries** (big spreadsheets, videos) make history heavy. Keep them out of
  the repository. Git LFS is not supported by eunomai-business yet.
- **Personal data** only if the project's purpose requires it, and as in any other shared system.
