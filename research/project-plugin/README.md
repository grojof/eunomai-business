# Research: a project plugin next to eunomai-business (H10)

**Status (2026-10-27): P1–P6 pass with a member's own upload.** The organization's upload is still to check. The design it
tests is [decision 10](../../docs/decisions.md#10--a-base-that-holds-for-everyone-projects-bring-their-own-capabilities).

**Question.** Can a project bring its own capabilities as a separate plugin (skills, a local server with its
tools, hooks for its own folders) that relies on eunomai-business in Cowork, without eunomai-business knowing
anything about the project?

**What is documented, and what is not.**
- A plugin declares the plugins it needs in `dependencies`. In Claude Code, "a plugin that an enabled plugin
  depends on starts enabled regardless". An entry is `"name"` or `"name@marketplace"`, and a bare name "resolve[s]
  against this plugin's own marketplace"
  ([manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference#dependencies),
  [dependencies](https://code.claude.com/docs/en/plugins/dependencies)). For plugins loaded from claude.ai, the
  page covers only an entry that names a marketplace. How Cowork resolves a bare name for a plugin uploaded to an
  organization, which has no marketplace, is not documented.
- Hooks from several plugins combine with deny first: "When multiple PreToolUse hooks return different decisions,
  precedence is `deny` > `defer` > `ask` > `allow`" ([hooks reference](https://code.claude.com/docs/en/hooks)).
- On Team, a plugin cannot be limited to a group; "Group access…" is Enterprise only
  ([plugins admin](https://claude.com/docs/plugins/admin#limit-to-user-groups-on-enterprise)).

## Checks

| # | Must hold | How | Status |
|---|---|---|---|
| P1 | The project plugin, declaring eunomai-business in `dependencies`, installs and loads in Cowork next to it | Upload one variant at a time; note any error on *Customize → Plugins* | Pass · 2026-10-27: the bare name (`eunomai-project-spike.zip`) installed and loaded; the other variants were not needed |
| P2 | Without eunomai-business on, the project plugin does not run unguarded. Expected from the documentation: it is disabled, with a message that ends "is disabled — enable it or remove the dependency" | Turn eunomai-business off, open a new task, ask for the spike test, and ask to create `prueba.bat` | Pass · 2026-10-27: "The plugin "eunomai-project-spike" did not load in this session (unmet dependency)"; its hook did not run either (no log entry). `prueba.bat` was written: the base's guard was off too |
| P3 | The project's own local server starts with IT's uv and uv's own Python 3.12 | `project_ping`: `python` 3.12.x and `python_installation` under uv's own Pythons, not a Python installed on the computer | Pass · 2026-10-27: 3.12.15 from `%APPDATA%\uv\python`; the server's environment inside the plugin's folder |
| P4 | A project skill calls eunomai-business's connector | `whoami`, `workspace_list` and `specialist_settings` answer when called from the `project-spike` skill. Tools are shared by the whole session, so this shows availability, not a link between the plugins | Pass · 2026-10-27: all three answered (`whoami` and `specialist_settings` with `unreachable` while the git server was down); `project_context` came back once it was up |
| P5 | Both plugins' hooks run on the same call, and either one's deny blocks it | The project hook denies `eunomai-project-spike-guard.txt`; the base guard still denies `prueba.bat` in a workspace; `project_guard_log` shows the project hook was consulted for both | Pass · 2026-10-27: the project hook denied its file and allowed `prueba.bat`, which eunomai-business's guard denied; the log has both |
| P6 | The specialist and the project's skill coexist: each answers only its own requests | In the same task, "Necesito una aplicación para…" starts the specialist, and only the spike request starts `project-spike` | Pass · 2026-10-27: the request for an application started `eunomai-business:specialist` |

Three variants, the same except for `dependencies`:

| Zip | `dependencies` | Why |
|---|---|---|
| `eunomai-project-spike.zip` | `["eunomai-business"]` | A bare name, which resolves "against this plugin's own marketplace"; a plugin uploaded to Cowork has none, so it may fail |
| `eunomai-project-spike-named.zip` | `["eunomai-business@organization"]` | An entry that names a marketplace, the only form the documentation covers for plugins loaded from claude.ai ("a claude.ai plugin of the same name" meets it) |
| `eunomai-project-spike-nodep.zip` | none | To tell a dependency failure from the rest |

Install one at a time: they share the hook's log and the same skill and server names. Each log entry records
the plugin's folder (`plugin`). What the rules for project plugins in decision 10 require of a real one (hooks
limited to its project's workspaces, no `updatedInput`) is for the template, not for this spike.

**What it means (2026-10-27).**
- A project plugin relies on eunomai-business with a bare name, `dependencies: ["eunomai-business"]`, at least
  when a member uploads it. A real project plugin goes through the organization's upload: P1 and P2 there are
  still to check.
- Turning eunomai-business off turns the project plugin off with it, but then nothing guards the workspace: the
  base plugin must be Required in the organization, so that members cannot turn it off.

## Running it

```
python research/project-plugin/spike/pack.py   # -> spike/dist/: the three variants
```

1. With eunomai-business installed and on: *Customize → Plugins → Upload plugin* (a member's own upload), the
   first variant. If the organization's upload (*Organization settings → Plugins & skills → Add*) is at hand,
   repeat P1 there too: it is the route a real project plugin would take.
2. New Cowork task with a workspace folder (for example `control-vacaciones`): *"Run the project spike test."*
3. *"Create a file named eunomai-project-spike-guard.txt with the text hello."* Then *"Create prueba.bat with the
   text echo hola."* Then *"Call project_guard_log."*
4. *"Necesito una aplicación para llevar las visitas de clientes."* Note which skill starts, then stop.
5. Turn eunomai-business off, open a new task, ask again for the spike test and then to create `prueba.bat`.
   Turn it back on.
6. If the first variant failed P1, uninstall it and repeat from step 1 with the next one.
7. Uninstall the spike plugin and delete the hook's log folder, `eunomai-project-spike`, under
   `%LOCALAPPDATA%` or, for Claude Desktop installed from the Microsoft Store, under
   `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local` ([where](../../docs/data-on-computers.md)).

The spike's server is locked like the connector (`uv.lock`, nothing younger than two weeks). Its tree passes
`dependency_audit` (29 packages, hashed) once exported beside its `pyproject.toml`:
`uv export --frozen --no-dev --no-emit-project -o requirements.txt` in `spike/plugin/server`.
