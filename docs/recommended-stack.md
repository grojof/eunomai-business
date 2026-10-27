---
type: reference
title: Recommended stack
description: "The technologies eunomai-business recommends for business users' applications, the organization's layer of brand and components on top, what is not allowed and why, and the open checks."
tags: [stack, technologies, components, supply-chain]
audience: [it, developers]
related: [decisions.md, configuration.md, project-practices.md, sources.md]
---

# Recommended stack

One stack for every application a business user builds with Cowork, so IT reviews the same kind of code every
time and every application looks like the organization's. The reasons are in
[decision 13](decisions.md#13--one-recommended-stack-pages-made-on-the-server); the facts behind them in
[sources](sources.md#recommended-stack).

## The stack

| Piece | Choice | Why |
|---|---|---|
| Server | Python 3.12+, FastAPI, Pydantic v2; uv with `uv.lock` | Typed contracts serve the pages, an API and AI tools alike |
| Data | PostgreSQL, SQLAlchemy 2, Alembic, psycopg 3 | Mature; versioned migrations; `numeric` arrives as `Decimal` |
| Reading another system's SQL Server | pyodbc with Microsoft's ODBC Driver 18 and a read-only user | `decimal` arrives as `Decimal` |
| Pages | Jinja2 with escaping always on, htmx 2.0, Alpine in its CSP build | No Node and no build step; htmx 2 is supported indefinitely |
| Tables | Made on the server (paged, sorted and filtered there); Tabulator where grouping or editing is needed | Tabulator groups and exports for free; AG Grid charges for it |
| Charts | Apache ECharts, one file | Apache licence, enough for dashboards and plans |
| Excel | XlsxWriter, on the server | Real number and date cells, rounded by the application's rules |
| Numbers, dates, times | `Decimal` end to end, dates as dates, moments in UTC shown in the user's time zone; one formatter of the application's own | The browser never computes, so nothing passes through floating point |

The few JavaScript files are copied into the repository with their version, origin and hash (`vendor.json`) and
served with Subresource Integrity. Exact versions live in each template's lock files, not here.

## The organization's layer

| Piece | Owner | Contents |
|---|---|---|
| eunomai-business | The product, the same for every organization | This stack as the default technologies, the guard and its [deny rules](hooks.md) |
| The organization's plugin | Its IT | `tokens.css` (colours, fonts, spacing, radius, with shadcn's variable names), logos and self-hosted fonts, a package of Jinja macros with a catalogue page, a skill that makes Claude use only them |
| A project plugin | IT, per project | The project's tools and rules ([decision 11](decisions.md#11--project-plugins-from-a-template-a-project-declares-its-own-development)) |

A component is one macro and its CSS, written only with the brand's variables. It is published with a version: a
git tag pinned in `uv.lock` (any git server), or the organization's PyPI registry where the git server has one
(Gitea does; GitHub Packages does not host Python).

## Not allowed, and why

| Not allowed | Why |
|---|---|
| npm, Node, `package.json` in a business user's application | The npm tree is where the supply-chain attacks of 2025 and 2026 happened; a React page pulls in hundreds of packages |
| `<script src>` from a CDN | Code without a pinned version or IT's review |
| `pip install`, `requirements.txt` without hashes, `--extra-index-url`, git dependencies on a branch | Unpinned code and dependency confusion |
| `float` for amounts or quantities; numbers in JSON for decimals | Precision is lost silently |
| A login of the application's own | Identity comes from the organization's identity proxy |
| Streamlit, NiceGUI, Reflex, Dash; Tailwind or Bootstrap in business users' applications | Each brings its own look and a build or npm tree; the brand lives in the organization's tokens |

The guard can enforce the first and third rows with [deny rules](hooks.md#add-a-rule) such as `Bash(npm *)`.

## For IT only: React

React, TypeScript and shadcn/ui stay available to IT for an application that really needs a rich client (drag and
drop, spreadsheet-like editing). It takes its own decision, pnpm with a minimum release age and blocked install
scripts, and a lock file scanned in CI. The brand already uses shadcn's variable names, so it needs no second
design layer.

## Names for `technologies`

In a project's [`.eunomai/project.toml`](project-practices.md#where-code-may-be-written) or the build's
`allowed_technologies`: `python`, `fastapi`, `sqlalchemy`, `postgresql`, `jinja2`, `htmx`, `alpine`, `tabulator`,
`echarts`, `xlsxwriter`, `pyodbc`.

## Open checks

| Check | How |
|---|---|
| A decimal(38,20) value read from SQL Server reaches the page and Excel unchanged | Frozen real values, compared one by one |
| A 50,000-row table: on the server versus Tabulator | Paging, sorting, export |
| Claude builds three screens from the organization's catalogue | Count the defects; tune the checks in CI |
| An organization's plugin with five macros, published by tag and by registry | Measure IT's effort |

The first application built with this stack, an MRP rebuilt next to an organization's current one, runs these
checks first.
