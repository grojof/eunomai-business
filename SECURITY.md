# Security policy

eunomai-business is a Claude plugin: skills, hooks and a local connector (an MCP server) that runs on the person's computer, signs in to the organization's git server and directory, and may run a project's preview and tests there when IT turns that on. Its guard denies what an organization forbids; it is a control in depth, not the only one. See [barriers](docs/barriers.md) and [data on computers](docs/data-on-computers.md).

## Supported versions

Pre-1.0: only the newest release, and `main`, receive security fixes. Reproduce on the current `main` before
reporting.

## Reporting a vulnerability

**Do not open a public issue for a security problem.** Use GitHub's private vulnerability reporting: the
repository's *Security* tab, *Report a vulnerability*. Include the affected part, the version or commit, a minimal
reproduction and the impact you saw. A report is acknowledged within a few working days and kept up to date until
it is fixed and disclosed.

## Scope

In scope: the connector (`connector/`), the guard and hooks, the skills, the build and IT tools (`tools/`), and the project-plugin and test-environment templates. Out of scope: Claude, Claude Desktop and Cowork, uv, and the git servers and identity providers the connector talks to: report those to their own projects.
