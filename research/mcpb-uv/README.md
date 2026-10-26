# Research: the connector as an MCPB extension of type `uv`

**Closed (2026-10-26): not the way, for now.** As a standalone extension it works (M1–M4 pass): Claude Desktop runs
it with its own uv, honours the lockfile, Cowork sees its tools, and a plugin's hook reaches it. But it splits the
product in two pieces with less organization control and a guard that fails open, and the variant that would
unite them, the bundle inside the plugin, does not run in Cowork. The decision, with its official sources, is
[decision 9](../../docs/decisions.md#9--it-provides-the-runtime-the-plugin-carries-everything-else): one plugin,
uv deployed by IT.

**Question.** Can eunomai-business keep its Python connector, unchanged, and ship it as a Claude Desktop extension
(MCPB) of type `uv`, which Claude Desktop runs managing Python and the dependencies itself, so that business users'
computers need nothing installed? The product would then be two pieces: the extension (the connector) and the
plugin (the skills and the hooks).

**Why it is worth a look.** The MCPB specification has had a `uv` server type since manifest 0.4: dependencies
"installed by the host application using UV", "No user Python installation required"
([MANIFEST.md](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md),
[hello-world-uv](https://github.com/modelcontextprotocol/mcpb/tree/main/examples/hello-world-uv)). Anthropic
recommends MCPB for "systems behind your firewall" and "Direct filesystem access for code editing and Git
operations" ([Build a desktop extension with MCPB](https://claude.com/docs/connectors/building/mcpb)). The type is
marked experimental, so it is tested before anything is restructured.

**How Claude Desktop finds uv.** When an extension of type `uv` is **installed**, Claude Desktop looks for uv on the
computer; if there is none, it downloads its own (uv 0.9.7) from GitHub and checks it against a checksum it holds.
A uv installed on the computer always comes first: "Claude Desktop uses a system UV installation when one is
available" (Anthropic, [mcpb#203](https://github.com/modelcontextprotocol/mcpb/issues/203)). No setting, manifest
field or organization policy forces its own uv
([enterprise configuration](https://support.claude.com/en/articles/12622667-enterprise-configuration-for-claude-desktop)).
Because the choice is made at installation, an extension installed while a uv was on the computer keeps using it:
the first run of M1 was not valid for that reason.

**Rule.** The current plugin stays the product unless M1–M4 all pass. M2 is not negotiable: without the lockfile's
hashes the supply-chain protection is lost.

## Checks

| # | Must hold | How | Status |
|---|---|---|---|
| M1 | Claude Desktop runs a `uv` extension on a computer without uv or Python installed by the user | Uninstall, remove the user's uv, restart, install; `spike_runtime` reports the uv that ran it (`UV`) | **Pass** · Cowork 2026-10-26: `...\Claude-Data\claude_<id>\uv-runtime\uv-0.9.7-win32-x64\uv.exe`, "uv 0.9.7 (0adb44480 2025-10-30)", downloaded by Desktop; no uv on PATH |
| M2 | It honours the bundled `uv.lock` (and so its hashes) | `probe_six` is `1.16.0` (pinned by the lock), not the newest `six` that `pyproject.toml` allows; the manifest runs `uv run --frozen` | **Pass** · with the user's uv and with Desktop's |
| M3 | The extension's tools reach Cowork sessions, local and in the cloud | The `spike_*` tools exist in a Cowork task | **Pass locally** · named `mcp__<display name>__<tool>`. Cloud not tried |
| M4 | A plugin's `mcp_tool` hook can call the extension's server | The test plugin's hook denies a write of `eunomai-spike-guard.txt` | **Pass** · the server is named by the extension's **display name** (`eunomai MCPB spike (uv runtime)`); the manifest name does not work |
| M5 | Organizations can deploy it to users without each one installing it by hand | Admin settings | **Partly** · an Owner uploads the `.mcpb` to the allowlist ([allowlist](https://support.claude.com/en/articles/12592343-enabling-and-using-the-desktop-extension-allowlist)); it is available to every member, each installs it; no per-user or per-group scope documented. Organizations can also deploy it with their own software management |

## Trade-offs

| | Plugin with its own local server (today) | Plugin + MCPB extension |
|---|---|---|
| What each computer needs | uv, installed by IT | Nothing, if Claude Desktop can download uv and Python from GitHub at install (proxy permitting) |
| Which uv runs | The one IT installs (or an absolute path in the build) | The computer's if any, otherwise Desktop's 0.9.7; neither can be forced |
| Supply chain | `uv run --frozen`, lock and hashes | The same arguments in the manifest |
| Organization control | One piece: Required, per group on Enterprise, pilots on Team | Two pieces: the plugin as today; the extension only through the allowlist, installed by each user |
| File guard | Command hook, blocks if it cannot run | `mcp_tool` hook to the extension: lets the write through if the extension is down (the save still refuses it) |
| Validated | H1–H9, a business-user test | This spike only: git, sign-in, DPAPI and data paths inside an extension not yet tried |

## Other variants tried (2026-10-26, Cowork on Windows, no uv on the computer)

| Variant | Result |
|---|---|
| Today's plugin, its server launched with `uv` | Does not start ("Connection closed"); its guard hook cannot run and, set to `onFailure: "block"`, blocks every write and shell command. Claude Desktop lends its uv to standalone `uv` extensions only |
| The same `uv` bundle **inside** a plugin (`"mcpServers": "./eunomai-mcpb-spike.mcpb"`, documented in the [plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference)) | The plugin installs and creates an empty `.mcpb-cache/`; the server never starts and its tools do not appear. Not usable in Cowork today |
| The standalone extension, looked at while running | Desktop runs it as `<its uv 0.9.7> run --frozen --no-dev --directory <extension>`: our arguments, its uv. The virtual environment used the computer's Python 3.12 (uv prefers an installed interpreter); `--python-preference only-managed` would make uv use its own |

## What each piece would hold, and if one is missing

| Piece | Holds | Can |
|---|---|---|
| Extension (the connector) | The Python connector: sign-in, encrypted tokens, git, save, send, propose, the dependency audit, the guard's rules | Everything that reaches the repository, and every barrier that holds: protected main branch, no force, valid paths, protected files put back, executables refused at save, `.git` configuration checked, the audit appended to pull requests |
| Plugin | Text and configuration only: the skills and the guard hook; no code | Guide Claude, and stop a dangerous file before it lands on the user's disk |

| Case | Risk | What still protects |
|---|---|---|
| Plugin without extension | None added: no tools, no credentials, no git; Claude can write files as in any Cowork session | Nothing leaves the computer |
| Extension without plugin | Claude uses the tools without the specialist; without the hook a launcher could land on disk | Every save barrier: it never reaches the repository; review on the git server |
| Hook down or removed | A dangerous file can land on the user's disk | The save refuses it; operating-system controls (Windows Script Host off, AppLocker) |

## Next checks

| # | Must hold | Why |
|---|---|---|
| M6 | A **PowerShell** guard hook (`shell: "powershell"`, `onFailure: "block"`, no runtime needed) denies executables and IT's files, and blocks when it cannot run, under execution policy and Constrained Language Mode; its cost per write is acceptable | A guard that fails closed without uv; watch [claude-code#100891](https://github.com/anthropics/claude-code/issues/100891) (`onFailure: "block"` not blocking in one PowerShell case) |
| M7 | The whole connector works inside the extension: browser sign-in with loopback, DPAPI tokens, git on the workspace folder, its data under MSIX | Only the spike ran so far |
| M8 | The same in a Cowork session in the cloud | H16 for this variant |
| M9 | The connector records each guard consultation, and a pull request says so when files changed with no consultation since the last save ("the guard was not active") | IT sees a missing or broken guard, in this variant and in today's |
| M10 | The specialist checks, at the start, that the extension is there and at the expected version, and stops for IT otherwise; IT can deploy the extension with its own software management | Both pieces required in practice: the plugin through the console, the extension through IT |

## Running the spike

```
python research/mcpb-uv/spike/pack.py   # -> spike/dist/eunomai-mcpb-spike.mcpb and eunomai-mcpb-spike-hooks.zip
```

1. Owner: upload `eunomai-mcpb-spike.mcpb` to the organization's desktop-extension allowlist. Install the plugin
   `eunomai-mcpb-spike-hooks.zip` (*Customize → Plugins → Upload plugin*).
2. Rename `%USERPROFILE%\.local\bin\uv.exe` for the test, quit Claude Desktop completely, reopen it, and only then
   install the extension (Desktop picks uv at installation). If an earlier version was installed, uninstall it and
   delete its folder under `Claude-Data\claude_<id>\Claude Extensions\` first.
3. New Cowork task: *"Call spike_runtime and show me the whole answer."*
4. *"Create a file named eunomai-spike-guard.txt with the text hello."* Then *"Call spike_guard_log."*
5. Put uv back, and write the results in the table above.
