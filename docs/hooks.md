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
[Claude Code's permission rules](https://code.claude.com/docs/en/permissions), so they read the same and could
move to Anthropic's own `permissions.deny` if that ever reaches every Cowork task
([decision 12](decisions.md#12--organization-rules-in-claude-codes-permission-syntax-applied-by-the-guard)).

## What ships

| Hook | When | What it does | If it cannot run |
|---|---|---|---|
| Guard, `SessionStart` | A task starts | In the cloud, tells Claude the task is refused | Nothing happens |
| Guard, `UserPromptSubmit` | Each message | In the cloud, blocks it with the reason | Nothing happens |
| Guard, `PreToolUse` | Each write, shell command and connector call | Refuses the cloud; then the [file guard](barriers.md#between-claudes-sandbox-and-the-computer); then the organization's rules | The call is blocked (`onFailure: "block"`) |
| A project plugin's hook, `PreToolUse` | Each write and shell command | The project's rules, in its own workspaces only | The call is blocked |

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
| `Bash(npm *)` | `npm`, `npm ci`, `cd app && npm ci`, `echo $(npm ls)`, `timeout 30 npm test`; not `npmx`, not `/usr/bin/npm` | eunomai-business: anywhere. A project: in its workspaces |
| `Bash(npm run build)` | That exact command | Same |
| `Edit(/data/raw/**)` | `data/raw/` at the workspace's root and everything under it | In workspaces (the project's own, for a project plugin) |
| `Edit(*.lock)`, `Edit(secrets/**)` | A bare name, or one folder and its content, at any depth | Same |

`Bash` rules also cover Cowork's shell (`mcp__workspace__bash`). `Edit` rules cover every tool that writes a file,
and, best effort, the targets of shell commands that write. Paths are relative to the workspace; `//` and `~` are
refused. A command is split at `&&`, `||`, `;`, `|` and `&` outside quotes, and each part is checked past leading
variable assignments and the wrappers Claude Code strips (`timeout`, `nice`, `nohup`...).

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
| Managed settings on the computers (MDM or `managed-settings.json`): `permissions.deny`, sandbox | Claude Code and Cowork tasks on that computer | A second layer for the same rules where IT manages the computers |
| Server-managed settings from the console | Claude Code only: Cowork does not read them | Not for Cowork |

Be careful with `allowManagedHooksOnly` on the computers: it stops the hooks of plugins that the managed settings do
not force through `enabledPlugins` ([hooks reference](https://code.claude.com/docs/en/hooks)). A plugin made
Required from the console is not listed there, so the guard would most likely stop running: test it before setting
it.

## Limits

- **Not a security boundary.** Anthropic says it of its own rules: a command rule matches the text Claude writes,
  so `/usr/bin/npm` or `sh -c 'npm ci'` are not stopped. The boundaries are the connector's
  [barriers](barriers.md), IT's review of every version, and the network.
- **Only `Bash` and `Edit`.** Reads, web fetches and other tools are not ruled here; use the console's controls.
- **No scripts of IT's own, no prompt or agent hooks.** Each script brings its interpreter, paths and shell
  differences between Windows and the cloud; prompt and agent hooks are not deterministic. If a need does not fit a
  rule, it is a change to the guard, reviewed and tested like any other.
- **Cowork on the user's computer only**: a task in the cloud is refused before any rule.
