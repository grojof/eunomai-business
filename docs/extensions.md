---
type: explanation
title: Extensions
description: "Uses that build on eunomai-business outside this repository, such as an organization-wide knowledge base read from the repositories."
tags: [knowledge-base, configuration]
audience: [organizations]
related: [decisions.md]
---

# Extensions

Uses that build on eunomai-business but live **outside this repository**. Each is an idea for organizations,
marked with its status. None is required.

## A knowledge base built from the repositories

**Status:** the pages are written by the guided flows, each kind with its `type` and tag (0.1.6,
[decision 16](decisions.md#16--an-applications-knowledge-lives-in-its-repository-by-kind)); the organization's
vocabulary and its check are planned (0.2.0). The reading service is an idea.

Business users' repositories accumulate what the organization knows: business rules, specifications, decisions,
glossaries. An organization can run a service that reads those pages from its git server and serves them as a
knowledge base, for example through an MCP server. A developer building an application then gets the business
knowledge needed for business-logic decisions, from the same source the business users maintain.

**What makes it work:** every page must be readable by a machine, not only by people:

- **Metadata in each page** (a front-matter block with `type`, `title`, `description`), the page's path as its
  identity, and links between pages. These are habits taken from the Open Knowledge Format, as
  [eunomai](https://github.com/grojof/eunomai) does for developers' documentation; OKF itself targets data
  catalogs, so only its habits apply.
- **A closed vocabulary per organization:** the allowed page types and tags (for example departments,
  processes, systems) defined once by the organization. Free-form tags drift until search and grouping stop
  working; a short, owned, versioned list stays useful.

**Planned in eunomai-business:** the vocabulary is set in the organization's configuration at build time
([decision 4](decisions.md#4--configuration-at-build-time-by-it)). The guided flows write pages with it, and a
deterministic check (not the model's judgment) verifies it. The plugin still does not manage project files
([decision 5](decisions.md#5--the-plugin-manages-no-project-rules)): the pages are the users' work, written with the
organization's vocabulary.

**Out of scope here:** the reading service, the index and the knowledge-base server.
