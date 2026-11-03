---
type: reference
title: Compliance
description: "For audits: what eunomai-business does with data and code, mapped to data protection, information-security controls and the software supply chain, and what remains the organization's responsibility."
tags: [compliance, data, security, supply-chain]
audience: [it, security, data-protection, auditors]
related: [data-on-computers.md, barriers.md, decisions.md]
---

# Compliance

eunomai-business does not make an organization compliant: it provides the facts and the controls an audit asks
about. Each row points to where the evidence lives. This page is not legal advice.

## Who does what

| Party | Role |
|---|---|
| **The organization** | Decides purposes, legal basis and retention; controller of the data in its repositories and servers; builds, configures and publishes the plugin |
| **Anthropic (Claude)** | Processes the conversation under the organization's Claude plan and agreements; outside this plugin |
| **eunomai-business** | Software on users' computers. Sends data only to the organization's sign-in providers and git server, and package names to public registries ([details](data-on-computers.md#calls-to-public-services)). Diagnostic builds can also request any address IT asks to test |

## Personal data

Terms as in the EU General Data Protection Regulation (GDPR).

| Topic | eunomai-business | Evidence |
|---|---|---|
| Data handled | Sign-in tokens; the user's name and e-mail in save points; whatever users write in their workspaces; the Windows user name in paths of the diagnostics log and of reports for IT | [Data on computers](data-on-computers.md) |
| Minimization | Tokens never reach Claude; the diagnostics log records field names, not values; reports to IT carry no tokens and travel only if the user sends the e-mail; the dependency check sends package names and versions only | [Barriers](barriers.md), [Data](data-on-computers.md) |
| Location | The user's computer and the organization's servers | [Data](data-on-computers.md) |
| Security of processing | Tokens encrypted per user, TLS verified with the operating system's store, public sign-in clients with PKCE | [Barriers](barriers.md#sign-in-and-tokens) |
| Erasure | Uninstalling and revoking, step by step; repository history follows the organization's own policy | [Uninstalling](data-on-computers.md#uninstalling) |
| Records of processing, impact assessment, information to users | The organization's; the pages above are their input | — |

## Information-security controls

Grouped by the control themes of an information-security management system (such as ISO/IEC 27001).

| Theme | What eunomai-business does | Evidence |
|---|---|---|
| Access control | Sign-in through the organization's identity provider; permissions stay on the git server; the main branch is protected by the connector and should be by the server | [Configuration](configuration.md), [Barriers](barriers.md#git), [Practices](project-practices.md) |
| Cryptography | TLS with the operating system's certificate store; tokens encrypted at rest | [Barriers](barriers.md#sign-in-and-tokens) |
| Change management and traceability | Every change is a version with save points under the user's identity, proposed as a pull request reviewed by IT; a backup before every automatic update | [Barriers](barriers.md#bringing-the-latest-changes), [Guided flows](guided-flows.md) |
| Secure development | Tests for the connector's barriers; deny-by-default dependency rules; documented decisions | [Barriers](barriers.md), [Decisions](decisions.md), [Validation](validation/hypotheses.md) |
| Logging and incidents | No logging by default (diagnostics only when enabled); every stop produces a report for IT | [Barriers](barriers.md#when-the-connector-stops) |
| Supplier relationships | Dependencies pinned and checked; the components and licenses listed below | [Barriers](barriers.md#dependencies) |

## Software supply chain

- **Dependencies:** the whole tree is locked and checked by the project's own rules; users' computers install
  exactly that tree, with every package's hash verified ([barriers](barriers.md#dependencies)). A weekly workflow
  re-checks it, proposes updates and opens an issue for any vulnerability without an allowed fix.
- **Licenses of the locked runtime tree** (43 packages, some installed only on Windows, Linux or web browsers): permissive (MIT, BSD, Apache-2.0, PSF) except two, both compatible
  with use as a dependency:

  | Package | License | Use |
  |---|---|---|
  | dulwich | Apache-2.0 OR GPL-2.0-or-later | Used under Apache-2.0 |
  | certifi | MPL-2.0 | Unmodified; MPL obligations apply only to changes in its own files |

- **The complete list:** `connector/sbom.cdx.json`, a CycloneDX 1.5 software bill of materials with every
  runtime package, its version, hashes, license and dependencies. It ships inside the plugin.
- **eunomai-business's own license:** not yet chosen.

## The organization's responsibility

- The legal basis for using Claude, and informing users about it.
- The agreement with Anthropic, and Cowork's settings (for example, whether tasks may run in the cloud).
- An impact assessment, where required.
- Retention and backups of repositories; protection of the main branch on the git server.
- Revoking access when someone leaves (identity provider, git server).
- A `support_email` so that users can reach IT when the connector stops, and send requests for new projects.
