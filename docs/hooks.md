---
type: how-to
title: Hooks and rules
description: "The hooks eunomai-business ships, how IT adds the organization's or a project's deny rules by configuration, how they combine with Anthropic's own controls, and their limits."
tags: [hooks, rules, policy, security]
audience: [it, security]
related: [barriers.md, configuration.md, decisions.md, sources.md]
---

# Hooks and rules

A hook is a command Claude runs before or after an action. eunomai-business uses one, the **guard**, and lets IT add
**deny rules** by configuration, without writing code. Rules are written like
[Claude Code's permission rules](https://code.claude.com/docs/en/permissions), so they read the same and would move
to Anthropic's own `permissions.deny` with little change if that ever reaches every Cowork task
([decision 12](decisions.md#12--organization-rules-in-claude-codes-permission-syntax-applied-by-the-guard));
[where they differ](#where-they-differ-from-claude-codes-rules) is below.

## What ships

| Hook | When | What it does | If it cannot run |
|---|---|---|---|
| Guard, `SessionStart` | A task starts | In the cloud, tells Claude the task is refused | Nothing happens |
| Guard, `UserPromptSubmit` | Each message | In the cloud, blocks it with the reason | Nothing happens |
| Guard, `PreToolUse` | Each write, shell command and connector call | Refuses the cloud; then [git in a workspace](#git-from-the-sandbox-shell) and the [file guard](barriers.md#between-claudes-sandbox-and-the-computer); then the organization's rules | The call is blocked (`onFailure: "block"`) |
| A project plugin's hook, `PreToolUse` | Each write and shell command | The project's rules, in its own workspaces only | The call is blocked |

## Git from the sandbox shell

Built in; no configuration changes it. Cowork's sandbox can create files in a workspace but not delete them, so a
git command that touches `.git` leaves a lock or temporary objects behind, and the next save stops. Claude uses the
connector instead (`workspace_status`, the version tools).

| In a workspace, from the shell | Decision |
|---|---|
| `log`, `show`, `blame`, `grep`, `ls-files`, `ls-tree`, `cat-file`, `rev-parse`, `rev-list`, `shortlog`, `merge-base`, `show-ref`, `for-each-ref`, `name-rev`, `reflog` (reading), `version`, `help`, `--exec-path` | Allowed |
| Listing: `branch` with `--show-current`, `-a`, `-r`, `-v` or `--list`, `tag` and `remote` bare or with `-l`, `-v`, `config --get` and `--list` | Allowed |
| `diff` with `--cached`, `--staged`, `--no-index`, a range (`main..HEAD`), or two commits with the last one plainly a commit (`main HEAD`, `HEAD~1 HEAD`) | Allowed |
| Plain `diff`, `diff HEAD`, `diff HEAD a.txt`, `diff main app`, `status`, and every other command | Denied |
| An option that writes a file or runs a program (`--output`, `grep -O`, `--ext-diff`), or any option before the command other than `--no-pager`, `-P`, `-p`, `--no-optional-locks`, `--no-replace-objects` and `--literal-pathspecs`, such as `-c` | Denied |
| Writing or removing anything in `.git`: `rm`, `mv`, `>`, `tee`, `Set-Content`, `find -delete`, a script's `os.remove`, the file tools. A place that cannot be worked out counts as a workspace's when it names `.git` (`$WS/.git/config`) | Denied |

| On a copy | Decision |
|---|---|
| `git -C /tmp/copy ...`, `cd /tmp/copy && git ...`, `env -C /tmp/copy git ...`, `--git-dir`, `GIT_DIR` with a folder outside a workspace | Allowed: any git command |
| `git -C copy ...`, relative, when neither the command nor the folder the hook receives puts it in a workspace, it does not climb with `..`, is not `.`, has no wildcard, and names no workspace | Allowed: any git command. This is a choice: after a `cd` into a workspace in an earlier call, the hook cannot tell |
| `git clone <workspace> /tmp/copy` | Allowed: it reads the workspace and writes the copy |
| `--work-tree` or `GIT_WORK_TREE` alone | Not enough: they move the files, and the repository is still the one found from the folder |
| A copy named like the workspace, outside the folder Cowork mounts or in its `outputs` or `uploads` | Allowed: it is not the workspace |

| Why | |
|---|---|
| `diff` is not read-only | With files that look changed, `git diff` and `git diff HEAD` rewrite the index, and `--no-optional-locks` does not stop it. Every file looks changed when Windows wrote the index and the sandbox reads it ([measured](sources.md#measured-on-real-installations)) |
| A bare `git status` counts as inside | The hook does not see the sandbox shell's folder, which an earlier `cd` may have moved ([limits](#limits)). A command stays out only by showing it runs elsewhere |
| A `cd` holds only as far as it surely ran | To the end of its bracket, not past a pipe or `&`; after `\|\|` or inside a block the folder is unknown afterwards. After `&&` it holds: `mkdir x && cd x` is too common to refuse |
| This rule reads quotes, unlike `Bash` rules | A quoted word is data: `echo "git add"` and a heredoc that mentions git are not refused. What runs is still looked for: the argument of `sh -c`, `eval`, a heredoc or `<<<` or a pipe fed to a shell, `$(...)` inside quotes |
| On the computer's own shell (`Bash`) | The folder the hook receives is real, so outside a workspace nothing is denied |
| Without registered workspaces | Nothing is denied |

## Add a rule

In the build's configuration (`config.local.json` or a variant for eunomai-business, `config.json` for a project
plugin), add an entry to `deny` and build again:

```json
"deny": [
  {
    "rule": "Bash(npm *)",
    "reason": "Node packages are not among the organization's technologies",
    "examples": {"denied": ["npm install left-pad", "cd app && npm ci"], "allowed": ["uv run pytest"]}
  },
  {
    "rule": "Edit(/data/raw/**)",
    "reason": "raw data comes from the nightly import; change the import, not the copy",
    "examples": {"denied": ["data/raw/2026/a.csv"], "allowed": ["data/clean/a.csv"]}
  }
]
```

| Field | Meaning |
|---|---|
| `rule` | `Bash(<command>)`, `Bash` alone (no shell at all) or `Edit(<path>)` |
| `reason` | One line Claude tells the user |
| `examples` | Optional: what the rule must deny and must let through. The build checks them and refuses to package a rule that fails them |

| Form | Matches | Where |
|---|---|---|
| `Bash(npm *)` | `npm`, `npm ci`, `cd app && npm ci`, `echo $(npm ls)`, `for x in a; do npm ci; done`, `timeout 30 npm test`, `sh -c 'npm ci'`; not `npmx`, not `/usr/bin/npm` | eunomai-business: anywhere. A project: commands run in its workspaces |
| `Bash(npm run build)` | That exact command | Same |
| `Edit(/data/raw/**)` | `data/raw/` at the workspace's root and everything under it | In workspaces (the project's own, for a project plugin) |
| `Edit(*.lock)`, `Edit(secrets/**)` | A bare name, or one folder and its content, at any depth | Same |

`Bash` rules also cover Cowork's shell (`mcp__workspace__bash`). A command is looked for wherever one can start
(after an operator, a bracket, a quote or a keyword such as `then` or `do`, inside substitutions), past leading
variable assignments and the wrappers Claude Code strips (`timeout`, `nice`, `nohup`...). Quotes are not trusted,
so they cannot hide a command; the price is that a mention can be denied too (a quoted message or a heredoc that
says `npm install`), and Claude then writes that text with the file tools.

`Edit` rules cover every tool that writes a file and, best effort, what a shell command writes, moves or removes:
the target of `>` and `>>`, the arguments of `rm`, `mv`, `touch`, `mkdir`, `tee` and similar, the last argument of
`cp`, `ln` and `sed -i`. Removing or moving a folder that holds a protected path is denied too. Paths are relative
to the workspace; `//`, `~`, `..`, `\` and `!` are refused, and a trailing `/` means everything in the folder.

## Where they differ from Claude Code's rules

| Point | Claude Code | Here |
|---|---|---|
| Quotes and heredocs | Parsed: a quoted mention is not a command | Not trusted: a mention can be denied (never a hidden command let through) |
| Leading `/` in a path | The folder of the settings file that holds the rule | The workspace's root |
| A relative path | The current directory | The workspace (in Cowork the current directory is the sandbox's, not the workspace) |
| `!` negation, `[...]` classes | Supported | Refused or read literally: write the rule without them |
| Rule kinds | Every tool, `Read`, `WebFetch`, `mcp__…`, parameters | `Bash` and `Edit` only |

## How rules combine

| Fact | Consequence |
|---|---|
| Claude Code runs every plugin's hooks; one deny stops the call (`deny > defer > ask > allow`) | A project plugin can only add restrictions; it can never open what eunomai-business closes |
| The file guard runs before the rules | Context, configuration and executables stay protected whatever the rules say |
| Rules are data packaged in the build (`policy.json`), never fetched | They change with a new build that IT reviews; an invalid file blocks tool calls |

## Anthropic's controls that complement this

| Control | Reaches | Use it for |
|---|---|---|
| Admin console: eunomai-business **Required**, Cowork in the cloud **off**, network egress, connector approval | Every Cowork task | The plugin cannot be turned off; the network is the real boundary |
| Managed settings on the computers (MDM or `managed-settings.json`): `permissions.deny`, sandbox | Claude Code and Cowork tasks on that computer, except with `requireCoworkFullVmSandbox`, where neither the device policy nor the file is inside the VM ([managed settings](https://code.claude.com/docs/en/managed-settings)) | A second layer for the same rules where IT manages the computers |
| Server-managed settings from the console | Claude Code only: Cowork does not read them | Not for Cowork |

Be careful with `allowManagedHooksOnly` on the computers: it stops the hooks of plugins that the managed settings do
not force through `enabledPlugins` ([hooks reference](https://code.claude.com/docs/en/hooks)). A plugin made
Required from the console is not listed there, so the guard would most likely stop running: test it before setting
it.

## Limits

- **Not a security boundary.** Anthropic says it of its own rules: a command rule matches the text Claude writes,
  so `/usr/bin/npm` or `sh -c 'npm ci'` are not stopped. The boundaries are the connector's
  [barriers](barriers.md), IT's review of every version, and the network.
- **Git in a workspace is guidance too.** This rule helps against mistakes; the barrier is the connector, which checks
  what leaves the computer whatever happened in `.git`. It reads the text of a command and stops the usual forms (a
  path to git, wrappers such as `env`, `sudo`, `setsid`, `ionice`, `flock`, `sh -c`, `xargs`, `find -exec`). What text
  matching does not see: git run from a script, through a variable (`$G add .`), a substitution as the program,
  `$'git'`, brace expansion, a shell function, a substitution inside an unquoted heredoc, `env -S`, `taskset`, `doas`,
  `su -c`, `watch`, `script -c`, a `git-add` program, a link to the workspace from elsewhere, `git -C /tmp/copy push`
  into it, or a program git is told to run through its environment (`GIT_EXTERNAL_DIFF`). Writes it does not know as
  writes, such as `dd of=.git/x`, `tar -C .git` or a script's `open()`, are not seen either.
- **Only `Bash` and `Edit`.** Reads, web fetches and other tools are not ruled here; use the console's controls.
- **The shell's folder.** A project's `Bash` rules, and relative paths in `Edit` rules, rely on the folder the hook
  receives being the shell's current one; if Cowork's shell keeps a `cd` from one call to the next, a rule may not
  see it. To validate: H19.
- **No scripts of IT's own, no prompt or agent hooks.** Each script brings its interpreter, paths and shell
  differences between Windows and the cloud; prompt and agent hooks are not deterministic. If a need does not fit a
  rule, it is a change to the guard, reviewed and tested like any other.
- **Cowork on the user's computer only**: a task in the cloud is refused before any rule.
