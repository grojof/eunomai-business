# Research: the connector as an MCPB extension of type `uv`

**Result (2026-10-26): it works; the decision is pending.** M1–M4 pass on Windows in a local Cowork session:
Claude Desktop ran the extension with its own uv on a computer without uv, honoured the bundled lockfile, Cowork
saw its tools, and a plugin's `mcp_tool` hook reached it. What weighs against it is in
[Trade-offs](#trade-offs).

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
