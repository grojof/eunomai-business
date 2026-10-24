# Research: a Node.js connector

**Question.** Should eunomai-business's connector move from Python (started with `uv run`) to Node.js, running on
the Node that ships with Claude Desktop, so that business users' computers need neither uv nor Python?

**Rule.** The Python connector stays the product until every check below passes. If one of N1–N4 fails, the move
loses most of its point and stops here, with the reason written down. If all pass, the connector is ported on its
own branch, with its tests, and merged as one squashed pull request that replaces `connector/`.

## Checks

| # | Must hold | How | Status |
|---|---|---|---|
| N1 | A plugin's local server with `"command": "node"` starts in Cowork on Claude Desktop's own Node, on a computer without Node installed | Spike plugin, `spike_runtime`: `electron` is set and `exec_path` is inside the Claude package | Cowork 2026-10-25, Node on PATH: the plugin ran on the installed Node (nvm4w, v22.21.0), not on Desktop's. Pending without Node on PATH (`nvm off`, restart Desktop). Claude Desktop 3.6556.2.0 (MSIX) ships no `node.exe`; its Node would be Electron's |
| N2 | It reaches internal HTTPS hosts trusting the organization's CA (Windows certificate store) | `spike_reach` on the git server | Cowork 2026-10-25, installed Node 22.21: system store 200 in 27 ms (284 certificates), bundled store `SELF_SIGNED_CERT_IN_CHAIN`. Pending on Desktop's Node |
| N3 | Sign-in records encrypted per user with DPAPI, without native modules | `spike_protect` (PowerShell `ProtectedData`) | Cowork 2026-10-25: round trip works, 450–500 ms per call (PowerShell start-up), FullLanguage mode; tokens would be kept in memory. Pending under policies (Constrained Language Mode would block it) |
| N4 | The file guard without Python: a PreToolUse hook of type `mcp_tool` calls the plugin's own server and its answer denies the tool | Spike hook on `Write`, `Edit` and the shell; ask Claude to write `eunomai-spike-guard.txt` | **Pass** · Cowork 2026-10-25: the `mcp_tool` hook called the plugin's own server and its deny stopped a `Write`. Behaviour when the server is down still to note (the docs say an error is non-blocking, so it fails open) |
| N5 | Git with isomorphic-git: clone, fetch, save, send to Gitea with the OAuth token; files byte for byte (no line-ending or filter changes); runs no hooks | A local test | Partial · 2026-10-25, local: clone over https with the system store in 0.7 s, files byte for byte (CRLF kept), and neither a hook in `.git/hooks` nor a filter in `.git/config` ran (isomorphic-git runs no commands at all). Authenticated push to Gitea pending |
| N6 | Sign-in with PKCE and a loopback redirect from Node, opening the browser | Port of `auth` | Low risk (standard Node `http`) |
| N7 | The plugin with its packages stays small and passes the dependency rules | `dependency_audit` on its `package-lock.json` | **Fails as the rules stand** · `isomorphic-git` 1.43.3 and `@modelcontextprotocol/sdk` 1.32.1 are allowed (MIT), but isomorphic-git's tree has 55 packages and 24 have had no release in three years (`inherits`, `once`, `wrappy`, browser polyfills such as `buffer` and `events`): blocked as unmaintained. It would need 24 IT exceptions, vendoring, or a different rule for finished micro-packages. The Python tree passes with none |

N4 is worth having whatever the answer to N1: an `mcp_tool` hook would also let the Python connector serve the
guard, without starting uv on every tool call.

## Running the spike

```
python research/node-connector/spike/pack.py      # -> research/node-connector/spike/dist/eunomai-node-spike.zip
```

1. Install the zip in Claude Desktop (*Customize → Plugins → Upload plugin*), next to eunomai-business.
2. New Cowork task: *"Call spike_runtime, then spike_reach with https://<git server>/api/v1/version, then
   spike_protect."* Copy the answers.
3. Ask: *"Create a file named eunomai-spike-guard.txt with the text hello."* The guard should deny it. Then
   *"Call spike_guard_log."*
4. Repeat 2–3 on a computer without Node installed, and with "Run Cowork in the cloud" on if available.
5. Write the results in the table above.
