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
| Since 2026-10-06, new Cowork tasks on Pro, Max and Ultra run in the cloud; the "Only on your computer" option is gone. The article says nothing of the kind for Team or Enterprise, where local sessions stay one of two places a session can run ([Team and Enterprise](https://support.claude.com/en/articles/13455879)), for "existing desktop deployments" ([architecture](https://support.claude.com/en/articles/14479288)) | [Use Cowork on web, desktop and mobile](https://support.claude.com/en/articles/15520349) | 2026-10-31 | [Decision 1](decisions.md#1--a-local-connector-on-the-users-computer), H16 |
| "Local MCP servers, including plugins that bundle them" need the desktop app "open and connected, even when your session runs in the cloud"; with the app closed, cloud sessions "can't reach your computer" | [What to expect with Claude Cowork in the cloud](https://support.claude.com/en/articles/15811196) | 2026-10-25 | Decision 1, H16 |
| Cowork sessions run in the cloud by default; there the sandbox "can't reach private, internal, link-local, or cloud-metadata addresses" and "local MCP servers don't run in sessions in the cloud" (the article on what to expect in the cloud, above, says the opposite for local MCP servers with the app open) | [Claude Cowork architecture overview](https://support.claude.com/en/articles/14479288) | 2026-10-27 | [Barriers](barriers.md#between-claudes-sandbox-and-the-computer), H16 |
| `CLAUDE_CODE_REMOTE` is set to `true` when Claude Code runs as a cloud session (Claude Code on the web): "read this from a hook or setup script to detect whether you are in a cloud session"; `CLAUDE_CODE_REMOTE_SESSION_ID` is set there too. Whether Cowork's cloud tasks set them is H16 | [Environment variables](https://code.claude.com/docs/en/env-vars) | 2026-10-27 | The guard, H16 |
| A matcher with characters other than letters, digits, `_`, `-`, spaces, `,` and `\|` is an unanchored JavaScript regular expression: wrap it in `^` and `$` for a whole-name match | [Hooks reference](https://code.claude.com/docs/en/hooks) | 2026-10-27 | The guard's hook |
| A command hook with `onFailure: "block"` blocks the tool call when it fails, including when it cannot start | [Hooks reference](https://code.claude.com/docs/en/hooks) | 2026-10-27 | The guard, H16, H17 |
| On Team and Enterprise an owner decides whether Cowork runs in the cloud | [Use Cowork on Team and Enterprise plans](https://support.claude.com/en/articles/13455879) | 2026-10-24 | [Configuration](configuration.md#whose-context-counts) |
| In local sessions "Claude's work runs on the user's computer, with code in an isolated virtual machine" | [Use Cowork on Team and Enterprise plans](https://support.claude.com/en/articles/13455879) | 2026-10-30 | [Recommended stack](recommended-stack.md#the-stylesheet) |
| "Cowork respects your organization's current network egress permissions", applied "when a new Cowork session is created"; "A cloud session uses the same network-access setting that governs local Cowork and chat"; "No network access is the default for Enterprise organizations" | [Use Cowork on Team and Enterprise plans](https://support.claude.com/en/articles/13455879), [Claude Cowork architecture overview](https://support.claude.com/en/articles/14479288) | 2026-10-30 | [Recommended stack](recommended-stack.md#the-stylesheet), H20 |
| Local MCP servers "run on your computer with the same permissions as any other program"; use a dedicated working folder | [Use Cowork safely](https://support.claude.com/en/articles/13364135) | 2026-10-25 | [Barriers](barriers.md) |
| Local MCP servers were moved out of Cowork's VM so admins decide which run; "admins should set a boundary that is absolute and always-on"; an injection came through "a malicious file placed in the user's mounted workspace" | [How we contain Claude across products](https://www.anthropic.com/engineering/how-we-contain-claude) (2026-05-25) | 2026-10-25 | Decisions 6, 7; the file guard |

### Plugins, connectors and extensions

| Fact | Official source | Checked | Relied on by |
|---|---|---|---|
| MCP tunnels let Claude reach MCP servers in a private network over an outbound-only connection; on claude.ai they are "in research preview and are available to organizations on the Claude Enterprise plan by request", with no uptime or continuity commitment, through Cloudflare, and members use them as custom connectors. Tunnels created in the Console serve only the API and Managed Agents | [MCP tunnels (claude.ai)](https://claude.com/docs/connectors/mcp-tunnels/overview), [MCP tunnels (Platform)](https://platform.claude.com/docs/en/agents-and-tools/mcp-tunnels/overview) | 2026-10-27 | [Decision 1](decisions.md#1--a-local-connector-on-the-users-computer), decision 11 |
| A plugin can reference remote and local MCP servers; a local one "runs in Claude Code and in a Cowork session that runs on the user's computer", so "most plugins reference remote servers" | [Decide what to include in your plugin](https://claude.com/docs/connectors/building/what-to-build) | 2026-10-25 | Decision 1 |
| Plugins "are the main way to build third-party extensions for Claude" | [Build plugins for Claude](https://claude.com/blog/build-plugins-for-claude) | 2026-10-26 | [Decision 9](decisions.md#9--it-provides-the-runtime-the-plugin-carries-everything-else) |
| Desktop-extension directory listings "are deprecated… To distribute a local server through the directory, include it in a plugin" | [Submit a connector](https://claude.com/docs/connectors/building/submission.md) | 2026-10-26 | Decision 9 |
| MCPB is "the sanctioned way to distribute local MCP servers", "packaged with its runtime" (Anthropic's own skill) | [build-mcpb skill](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/mcp-server-dev/skills/build-mcpb/SKILL.md) | 2026-10-26 | Decision 9 (weighed against) |
| A plugin's `mcpServers` can name a `.mcpb` bundle, extracted into `.mcpb-cache/` | [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference) | 2026-10-26 | Decision 9 |
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
| Permission rules are `Tool` or `Tool(specifier)`; a `*` in a Bash rule matches any text and a trailing ` *` also the bare command; compound commands are split and each part checked; wrappers and leading assignments are stripped; `Edit` paths are gitignore patterns; a Bash rule "isn't a security boundary around the program" | [Configure permissions](https://code.claude.com/docs/en/permissions) | 2026-10-27 | [Decision 12](decisions.md#12--organization-rules-in-claude-codes-permission-syntax-applied-by-the-guard), `rules.py` and its tests |
| In Cowork the shell is `mcp__workspace__bash`; deny rules that name the whole `Bash` tool apply to it, allow rules never do | [Configure permissions](https://code.claude.com/docs/en/permissions) | 2026-10-27 | The guard's matcher and `Bash` rules |
| A plugin's `settings` only take `agent` and `subagentStatusLine`: a plugin cannot carry permission rules | [Plugin manifest reference](https://code.claude.com/docs/en/plugins-reference) | 2026-10-27 | Decision 12 |
| "In a Cowork session… Claude Code never fetches server-managed settings"; managed settings on the device apply to Cowork on that computer, and a remote session has "no device policy to read" | [Server-managed settings](https://code.claude.com/docs/en/server-managed-settings), [Managed settings](https://code.claude.com/docs/en/managed-settings) | 2026-10-27 | Decision 12, [hooks and rules](hooks.md) |
| Mods (`tool.check`, policy mods) are "in Claude Code only" | [Plugins overview](https://claude.com/docs/plugins/overview) | 2026-10-27 | Decision 12 |
| `allowManagedHooksOnly` stops hooks of plugins not forced through the managed settings' `enabledPlugins` | [Hooks reference](https://code.claude.com/docs/en/hooks) | 2026-10-27 | [Hooks and rules](hooks.md) |
| Agent hooks are experimental: "For production workflows, prefer command hooks"; the `if` field is best effort, "use the permission system rather than a hook to enforce a hard allow or deny" | [Hooks reference](https://code.claude.com/docs/en/hooks) | 2026-10-27 | Decision 12 |

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
| Remote MCP servers (custom connectors) are reached "from Anthropic's cloud infrastructure, rather than from your local device", on every client including Cowork, and must be reachable from the public internet; in Cowork a plugin's remote server is connected from its *Connectors* tab, and a local one loads "when the Cowork session runs on your computer" | [Custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), [Plugin platform support](https://claude.com/docs/plugins/platform-support) | 2026-10-27 | [Decision 11](decisions.md#11--project-plugins-from-a-template-a-project-declares-its-own-development) |
| Organization sync from github.com, GitHub Enterprise Server and GitLab only; otherwise a zip upload | [Sync plugins from a repository](https://claude.com/docs/plugins/org-sync) | 2026-10-25 | Distribution (the organization's choice) |

### Outside Claude

| Fact | Official source | Checked | Relied on by |
|---|---|---|---|
| A Windows package's new files and folders under `AppData` go to a private per-package location; existing ones are changed in place | [How packaged desktop apps run (MSIX)](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes) | 2026-10-26 | [Data on computers](data-on-computers.md) |
| Plugins declare `dependencies` ("name" or "name@marketplace"; a bare name resolves in the plugin's own marketplace); for plugins loaded from claude.ai only entries that name a marketplace are covered | [Manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference#dependencies), [Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies) | 2026-10-26 | [Decision 10](decisions.md#10--a-base-that-holds-for-everyone-projects-bring-their-own-capabilities), H10 |
| "When multiple PreToolUse hooks return different decisions, precedence is `deny` > `defer` > `ask` > `allow`"; a hook's `allow` does not override deny rules | [Hooks reference](https://code.claude.com/docs/en/hooks) | 2026-10-26 | Decision 10 |
| `uv pip compile --universal` writes one list for every platform, with markers; `--generate-hashes`, `--python-version`, `--exclude-newer` (dates or durations such as `14 days`) and `--exclude-newer-package` | [Resolution](https://docs.astral.sh/uv/concepts/resolution/#universal-resolution), [CLI reference](https://docs.astral.sh/uv/reference/cli/#uv-pip-compile); checked with uv 0.13.5 | 2026-10-26 | The specialist's Build (pinning the whole tree) |
| Gitea lists a pull request's reviews (`APPROVED`, `COMMENT`, `REQUEST_CHANGES`; dismissed or stale flags), their line comments (resolved or not) and the conversation | Gitea API 1.27.1, `/swagger.v1.json` of the organization's server | 2026-10-26 | `workspace_status` (`review`) |
| "Any user with write access to your repository has read access to all secrets configured in your repository"; environment secrets are "only available to workflow jobs that use the environment", limited to allowed branches (private repositories: Pro or Team); "required reviewers are only available for public repositories" on Free, Pro and Team | [Security hardening for GitHub Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions), [Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/managing-environments-for-deployment), [Deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments) | 2026-10-27 | [A test environment](project-practices.md#a-test-environment-without-waiting-for-it) |
| Gitea Actions secrets exist per user, organization and repository only | [Gitea secrets](https://docs.gitea.com/usage/actions/secrets) | 2026-10-27 | [A test environment](project-practices.md#a-test-environment-without-waiting-for-it) |
| Pipelines that run unreviewed code: "executed on isolated nodes", each with only "the credentials it needs" (Poisoned Pipeline Execution) | [OWASP CICD-SEC-4](https://owasp.github.io/www-project-top-10-ci-cd-security-risks/CICD-SEC-04-Poisoned-Pipeline-Execution) | 2026-10-27 | [A test environment](project-practices.md#a-test-environment-without-waiting-for-it) |
| GitOps: "Software agents automatically pull the desired state declarations from the source" | [OpenGitOps principles](https://opengitops.dev/) | 2026-10-27 | [Branch-following agent](../templates/test-environment-agent/README.md) |

### Recommended stack

| Fact | Official source | Checked | Relied on by |
|---|---|---|---|
| 84 malicious versions of 42 `@tanstack/*` packages were published on 2026-05-11 through the project's trusted-publisher binding, and removed about 3 to 4.5 hours later | [TanStack postmortem](https://tanstack.com/blog/npm-supply-chain-compromise-postmortem) | 2026-10-27 | [Decision 13](decisions.md#13--one-recommended-stack-pages-made-on-the-server) |
| htmx's authors: htmx 2 "will continue to be supported indefinitely"; 4.0 stays on npm's `next` tag "until some point in early 2027" | [htmx 4.0.0 announcement](https://four.htmx.org/announcements/2026-08-28-htmx-4.0.0-is-released) | 2026-10-27 | [Recommended stack](recommended-stack.md) |
| Row grouping, aggregation, Excel export and the server-side row model are AG Grid Enterprise features | [AG Grid: community vs enterprise](https://www.ag-grid.com/javascript-data-grid/community-vs-enterprise/) | 2026-10-27 | [Recommended stack](recommended-stack.md) |
| Pydantic v2 serialises `Decimal` as a string in JSON | [Pydantic: standard library types](https://pydantic.dev/docs/validation/latest/api/pydantic/standard_library_types/) | 2026-10-27 | [Recommended stack](recommended-stack.md) |
| psycopg 3 returns `numeric` as `Decimal`; pyodbc returns `decimal` as `Decimal` | [psycopg: adaptation](https://www.psycopg.org/psycopg3/docs/advanced/adapt.html), [pyodbc: data types](https://github.com/mkleehammer/pyodbc/wiki/Data-Types) | 2026-10-27 | [Recommended stack](recommended-stack.md) |
| GitHub Packages hosts npm, RubyGems, Maven, Gradle, NuGet and containers, not Python | [Introduction to GitHub Packages](https://docs.github.com/en/packages/learn-github-packages/introduction-to-github-packages) | 2026-10-27 | Decision 14 (weighed against) |
| Gitea's package registry (since 1.17, unless packages are turned off) includes PyPI and npm | [Gitea packages](https://docs.gitea.com/usage/packages/overview) | 2026-10-27 | Decision 14 (weighed against) |
| Securing htmx: escaping, no user content in attributes or scripts, CSP | [Web security basics with htmx](https://htmx.org/essays/web-security-basics-with-htmx/) | 2026-10-27 | [Recommended stack](recommended-stack.md) |
| Web Awesome's free core is MIT; Pro (paid, per seat) adds components such as its data grid and charts | [Web Awesome Pro](https://webawesome.com/pro) | 2026-10-27 | Decision 13 |
| Excel stores numbers as double-precision floating point, 15 significant digits | [Microsoft Learn: floating-point arithmetic in Excel](https://learn.microsoft.com/en-us/troubleshoot/microsoft-365-apps/excel/floating-point-arithmetic-inaccurate-result) | 2026-10-27 | [Recommended stack](recommended-stack.md) |
| Python's default decimal context has a precision of 28 digits | [Python: decimal](https://docs.python.org/3/library/decimal.html) | 2026-10-27 | [Recommended stack](recommended-stack.md) |
| Bootstrap 5.3.8 is published as "compiled files for quick drop-in usage"; it has no `dependencies`, and its one peer dependency, Popper, comes inside the bundled files | [Bootstrap: contents](https://getbootstrap.com/docs/5.3/getting-started/contents/), [npm registry entry](https://registry.npmjs.org/bootstrap/5.3.8) | 2026-10-30 | [Decision 14](decisions.md#14--tailwind-with-daisyui-behind-macros-the-organizations-layer-is-a-base-application) |
| Tailwind's standalone build is a self-contained executable, "no Node.js or npm required". Release v4.3.3 carries `tailwindcss-linux-x64` (about 110 MB), `tailwindcss-windows-x64.exe` and `sha256sums.txt`; downloads redirect from `github.com` to `release-assets.githubusercontent.com`. MIT | [Standalone CLI](https://tailwindcss.com/blog/standalone-cli), [v4.3.3](https://github.com/tailwindlabs/tailwindcss/releases/tag/v4.3.3), [licence](https://github.com/tailwindlabs/tailwindcss/blob/main/LICENSE) | 2026-10-30 | Decision 14, [recommended stack](recommended-stack.md#the-stylesheet) |
| daisyUI 5 works with that executable, "without a JS runtime like Node", through `daisyui.mjs` and `daisyui-theme.mjs` from its GitHub release; its instructions download `latest`, and release v5.7.50 carries no checksums. MIT | [daisyUI standalone](https://daisyui.com/docs/install/standalone/), [v5.7.50](https://github.com/saadeghi/daisyui/releases/tag/v5.7.50), [licence](https://github.com/saadeghi/daisyui/blob/master/LICENSE) | 2026-10-30 | Decision 14, [recommended stack](recommended-stack.md#the-stylesheet) |
| Setting a namespace to `initial` (`--color-*: initial`) removes the default utilities that use it, "like `bg-red-500`" | [Tailwind: theme variables](https://tailwindcss.com/docs/theme) | 2026-10-30 | Decision 14, [recommended stack](recommended-stack.md#the-stylesheet) |
| daisyUI publishes an "Official daisyUI component-library skill for Tailwind CSS" as `llms.txt`; themes are CSS variables such as `--color-primary`; its install steps use npm or a CDN | [daisyUI llms.txt](https://daisyui.com/llms.txt) | 2026-10-30 | Decision 14, [recommended stack](recommended-stack.md#the-stylesheet) |
| daisyUI's store sells templates and charts; Blueprint, its MCP server, is licensed by the month or for life. Tailwind Plus's pages open on a sign-in, so its terms were not read | [daisyUI store](https://daisyui.com/store/), [Blueprint](https://daisyui.com/blueprint/), [Tailwind Plus](https://tailwindcss.com/plus) | 2026-10-30 | Decision 14, [recommended stack](recommended-stack.md#the-stylesheet) |

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
| A plugin's local server launched with `uv` does not start without uv on the computer; the guard hook, set to block, then blocks every write and shell command | 2026-10-26 ([MCPB research](../research/mcpb-uv/README.md)) |
| A `.mcpb` bundle declared inside a plugin is not extracted or started in Cowork (empty `.mcpb-cache/`) | 2026-10-26 ([MCPB research](../research/mcpb-uv/README.md)) |
| Claude Desktop runs a `uv` extension as `<its uv> run <the manifest's arguments>`; uv then prefers a Python installed on the computer unless told `--managed-python` | 2026-10-26 ([MCPB research](../research/mcpb-uv/README.md)) |
| The first business-user test went from a vague request to a pull request through every stage; its departures drove decisions 7 and 8 | 2026-10-24 (H11–H14) |
| The recommended stack's server resolves to about 25 Python packages (fastapi, uvicorn, pydantic, sqlalchemy, alembic, psycopg[binary], jinja2, pyodbc, xlsxwriter, python-multipart; `uv pip compile`, Python 3.12; 61 with `fastapi[standard]`, which it avoids) | 2026-10-27 ([recommended stack](recommended-stack.md)) |
| A minimal React page (Vite, React, TypeScript, Tailwind, shadcn/ui on Radix, TanStack Query and Table) has about 200 lockfile entries, about 590 with the usual linting, testing and client generation (`npm install --package-lock-only --ignore-scripts`) | 2026-10-27 (decision 13) |
| Inside a real local Cowork sandbox (Linux x86_64), Tailwind's `tailwindcss-linux-x64` downloaded, its SHA-256 matched and it ran. One sandbox, on one organization's network rules | 2026-10-30 ([open checks](recommended-stack.md#open-checks), H20) |
| Chart.js 4.6.1 and ECharts 6.1.0 on the same data, under `style-src 'self'` in Chrome: Chart.js has no violation; ECharts' default tooltip has 9 to 10 distinct ones and loses its layout, none with `renderMode: "richText"`. Neither was tried with a screen reader | 2026-10-31 ([recommended stack](recommended-stack.md)) |

## Research done

| Study | Date | Question | Outcome |
|---|---|---|---|
| First business-user test | 2026-10-24 | Does the specialist take a business user to a reviewable pull request? | Yes, with departures: a launcher on the user's computer, a command given to the user, personal context used. Fixed by decisions 7 and 8 and the file guard |
| Independent audit (security, skills, coherence, decisions) | 2026-10-25 | Do those fixes hold? | A path traversal in saving, audit bypasses and context spoofing found and fixed before merging ([#19](https://github.com/grojof/eunomai-business/pull/19)) |
| Public skill and workflow repositories | 2026-10-24 | What to borrow for a compact specialist | Evidence before claims and tests that fail first (obra/superpowers), one question at a time and a consistency pass (github/spec-kit), process sized to the request (BMAD, GSD) ([guided flows](guided-flows.md)) |
| Anthropic's official skills and plugins | 2026-10-24 | What to reuse rather than rebuild | Anthropic's review checklist became `review-skills`; document skills are proprietary (recommend, never bundle) |
| A Node.js connector | 2026-10-25 | Remove uv and Python from users' computers? | Not now: plugins get no Node from Claude Desktop, and the JavaScript git library's tree fails the dependency rules ([research](../research/node-connector/README.md)) |
| Viability: official guidance, GitHub issues, community | 2026-10-25 | Is the approach supported, safe and lasting? | Governance flow is mainstream (it mirrors GitHub's Copilot coding agent); the local server plus hooks in Cowork is a supported but fragile layer, so enforcement belongs on the git server too. Follow-ups in [project practices](project-practices.md#checks-on-the-server) |
| MCPB extension of type `uv`, standalone and inside the plugin | 2026-10-26 | Ship the same Python connector with nothing installed by users? | Standalone: works, but two pieces, less organization control and a guard that fails open. Inside the plugin: does not run in Cowork. Decided: one plugin, uv deployed by IT ([decision 9](decisions.md#9--it-provides-the-runtime-the-plugin-carries-everything-else), [research](../research/mcpb-uv/README.md)) |
| A project plugin next to eunomai-business (H10) | 2026-10-26 | Can a project bring its own skills, server and hooks as a plugin that depends on eunomai-business? | P1–P6 pass with a member's own upload (2026-10-27); the organization's upload pending ([research](../research/project-plugin/README.md), [decision 10](decisions.md#10--a-base-that-holds-for-everyone-projects-bring-their-own-capabilities)) |

## Platform issues to watch

User reports on GitHub, not official statements; each is a reason to re-test after Claude Desktop updates.

| Issue | What it means here |
|---|---|
| [anthropics/claude-code#98498](https://github.com/anthropics/claude-code/issues/98498), [#96087](https://github.com/anthropics/claude-code/issues/96087) | Under MSIX, interpreters outside the package may not find plugin files |
| [#94395](https://github.com/anthropics/claude-code/issues/94395), [#87537](https://github.com/anthropics/claude-code/issues/87537) | `${VAR}` in a plugin's `env` and some variable names are dropped: keep `env` values literal (as the build does) |
| [#98839](https://github.com/anthropics/claude-code/issues/98839) | In cloud sessions hooks may run in the container: there the guard reads `CLAUDE_CODE_REMOTE`, or cannot start and blocks |
| [#73955](https://github.com/anthropics/claude-code/issues/73955) | MCP tool calls time out after about 60 s in Cowork: clone and update must stay quick |
| [#104181](https://github.com/anthropics/claude-code/issues/104181) | Background sessions start with a minimal PATH: an absolute path for `uv` in the build avoids it |
| [GHSA-4p2j-qj3c-6x84](https://github.com/anthropics/claude-code/security/advisories/GHSA-4p2j-qj3c-6x84) | A `git.exe` planted in a folder ran: the connector runs no `git.exe` (dulwich), and the guard refuses writing executables |
| [modelcontextprotocol PR #2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) | MCP roots are deprecated: the connector does not use them (workspaces are named in each call) |
