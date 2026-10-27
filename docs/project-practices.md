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

For users who change things often and need to see them working (a key user, an analyst), a project can give them
a test environment they update themselves, while everything else still goes through IT's review:

1. **Declare it** in `.eunomai/project.toml` on `main`:

   ```toml
   [test]
   branch = "pruebas"                        # the branch the test environment follows
   url = "https://app-test.example.internal" # where users see it (optional)
   ```

2. **Protect the branch** on the git server, limited to a team IT keeps. In Gitea (*Settings → Branches*, or the
   API): enable push and the push allowlist with that team (`enable_push`, `enable_push_whitelist`,
   `push_whitelist_teams`), and force push with its allowlist (`enable_force_push`, `enable_force_push_allowlist`,
   `force_push_allowlist_teams`), since each version replaces the last.
3. **Apply the branch to the test environment,** in one of two ways:

   | | How | Where the test environment's credentials live |
   |---|---|---|
   | **The test environment follows the branch** (recommended) | A small job on the test server fetches the branch with a read-only deploy key, runs the migrations and restarts the application | On the test server only |
   | **A workflow on push to the branch** | Gitea Actions runs the tests and applies the version | In the repository's secrets, which reach **every** workflow run in the repository, from any branch (Gitea has no secrets per environment: `environment` in a workflow is ignored) |

   With a workflow, also add a branch protection rule that matches every branch (`*`), with
   `protected_file_patterns` set to `.gitea/workflows/**;.github/workflows/**`: otherwise anyone who can push a
   branch can change a workflow that reads those secrets. A workflow change merged into `main` then also has to
   reach the test branch (IT pushes `main` to it), or every later version is refused for changing a protected file.
4. **Production's credentials never go in this repository's secrets:** what reaches the test branch is the
   version's own code. Production deploys from `main`, by IT's own pipeline.

In Cowork the specialist offers it after a save whose tests pass (`version_to_test`). The connector sends only a
saved version that already has everything on `main` and changes no file only IT changes. For someone outside the
team the server refuses, and their version goes through review as usual. Verified on a real Gitea: H18.

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
