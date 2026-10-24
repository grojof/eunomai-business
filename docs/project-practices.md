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
  project's context (`AGENTS.md`, `CLAUDE.md`), Claude's configuration (`.claude/`, `.mcp.json`), continuous
  integration (`.gitea/`, `.github/`...) and files Windows runs (`.bat`, `.ps1`...): IT changes those through its
  own pull requests. It prevents mistakes; it does not replace the two points above.

## The project's context

Put an `AGENTS.md` at the root of `main`: what the project is for, who uses it, the domain's words, the systems it
touches, rules with their source, and what is out of bounds. The specialist reads it from the server at the start
of every session, before anything personal in the user's session. Keep it short (it is cut at 20,000 characters);
when the specialist proposes lines for it in a pull request, IT decides.

## Checks on the server

What runs in a user's session is advisory for IT; what runs on the server is not:

- **Continuous integration on every pull request:** the tests, and a vulnerability scan of the pinned dependencies
  (for example OSV-Scanner).
- **Workflows from pull requests:** require approval before they run, so a version cannot change what runs on
  IT's runners with access to secrets.
- **Protected files:** where the hosting offers it, require IT's review for `AGENTS.md`, `.claude/`, workflow
  folders and lockfiles (code owners or protected file patterns).

## Content

- **No secrets** in the repository, ever: passwords, keys, connection strings.
- **Large or frequently changing binaries** (big spreadsheets, videos) make history heavy. Keep them out of
  the repository. Git LFS is not supported by eunomai-business yet.
- **Personal data** only if the project's purpose requires it, and as in any other shared system.
