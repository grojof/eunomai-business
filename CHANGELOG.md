# Changelog

## Unreleased

- **`workspace_update`:** brings the project's latest changes on its own: saves unsaved work first, backs up
  before moving anything, returns to the main branch when the user's proposal was accepted (also after a squash
  merge), and adds new main-branch changes to an open version only when no file was changed on both sides.
- **Stops go to IT, not to the user:** when the connector is not certain, or an unexpected error happens, the user
  gets one plain sentence and IT a report, with an e-mail link when `support_email` is set.
- **New setting `support_email`.**
- **Dependencies follow the project's own rules:** the whole tree locked with nothing younger than two weeks
  unless it fixes a vulnerability (certifi 2026.10.19), truststore back to 0.10.4.
- **Launch with `uv run --frozen`:** users' computers install exactly the locked tree, each package checked
  against its hash; downloads use the operating system's certificate store; uv's configuration files on the
  computer are ignored; Python 3.12. The setting `uvx` becomes `uv`.
- **The specialist (first version):** the `specialist` skill guides a business user from a vague idea to a pull
  request (understand, shape, specify, build, deliver), writing OpenSpec files without its command-line tool.
- **Settings for the specialist:** `docs_language`, `code_language`, `free_development` (off by default),
  `allowed_technologies`, `projects`, `dependency_exceptions`; tool `specialist_settings`.
- **`dependency_check`:** which package version may be used, decided by rules (vulnerabilities, yanked,
  deprecated, origin, activity, age), deny by default.
- **Software bill of materials:** `connector/sbom.cdx.json` (CycloneDX 1.5) with versions, hashes, licenses and
  dependencies of every runtime package, shipped inside the plugin; `tools/sbom.py` regenerates it.
- **Daily dependency maintenance:** a workflow applies the project's rules, proposes updates as one pull request
  and opens an issue for vulnerabilities without an allowed fix; tests run on every pull request (Linux, Windows).
- **Compliance page** for audits: data protection, information-security controls, supply chain and licenses,
  and what remains the organization's responsibility.
- **Guard probe (diagnostics):** the diagnostic hook denies two test markers, as a JSON answer and as exit code 2,
  and logs input field names and timings, to validate the planned file guard (H9).

## 0.1.0 · 2026-10-24

First development version.

- **Plugin and local connector** for Claude Cowork, built per organization with `tools/build.py`.
- **Sign-in** with OAuth 2.0 public clients (git server, Entra ID); tokens encrypted per user.
- **Workspaces, versions, save points and pull requests** without Git installed (`workspace_*`, `version_*`).
- **Barriers** enforced in code: main branch protected, token only to the git server, HTTPS only, git hooks and
  unexpected `.git/config` entries disabled, the computer's git configuration ignored.
- **Diagnostics** (`diag_*`, validation skills, hook log) only in builds that enable them.
- **Tests** against a fake git server; **docs** for IT, security and repository owners; design decisions.
