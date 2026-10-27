# Project plugin template

A **project plugin** brings one project's capabilities to eunomai-business in Cowork: its own tools, the paths it
protects, and a skill that tells Claude how to use them. eunomai-business stays the base: the specialist leads the
work, and sign-in, versions and the file guard are its own. Why this split:
[decision 10](../../docs/decisions.md#10--a-base-that-holds-for-everyone-projects-bring-their-own-capabilities) and
[decision 11](../../docs/decisions.md#11--project-plugins-from-a-template-a-project-declares-its-own-development).

| Part | What it does | Who changes it |
|---|---|---|
| `server/src/eunomai_project/project_tools.py` | The project's tools | The project |
| `config.json` (from `config.example.json`) | Name, repositories, protected paths, settings for the tools | IT, per project |
| `plugin/skills/project/SKILL.md.template` | When and how Claude uses the project's tools | The project |
| Everything else (`project.py`, `guard.py`, `hook.py`, `server.py`, `build.py`) | Finds the project's workspaces, denies protected paths, serves the tools, builds the zip | The template: keep it as it comes, to take its updates |

## Make a project's plugin

1. Copy this folder into the project's repository (for example as `project-plugin/`), outside anything the project
   deploys. Protect it like `AGENTS.md` (code owners or protected file patterns): it is code that runs on every
   user's computer.
2. `copy config.example.json config.json`, fill it in and version it: it holds no secret, and versioning it means its
   rules are reviewed like the rest. `uv` is the same as eunomai-business's build; `repositories` are the
   project's.
3. Write the project's tools in `project_tools.py`, following the rules at the top of that file, with their tests
   in `server/tests/`. Remove `project_example`.
4. Say in the project's `AGENTS.md` which of its tools to use, and for what: the specialist reads it.
5. Test and build:

   ```powershell
   cd server
   uv run --frozen --group dev pytest -q   # the template's tests and the project's
   cd ..
   python build.py                         # -> dist\<name>.zip
   ```

   Several packages from one configuration (a test git server, another set of settings): put in `variants/` a file
   with only what differs, then `python build.py --variant <name>` (into `dist\<name>\`) or `--all`. Every build
   is checked before any is written.
6. Before publishing, IT checks the rules below, and reviews the skill with eunomai-business's `review-skills`.
7. Publish it in *Organization settings → Plugins* next to eunomai-business, which must be **Required**: a member
   who could turn eunomai-business off would also turn off the project plugin, and then nothing guards their
   workspace ([H10](../../research/project-plugin/README.md)).

## Rules a project plugin follows

From decision 10, checked by IT before every publish:

| Rule | How the template keeps it |
|---|---|
| Declares eunomai-business in `dependencies` | `build.py` writes it; without eunomai-business, Cowork does not load the plugin |
| Its hooks act only in its project's workspaces | `project.py` takes them from eunomai-business's register of workspaces, where each one's origin was recorded when it was cloned |
| Its hooks only deny; never `allow`, never a rewritten input | `guard.py` answers deny or nothing |
| Its tools enforce their own limits | Every tool starts from `project.own_workspace`; the rest is the project's code, reviewed by IT |
| No secrets in the plugin | `build.py` refuses obvious ones (a name that says so, credentials in an address, a bearer value); IT's review covers the rest |

## How it works, and why

| Part | How | Why |
|---|---|---|
| The server | Runs on the user's computer, started by IT's uv with its own Python 3.12 | It reaches internal servers without putting them on the internet. A Cowork task in the cloud has no local servers: its hook refuses the task (`CLAUDE_CODE_REMOTE`) |
| Real changes | A tool prepares and checks a change in the workspace; the user saves it as a version; IT reviews it | No credentials to databases or deployments on users' computers |
| The project's workspaces | Those eunomai-business registered as cloned from the project's repositories (its register, out of the sandbox's reach) | Never `.git/config`, which the sandbox can rewrite |
| The hook | The file tools always; the sandbox shell best effort (writing, moving, removing or unpacking into a protected path). A folder is protected as `folder/**` | Rules prevent mistakes; the permissions are the git server's |
| The hook's runtime | `hook.py` with Python's standard library only, set to block if it cannot run | It never waits for installing anything; a damaged plugin stops writes until IT fixes it, never lets them through |

## Settings and dependencies

`settings` in the configuration reach the tools as `config["settings"]`: addresses and names, never a secret. The
server's dependencies are locked like eunomai-business's connector (`uv.lock`, nothing younger than two weeks).
Before adding one, check it with eunomai-business's `dependency_check`; after locking, the exported list must pass
`dependency_audit`. eunomai-business's daily dependency workflow keeps only its own connector current: when it
upgrades `mcp`, upgrade it here too.

```powershell
cd server
uv lock
uv export --frozen --no-dev --no-emit-project -o requirements.txt   # beside pyproject.toml, for the audit; the build leaves it out
```
