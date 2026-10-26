---
type: reference
title: Sources and evidence
description: "Every platform fact eunomai-business's decisions rely on, with its official Anthropic source and the date it was checked; what was measured on real installations; the research done and its outcome; and the platform issues to watch."
tags: [decisions, sources, validation, research]
audience: [it, security, developers]
related: [decisions.md, validation/hypotheses.md, architecture.md]
---

# Sources and evidence

Where each decision comes from. Official Anthropic sources first, then what was measured on a real installation,
then the research done. Pages were read on the date given; many official pages carry no date of their own, so the
date is when they were checked. When a source and a measurement disagree, the measurement wins and both are noted.

## Platform facts the design relies on

### Where Cowork runs, and local connectors

| Fact | Official source | Checked | Relied on by |
|---|---|---|---|
| Since 2026-10-06, new Cowork tasks on Pro and Max run in the cloud; the "Only on your computer" option is gone | [Use Cowork on web, desktop and mobile](https://support.claude.com/en/articles/15520349) | 2026-10-25 | [Decision 1](decisions.md#1--a-local-connector-on-the-users-computer), H16 |
| "Local MCP servers, including plugins that bundle them" need the desktop app "open and connected, even when your session runs in the cloud"; with the app closed, cloud sessions "can't reach your computer" | [What to expect with Claude Cowork in the cloud](https://support.claude.com/en/articles/15811196) | 2026-10-25 | Decision 1, H16 |
| On Team and Enterprise an owner decides whether Cowork runs in the cloud | [Use Cowork on Team and Enterprise plans](https://support.claude.com/en/articles/13455879) | 2026-10-24 | [Configuration](configuration.md#whose-context-counts) |
| Local MCP servers "run on your computer with the same permissions as any other program"; use a dedicated working folder | [Use Cowork safely](https://support.claude.com/en/articles/13364135) | 2026-10-25 | [Barriers](barriers.md) |
| Local MCP servers were moved out of Cowork's VM so admins decide which run; "admins should set a boundary that is absolute and always-on"; an injection came through "a malicious file placed in the user's mounted workspace" | [How we contain Claude across products](https://www.anthropic.com/engineering/how-we-contain-claude) (2026-05-25) | 2026-10-25 | Decisions 6, 7; the file guard |

### Plugins, connectors and extensions

| Fact | Official source | Checked | Relied on by |
|---|---|---|---|
| A plugin can reference remote and local MCP servers; a local one "runs in Claude Code and in a Cowork session that runs on the user's computer", so "most plugins reference remote servers" | [Decide what to include in your plugin](https://claude.com/docs/connectors/building/what-to-build) | 2026-10-25 | Decision 1 |
| Local servers are the choice for "systems behind your firewall" and "Direct filesystem access for code editing and Git operations"; Node.js "Included with Claude Desktop"; desktop-extension directory listings are deprecated: "include it in a plugin" | [Build a desktop extension with MCPB](https://claude.com/docs/connectors/building/mcpb) | 2026-10-25 | Decision 1; [Node research](../research/node-connector/README.md); [MCPB research](../research/mcpb-uv/README.md) |
| MCPB server type `uv` (manifest 0.4): dependencies "installed by the host application using UV", "No user Python installation required" | [MCPB manifest specification](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md) | 2026-10-25 | [MCPB research](../research/mcpb-uv/README.md) |
| What each surface loads: hooks in Cowork and Claude Code; local MCP "when the Cowork session runs on your computer"; `settings` ignored; `${user_config.*}` without default ignored; a top-level `bin/` cannot be installed | [Plugin feature support across platforms](https://claude.com/docs/plugins/platform-support) | 2026-10-25 | [Configuration](configuration.md) (build-time settings), plugin layout |
| Every person who installs a plugin receives its files: no secrets in `.mcp.json` | [Plugin structure and testing](https://claude.com/docs/plugins/build) | 2026-10-25 | Decision 2 (public clients, no secrets) |
| Plugins "can execute arbitrary code on your machine with your user privileges"; hooks and MCP servers run outside the sandbox | [Plugin security](https://code.claude.com/docs/en/plugins/security) | 2026-10-25 | [Barriers](barriers.md) |
| Outbound-only MCP tunnels to private servers: research preview, Enterprise on request | [MCP tunnels](https://claude.com/docs/connectors/mcp-tunnels/overview) | 2026-10-25 | Watch list (a future remote path) |

### Hooks

| Fact | Official source | Checked | Relied on by |
|---|---|---|---|
| Hooks in Cowork run "on the device itself and not in Cowork's virtual machine"; on Windows without Git Bash, in PowerShell | [Claude Desktop extensions (third-party deployments)](https://claude.com/docs/third-party/claude-desktop/extensions) | 2026-10-24 | [Architecture: hooks](architecture.md#hooks) |
| `onFailure: "block"`, the `shell` field, the PreToolUse `deny` answer, and `mcp_tool` hooks (`server: plugin:<plugin>:<server>`) | [Hooks reference](https://code.claude.com/docs/en/hooks) | 2026-10-25 | The file guard; [Node research](../research/node-connector/README.md) N4 |
| 2026-10-15: on Windows without Git for Windows, a failed shell-form PreToolUse hook without `onFailure` blocks the tool | [Cowork changelog](https://claude.com/docs/cowork/changelog) | 2026-10-24 | The guard sets `onFailure` explicitly |

### Context and instructions

| Fact | Official source | Checked | Relied on by |
|---|---|---|---|
| Organization instructions take precedence over a user's own when they contradict | [Organization instructions](https://support.claude.com/en/articles/14546867) | 2026-10-25 | [Decision 8](decisions.md#8--the-projects-context-belongs-to-it) |
| Cowork has global and folder instructions; reading a folder's `CLAUDE.md` or `AGENTS.md` is not documented for Cowork (the changelog lists `AGENTS.md` for Code) | [Get started with Cowork](https://support.claude.com/en/articles/13345190), [Cowork changelog](https://claude.com/docs/cowork/changelog) | 2026-10-25 | Decision 8: the connector hands the context over |
| Instructions are context, not enforced configuration; only hooks enforce | [Memory](https://code.claude.com/docs/en/memory) | 2026-10-24 | The guard and the connector's barriers |

### Skills and organization controls

| Fact | Official source | Checked | Relied on by |
|---|---|---|---|
| "Use Skills only from trusted sources"; audit every file of a third-party skill | [Agent Skills: security considerations](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview#security-considerations) | 2026-10-25 | `review-skills` |
| The review checklist for skills in organizations; scanning "complements, but doesn't replace" it; coexistence of skills | [Skills for enterprise](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/enterprise) | 2026-10-25 | `review-skills` |
| Skill authoring: concise, under 500 lines, references one level deep, third-person descriptions | [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) | 2026-10-25 | The `specialist` skill |
| Plugin availability per organization (Not available, Available, Installed by default, Required), per group on Enterprise, a pilot with chosen people on Team; skill and plugin scanning; publishing that requires review (Team default: Open) | [Manage plugins for your organization](https://claude.com/docs/plugins/admin), [Skill and plugin scanning](https://support.claude.com/en/articles/15927065) | 2026-10-26 | [Configuration](configuration.md#whose-context-counts) |
| Desktop extensions: Owners enable an allowlist and upload their own `.mcpb`, available to every member to install; machine-level policy (`isDesktopExtensionEnabled`, `isLocalDevMcpEnabled`…) overrides it; no policy forces Desktop's own uv | [Desktop extension allowlist](https://support.claude.com/en/articles/12592343-enabling-and-using-the-desktop-extension-allowlist), [Enterprise configuration for Claude Desktop](https://support.claude.com/en/articles/12622667-enterprise-configuration-for-claude-desktop) | 2026-10-26 | [MCPB research](../research/mcpb-uv/README.md) |
| Claude Desktop prefers a uv installed on the computer and otherwise downloads its own, checked against a checksum (an Anthropic staff answer on the MCPB repository) | [mcpb#203](https://github.com/modelcontextprotocol/mcpb/issues/203) | 2026-10-26 | [MCPB research](../research/mcpb-uv/README.md) |
| Organization sync from github.com, GitHub Enterprise Server and GitLab only; otherwise a zip upload | [Sync plugins from a repository](https://claude.com/docs/plugins/org-sync) | 2026-10-25 | Distribution (the organization's choice) |

## Measured on real installations

Full status in [validation](validation/hypotheses.md). Facts measured here that no official page states:

| Fact | Measured |
|---|---|
| Claude Desktop installed as a Windows package (MSIX) redirects the connector's `%LOCALAPPDATA%` to `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local` | 2026-10-24 ([data on computers](data-on-computers.md)) |
| Cowork hands hooks the tools `Write`, `Edit`, `Read` and `mcp__workspace__bash` | 2026-10-24, hook log |
| A plugin's `"command": "node"` server does not get Claude Desktop's Node: without Node on the PATH it does not start | 2026-10-25 ([Node research](../research/node-connector/README.md), N1) |
| An `mcp_tool` hook calling the plugin's own server denies a `Write` in Cowork | 2026-10-25 (N4) |
| An MCPB extension of type `uv` runs, on a computer without uv, on the uv 0.9.7 Claude Desktop downloads at installation (`Claude-Data\claude_<id>\uv-runtime\`); with a uv on the computer, that one is used; the lockfile is honoured either way | 2026-10-26 ([MCPB research](../research/mcpb-uv/README.md), M1–M2) |
| Cowork names an extension's server, for tools and for `mcp_tool` hooks, by its display name | 2026-10-26 (M3–M4) |
| The first business-user test went from a vague request to a pull request through every stage; its departures drove decisions 7 and 8 | 2026-10-24 (H11–H14) |

## Research done

| Study | Date | Question | Outcome |
|---|---|---|---|
| First business-user test | 2026-10-24 | Does the specialist take a business user to a reviewable pull request? | Yes, with departures: a launcher on the user's computer, a command given to the user, personal context used. Fixed by decisions 7 and 8 and the file guard |
| Independent audit (security, skills, coherence, decisions) | 2026-10-25 | Do those fixes hold? | A path traversal in saving, audit bypasses and context spoofing found and fixed before merging ([#19](https://github.com/grojof/eunomai-business/pull/19)) |
| Public skill and workflow repositories | 2026-10-24 | What to borrow for a compact specialist | Evidence before claims and tests that fail first (obra/superpowers), one question at a time and a consistency pass (github/spec-kit), process sized to the request (BMAD, GSD) ([guided flows](guided-flows.md)) |
| Anthropic's official skills and plugins | 2026-10-24 | What to reuse rather than rebuild | Anthropic's review checklist became `review-skills`; document skills are proprietary (recommend, never bundle) |
| A Node.js connector | 2026-10-25 | Remove uv and Python from users' computers? | Not now: plugins get no Node from Claude Desktop, and the JavaScript git library's tree fails the dependency rules ([research](../research/node-connector/README.md)) |
| Viability: official guidance, GitHub issues, community | 2026-10-25 | Is the approach supported, safe and lasting? | Governance flow is mainstream (it mirrors GitHub's Copilot coding agent); the local server plus hooks in Cowork is a supported but fragile layer, so enforcement belongs on the git server too. Follow-ups in [project practices](project-practices.md#checks-on-the-server) |
| MCPB extension of type `uv` | 2026-10-26 | Ship the same Python connector with nothing installed by users? | Technically yes: Claude Desktop ran it with its own uv, honouring the lockfile, and a plugin's hook reached it. Decision pending on the trade-offs: two pieces, less organization control, a guard that lets writes through if the extension is down ([research](../research/mcpb-uv/README.md)) |

## Platform issues to watch

User reports on GitHub, not official statements; each is a reason to re-test after Claude Desktop updates.

| Issue | What it means here |
|---|---|
| [anthropics/claude-code#98498](https://github.com/anthropics/claude-code/issues/98498), [#96087](https://github.com/anthropics/claude-code/issues/96087) | Under MSIX, interpreters outside the package may not find plugin files |
| [#94395](https://github.com/anthropics/claude-code/issues/94395), [#87537](https://github.com/anthropics/claude-code/issues/87537) | `${VAR}` in a plugin's `env` and some variable names are dropped: keep `env` values literal (as the build does) |
| [#98839](https://github.com/anthropics/claude-code/issues/98839) | In cloud sessions hooks may run in the container: with the guard set to block, keep Cowork local until H16 passes |
| [#73955](https://github.com/anthropics/claude-code/issues/73955) | MCP tool calls time out after about 60 s in Cowork: clone and update must stay quick |
| [#104181](https://github.com/anthropics/claude-code/issues/104181) | Background sessions start with a minimal PATH: an absolute path for `uv` in the build avoids it |
| [GHSA-4p2j-qj3c-6x84](https://github.com/anthropics/claude-code/security/advisories/GHSA-4p2j-qj3c-6x84) | A `git.exe` planted in a folder ran: the connector runs no `git.exe` (dulwich), and the guard refuses writing executables |
| [modelcontextprotocol PR #2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) | MCP roots are deprecated: the connector does not use them (workspaces are named in each call) |
