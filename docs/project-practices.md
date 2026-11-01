---
type: how-to
title: Good practices for project repositories
description: "How to set up and run a repository that business users work on: main branch, line endings, ignored files, permissions, content."
tags: [repositories, git]
audience: [repository-owners]
related: [barriers.md]
---

# Good practices for project repositories

eunomai-business writes no rule into a project; it only refuses to save the files listed below. These are
recommendations for whoever creates and runs a repository that business users work on. They apply to any git hosting (Gitea, GitHub, GitHub
Enterprise, GitLab).

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
```

| Rule | Why |
|---|---|
| Each command is a list of words, run as `uv run --frozen <words>`. No shell: not as the program, nor `&&`, `\|`, `;`, `>` or `$(` in a word | What IT reviewed is what runs |
| `{port}` is the only substitution, in `run` only, and `run` must use it | The connector picks a free port |
| `run` says `127.0.0.1`, and no other host, socket or file descriptor | Nothing is offered to the network |
| `[preview.environment]` takes names and text, and cannot set `PATH`, the home and temporary folders, or `UV_*`, `PYTHON*`, `LD_*`, `DYLD_*` | The connector builds the environment from a short list; no secrets here either, this file is in the repository |
| The project has a `uv.lock`, and what it needs at run time is in its main dependencies | Development packages are not installed, the project itself is not built, and only wheels are used |
| The application starts with example data and without credentials | A person's computer has no database or secrets of the project's. Production stays the default: development only when set explicitly |

A declaration that breaks a rule shows nothing and goes to IT. Protect it like `AGENTS.md`.

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
