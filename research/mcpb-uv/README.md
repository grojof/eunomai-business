# Research: the connector as an MCPB extension of type `uv`

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

**Rule.** The current plugin stays the product unless M1–M4 all pass. M2 is not negotiable: without the lockfile's
hashes the supply-chain protection is lost.

## Checks

| # | Must hold | How | Status |
|---|---|---|---|
| M1 | Claude Desktop runs a `uv` extension on a computer without uv or Python installed by the user | `spike_runtime`: `parent` shows a uv inside Claude's own folders, not `%USERPROFILE%\.local\bin` | Pending |
| M2 | It honours the bundled `uv.lock` (and so its hashes) | `spike_runtime`: `probe_six` is `1.16.0` (pinned by the lock) and not the newest `six`, which `pyproject.toml` allows; `argv`/`parent` show `--frozen` | Pending. Local, with the user's uv: honoured |
| M3 | The extension's tools reach Cowork sessions, local and in the cloud | The `spike_*` tools exist in a Cowork task | Pending (early 2026 reports said extension servers were not forwarded to Cowork) |
| M4 | A plugin's `mcp_tool` hook can call the extension's server | The test plugin's hook denies a write of `eunomai-spike-guard.txt`; `spike_guard_log` says which server name worked (`via`) | Pending; the hook's server name for an extension is not documented, so two are tried |
| M5 | Organizations can deploy it to users without each one installing it by hand | Team/Enterprise admin settings for extensions | To read in the admin settings ([local connectors in the desktop app](https://claude.com/docs/connectors/custom/add-unlisted.md#install-a-local-connector-in-the-desktop-app)) |

## Running the spike

```
python research/mcpb-uv/spike/pack.py   # -> spike/dist/eunomai-mcpb-spike.mcpb and eunomai-mcpb-spike-hooks.zip
```

1. Install the extension: double-click `eunomai-mcpb-spike.mcpb`, or *Settings → Extensions → Advanced settings →
   Install Extension…*. Install the plugin `eunomai-mcpb-spike-hooks.zip` (*Customize → Plugins → Upload plugin*).
2. New Cowork task: *"Call spike_runtime and show me the whole answer. What is the full name of that tool?"*
   (the full name tells the server name a hook needs).
3. *"Create a file named eunomai-spike-guard.txt with the text hello."* Then *"Call spike_guard_log."*
4. Repeat 2 with uv out of the way (rename `%USERPROFILE%\.local\bin\uv.exe` for the test, restart Claude Desktop),
   and with Cowork in the cloud if available.
5. Write the results in the table above.
