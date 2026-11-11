# AGENTS.md — eunomai-business

How to work in this repository, for people and AI assistants alike. What the product is: [README](README.md).

## Where things are

| Path | What |
|---|---|
| `plugin/` | The plugin's skills and hook templates |
| `connector/` | The local MCP server and the guard (`guard.py`, `rules.py`), with its tests |
| `templates/` | The project-plugin template and the test-environment agent |
| `tools/build.py` | Builds the plugin from IT's configuration (standard library only) |
| `docs/` | How it works and why; [decisions](docs/decisions.md), [sources](docs/sources.md), [validation](docs/validation/hypotheses.md) |
| `research/` | Spikes behind decisions; not shipped |
| `openspec/`, `.claude/` | Optional spec-first changes with [OpenSpec](https://github.com/Fission-AI/OpenSpec): its configuration, specs, changes, and its skills and `/opsx:*` commands for Claude Code |

## Directions that do not change without a new decision

| Direction | Where it is decided |
|---|---|
| Only Cowork tasks on the user's computer; a task in the cloud is refused | Decision 1, [barriers](docs/barriers.md) |
| A local connector; git without Git; configuration fixed at build time; no secrets in a build | Decisions 1, 3, 4 |
| Business users never install or run anything; IT provides the runtime (uv) | Decisions 6, 7, 9 |
| The one thing that runs on a person's computer is a preview through the connector, off by default, with two keys; its risk is stated, not hidden | Decision 7, [barriers](docs/barriers.md#the-preview-on-the-persons-computer) |
| Host-agnostic: GitHub or Gitea, any Linux server, any identity proxy | [Architecture](docs/architecture.md#what-is-tied-to-a-git-hosting) |
| A base for every organization; projects bring their capabilities in project plugins from the template | Decisions 10, 11 |
| One recommended stack for business users' applications; React only for IT | Decisions 13, 14, [recommended stack](docs/recommended-stack.md) |
| Rules in Claude Code's permission syntax, applied by the guard; no scripts of IT's own, no prompt or agent hooks, no rule language of our own | Decision 12, [hooks and rules](docs/hooks.md) |
| The guard only denies; tool-call hooks block when they fail, prompt and session hooks continue; matchers are anchored | [Hooks and rules](docs/hooks.md) |

## Before relying on how Claude, Cowork or a plugin behaves

1. Read the official page, not memory or a forum: the [hooks reference](https://code.claude.com/docs/en/hooks),
   [permissions](https://code.claude.com/docs/en/permissions), [plugin manifest](https://code.claude.com/docs/en/plugins-reference),
   [environment variables](https://code.claude.com/docs/en/env-vars),
   [managed settings](https://code.claude.com/docs/en/managed-settings),
   [Cowork architecture](https://support.claude.com/en/articles/14479288),
   [plugin platform support](https://claude.com/docs/plugins/platform-support),
   [MCP tunnels](https://claude.com/docs/connectors/mcp-tunnels/overview).
2. Record the fact in [sources](docs/sources.md) with the link, a short quote and the date checked. A community
   source is labelled as such and never decides alone.
3. If it is about Cowork and only shown for Claude Code, add or update a check in
   [validation](docs/validation/hypotheses.md) and say so in the docs until it passes.

## When Claude Code or Cowork changes (review on every update of the plugin)

| Check | Why |
|---|---|
| Hook fields, events and matcher semantics still as the guard uses them (`onFailure`, anchored matchers, `UserPromptSubmit`, `SessionStart`) | The guard's protection depends on them |
| Permission-rule syntax unchanged; if Anthropic's examples change, update `connector/tests/test_rules.py` first | `rules.py` must read a rule as Claude Code does |
| Whether managed or server-managed settings, permission rules or policy mods now reach Cowork, and whether a plugin may carry settings | A built-in control would replace part of the guard: prefer it and record a decision |
| Whether cloud tasks set `CLAUDE_CODE_REMOTE`, run local MCP servers or reach internal networks (MCP tunnels) | Decision 1 and H16 |
| The `Checked` dates in [sources](docs/sources.md) | A stale fact is treated as unverified |

## Every change

- Branch from `main`; never stack a pull request on a branch that will be deleted.
- Spec-first is optional: whoever wants it starts a non-trivial change with OpenSpec (`/opsx:propose`, or
  `openspec/changes/<name>/` by hand: proposal, specs, tasks) and archives it when merged. The rest of this list holds
  either way.
- Tests: while working, `python tools/test.py --affected` (what the changes against main can break, by the rules in
  the script); before merging, `python tools/test.py` (every suite: the connector's in parallel, the previews four at a
  time, then the tests marked `serial`, which wait on the clock, two at a time), `python tools/build.py` on the example configuration, and the docs check. GitHub's workflow runs
  by hand, now and then.
- An independent review before pushing; its findings are fixed or answered in the pull request.
- Commits carry no AI co-author; a pull request description ends with `Assisted-by: Claude`.
- Docs say how it works and why, in tables where they help; what was found on the way goes to the pull request or
  the [changelog](CHANGELOG.md). English; no names of people.
