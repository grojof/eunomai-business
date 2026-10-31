---
type: reference
title: Recommended stack
description: "The technologies eunomai-business recommends for business users' applications, how the stylesheet is generated without Node, the base application an organization clones for its brand and components, what is not allowed and why, and the open checks."
tags: [stack, technologies, components, supply-chain]
audience: [it, developers]
related: [decisions.md, configuration.md, project-practices.md, sources.md]
---

# Recommended stack

One stack for every application a business user builds with Cowork, so IT reviews the same kind of code every
time and every application looks like the organization's. The reasons are in
[decision 13](decisions.md#13--one-recommended-stack-pages-made-on-the-server) and
[decision 14](decisions.md#14--tailwind-with-daisyui-behind-macros-the-organizations-layer-is-a-base-application);
the facts behind them in [sources](sources.md#recommended-stack).

## The stack

| Piece | Choice | Why |
|---|---|---|
| Server | Python 3.12+, FastAPI, Pydantic v2; uv with `uv.lock` | Typed contracts serve the pages, an API and AI tools alike |
| Data | PostgreSQL, SQLAlchemy 2, Alembic, psycopg 3 | Mature; versioned migrations; `numeric` arrives as `Decimal` |
| Reading another system's SQL Server | pyodbc with Microsoft's ODBC Driver 18 and a read-only user | `decimal` arrives as `Decimal` |
| Pages | Jinja2 with escaping always on, htmx 2.0, a little plain JavaScript in the application's own file | No Node; its authors support htmx 2 indefinitely. `business-app-base` built every form, including a searchable select, without Alpine.js: a screen holding a lot of browser state may still want its CSP build, as a decision of its own |
| Look | Tailwind CSS 4 with daisyUI 5, behind Jinja macros | Components free to customise, with colours from one theme; screens call macros, so an organization can replace this layer without touching a screen |
| Tables | A native HTML table with daisyUI's classes; paged, sorted, filtered and grouped on the server | Only one page of rows reaches the browser, and a native table needs no keyboard code. Tabulator and AG Grid stay for an application that truly needs spreadsheet-like editing. Exports go through Excel on the server |
| Charts | Chart.js, one file, always with a text summary and the data as a table | MIT and 210 KB, no violation of the Content Security Policy, and tooltips that fit the theme. ECharts is richer, at 1.1 MB, and its default tooltip breaks under the policy ([measured](sources.md#measured-on-real-installations)) |
| Excel | XlsxWriter, on the server | Real number and date cells; Excel keeps 15 significant digits, so values are rounded first by the application's rules |
| Numbers, dates, times | `Decimal` from the database to the page, with the decimal context raised above the data's precision (Python's default is 28 digits) and rounding only where a rule says; dates as dates; moments in UTC shown in the user's time zone; one formatter of the application's own | The browser never computes, so nothing passes through floating point |

The few JavaScript files are copied into the repository with their version, origin and hash (`vendor.json`) and
served with Subresource Integrity. Exact versions live in each application's `uv.lock` and `vendor.json`, not here.

## The stylesheet

Tailwind's standalone executable generates the stylesheet, without Node, wherever templates change: a developer's
computer, the assistant's sandbox or CI. The generated CSS is committed, so servers need neither Node nor the
executable. A business user runs nothing: in Cowork it runs in Claude's sandbox
([decision 7](decisions.md#7--nothing-runs-on-the-users-computer)), which must be able to reach `github.com` and
`release-assets.githubusercontent.com` under the organization's network settings; no network access is the default
on Enterprise ([sources](sources.md#where-cowork-runs-and-local-connectors)). Where it cannot, a developer's computer
or CI generates the stylesheet, as a case for IT ([decision 6](decisions.md#6--the-user-never-resolves-a-technical-problem)).

| Piece | Where it lives | How it is pinned |
|---|---|---|
| Tailwind's executable, about 110 MB | Downloaded once into an ignored cache folder, never committed | Version and SHA-256 in `vendor.json`, compared after downloading; each release publishes `sha256sums.txt` |
| `daisyui.mjs`, `daisyui-theme.mjs` | Copied into the repository; they generate the stylesheet and are never served | Version, origin and hash in `vendor.json`, from a tagged release: daisyUI's releases publish no checksums, and its instructions download `latest` |
| The generated CSS | Committed, and served by the application | A check fails when it is out of date with the templates |

Neither Tailwind nor daisyUI comes through npm or a CDN. Tailwind's own palette is removed, so colours exist only in
the organization's theme, and a test refuses invented values such as `bg-[#ff0000]`, which a removed palette does not
stop. For component classes when writing a macro, assistants have daisyUI's official
[llms.txt](https://daisyui.com/llms.txt); its npm and CDN instructions do not apply here. The paid parts of Tailwind
and daisyUI (Tailwind Plus, daisyUI's store, Blueprint MCP) are not needed.

## The organization's layer

An organization does not install its layer: it clones it.

| Piece | Owner | Contents |
|---|---|---|
| eunomai-business | The product, the same for every organization | This page as the recommended value for `technologies`, the guard and its [deny rules](hooks.md) |
| `business-app-base` | A separate repository, the same for every organization | A demo application: Jinja macros with a gallery of every component, the rules for assistants in its `AGENTS.md`, and the tests that hold them |
| The organization's base | Its IT | A clone of `business-app-base`, made once, with its brand added: daisyUI's theme (colours, radius) and logos |
| An application | Its project | A clone of the organization's base with the demo deleted |
| A project plugin | IT, per project | The project's tools and rules ([decision 11](decisions.md#11--project-plugins-from-a-template-a-project-declares-its-own-development)) |

A component is one macro, written only with the theme's colours. Components are not a package: each clone carries
its own copy, so there is nothing to publish and no version to follow. When the base improves, an application
compares versions and takes what it wants. The prototype a user tries comes before any clone, so its look still
comes from the organization's skills (`organization_skills`, [configuration](configuration.md)).

## Not allowed, and why

| Not allowed | Why |
|---|---|
| npm, Node, `package.json` in a business user's application | The npm tree is where the largest supply-chain attacks of 2025 and 2026 happened (for example TanStack, [sources](sources.md#recommended-stack)); a React page pulls in hundreds of packages |
| `<script src>` from a CDN | Code without a pinned version or IT's review |
| `pip install`, `requirements.txt` without hashes, `--extra-index-url`, git dependencies on a branch | Unpinned code and dependency confusion |
| `float` for amounts or quantities; numbers in JSON for decimals | Precision is lost silently |
| A login of the application's own | Identity comes from the organization's identity proxy |
| Streamlit, NiceGUI, Reflex, Dash | Their own look and state model; Reflex builds a Node front end underneath |
| Colours outside the organization's theme, such as `bg-[#ff0000]` | The brand lives in the theme; a test refuses them |

[Deny rules](hooks.md#add-a-rule) such as `Bash(npm *)`, `Bash(pip install *)` and `Edit(package.json)` stop the
usual ways Claude would break the first and third rows; the rest is checked in IT's review and CI. Rules are
guidance, not a boundary ([limits](hooks.md#limits)).

## For IT only: React

React, TypeScript and shadcn/ui stay available to IT for an application that really needs a rich client (drag and
drop, spreadsheet-like editing). It takes its own decision, pnpm with a minimum release age and blocked install
scripts, and a lock file scanned in CI. The brand's colours are CSS variables under daisyUI's names; how shadcn's
variables map to them is settled with that application.

## Recommended `technologies`

In a project's [`.eunomai/project.toml`](project-practices.md#where-code-may-be-written) or the build's
`allowed_technologies`, the specialist reads plain names:

```toml
technologies = ["Python", "FastAPI", "Pydantic", "SQLAlchemy", "Alembic", "PostgreSQL", "pyodbc", "Jinja2", "htmx",
                "Tailwind CSS", "daisyUI", "Chart.js", "XlsxWriter", "HTML and CSS"]
```

## Open checks

| Check | How |
|---|---|
| A decimal(38,20) value read from SQL Server reaches the page unchanged, and Excel rounded by the application's rules | Frozen real values, compared one by one |
| Claude builds three screens from the base application's catalogue | Count the defects; tune the checks in CI |
| An organization clones the base application, adds its brand and clones it again for an application | Measure IT's effort |
| Generating the stylesheet in Cowork under another organization's network rules ([H20](validation/hypotheses.md)) | In a local task there, download the executable, compare its hash and generate; it has run on one sandbox so far ([measured](sources.md#measured-on-real-installations)) |
| A person opens, from their computer, a server running inside Cowork's sandbox ([H21](validation/hypotheses.md)) | Not documented: try it in a local task. Until it passes, the user sees screenshots and results from the sandbox |
| `business-app-base` ready to clone | As of 2026-10-31 it holds lists over 50,000 rows, Excel, charts and forms, and its tests run on PostgreSQL; it is private, has no licence and is still to be tried in Cowork ([guide](validation/run-the-validation.md#9--the-business-user-test-and-the-newer-checks-h11h18)) |

The first application built with this stack runs these checks first.
