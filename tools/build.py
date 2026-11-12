"""Build the uploadable plugin from the organization's configuration.

    python tools/build.py                      # config.local.json -> dist/<plugin_name>/ and .zip
    python tools/build.py --variant tests      # config.local.json + variants/tests.json -> dist/tests/
    python tools/build.py --all                # the configuration and every variant
    python tools/build.py --config other.json --out some/folder

The configuration holds the organization's host names and public client IDs (no secrets); a variant holds only what
differs from it. config.local.json, variants/ and dist/ are git-ignored. Standard library only, so IT needs nothing
but Python to build.
"""

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.compile(r"\d+\.\d+\.\d+")


def eunomai_version() -> str:
    """eunomai-business's version, from the connector's pyproject.toml: the one place it is written."""
    found = re.search(r'^version = "([^"]+)"', (ROOT / "connector" / "pyproject.toml").read_text(encoding="utf-8"),
                      re.MULTILINE)
    if not found:
        raise SystemExit("connector/pyproject.toml has no version")
    return found[1]
PLUGIN_SRC = ROOT / "plugin"
CONNECTOR_SRC = ROOT / "connector"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "*.egg-info", "build", "tests", ".pytest_cache",
                                ".env", "*.env", ".ruff_cache", ".mypy_cache", ".coverage", "htmlcov")
SPECIALIST_KEYS = {"docs_language", "code_language", "free_development", "allowed_technologies",
                   "dependency_exceptions", "organization_context", "organization_skills", "app_preview", "app_tests",
                   "message_style", "uv_minimum"}
KEYS = {"uv", "connector_source", "connector_path", "workspaces_root", "diagnostics", "support_email",
        "providers", "deny", "plugin_name", "plugin_description", "plugin_version", "platform"} | SPECIALIST_KEYS
VARIANT = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
PLUGIN_NAME = VARIANT  # as connector/src/eunomai_business/__init__.py reads it
DEFAULT_PLUGIN = "eunomai-business"
DEFAULT_DESCRIPTION = ("Versions, save points and pull requests for business users in Claude Cowork, with sign-in "
                       "through the organization and barriers enforced by a local connector.")
PLATFORMS = ("gitea",)  # the hosting platforms the connector has code for: connector/src/eunomai_business/hosting.py
NOT_YET = {  # as hosting.NOT_YET says it; a test keeps the two in step
    "github": "it needs a GitHub class for its REST API — pull requests, their reviews and review comments, and the "
              "repository's default branch — tested against a real GitHub",
    "gitlab": "it needs a GitLab class for its REST API v4 — merge requests, their approvals, notes and discussions, "
              "and the project's default branch — tested against a real GitLab",
}
MOVED = {"projects": "projects is no longer a setting: each project declares it in .eunomai/project.toml on its main "
                     "branch (docs/project-practices.md)"}
PROVIDER_KEYS = {"authorize_url", "token_url", "client_id", "scopes", "redirect_uri", "userinfo_url", "login_field"}
PROVIDER_REQUIRED = {"authorize_url", "token_url", "client_id", "redirect_uri", "userinfo_url"}
LOOPBACK = {"127.0.0.1", "localhost"}
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
STYLE_ACCENT = re.compile(r"#[0-9a-fA-F]{6}\Z")  # as connector/src/eunomai_business/message_page.py reads them
STYLE_FONT = re.compile(r"[A-Za-z0-9 ,'\"-]{1,100}\Z")
EXCEPTION = re.compile(r"^(pypi|npm):[A-Za-z0-9@/._-]+$")


def _rules():
    """The connector's deny-rule module, loaded from its file: the build keeps to the standard library."""
    source = CONNECTOR_SRC / "src" / "eunomai_business" / "rules.py"
    spec = importlib.util.spec_from_file_location("eunomai_rules", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def validate_specialist(cfg: dict) -> list[str]:
    errors = []
    for key in ("docs_language", "code_language"):
        if cfg.get(key) and not LANGUAGE.match(str(cfg[key])):
            errors.append(f"{key} must be a language code such as en or es")
    for key in ("free_development", "app_preview", "app_tests"):
        if not isinstance(cfg.get(key, False), bool):
            errors.append(f"{key} must be true or false")
    if not _strings(cfg.get("allowed_technologies", [])):
        errors.append("allowed_technologies must be a list of names")
    context = cfg.get("organization_context", "")
    if not isinstance(context, str) or len(context) > 4000:
        errors.append("organization_context must be text of at most 4000 characters")
    skills = cfg.get("organization_skills", [])
    if not isinstance(skills, list) or not all(
            isinstance(s, dict) and set(s) == {"skill", "use_for"} and _strings([s["skill"], s["use_for"]])
            for s in skills):
        errors.append('organization_skills must be a list of {"skill": "<name or plugin:skill>", "use_for": "<purpose>"}')
    style = cfg.get("message_style", {})
    accent, font = (style.get("accent", "#000000"), style.get("font", "x")) if isinstance(style, dict) else ("", "")
    if not isinstance(style, dict) or set(style) - {"accent", "font"} \
            or not (isinstance(accent, str) and STYLE_ACCENT.match(accent)) \
            or not (isinstance(font, str) and STYLE_FONT.match(font)):
        errors.append('message_style takes "accent" (a colour such as #1f4e79) and "font" (font names separated by '
                      'commas), both optional')
    own = cfg.get("plugin_version", "")
    if not isinstance(own, str) or (own and not VERSION.fullmatch(own)):
        errors.append('plugin_version must be a version such as "0.1.3", or empty for eunomai-business\'s')
    minimum = cfg.get("uv_minimum", "")
    if not isinstance(minimum, str) or (minimum and not re.fullmatch(r"\d+\.\d+\.\d+", minimum)):
        errors.append('uv_minimum must be a version such as "0.13.5", or empty')
    exceptions = cfg.get("dependency_exceptions", [])
    if not isinstance(exceptions, list):
        errors.append("dependency_exceptions must be a list")
    else:
        for item in exceptions:
            if not isinstance(item, dict) or not EXCEPTION.match(str(item.get("package", ""))) \
                    or not str(item.get("reason", "")).strip():
                errors.append('dependency_exceptions: each needs "package" ("pypi:<name>" or "npm:<name>") '
                              'and a "reason"')
    return errors


def validate(cfg: dict) -> list[str]:
    """Every problem in the configuration, so IT fixes them in one pass. Keys starting with "_" are comments."""
    errors = [MOVED.get(key, f"unknown setting {key!r}") for key in cfg if not key.startswith("_") and key not in KEYS]
    errors += validate_specialist(cfg)
    if not PLUGIN_NAME.match(str(cfg.get("plugin_name", DEFAULT_PLUGIN))):
        errors.append("plugin_name: 1 to 40 lowercase ASCII letters, digits and hyphens, starting with a letter or digit")
    platform = cfg.get("platform", PLATFORMS[0])
    if platform in NOT_YET:
        errors.append(f"platform: {platform} is not supported yet: {NOT_YET[platform]}")
    elif platform not in PLATFORMS:
        errors.append(f"platform is one of {', '.join([*PLATFORMS, *NOT_YET])}; only {', '.join(PLATFORMS)} works")
    description = cfg.get("plugin_description", DEFAULT_DESCRIPTION)
    if not isinstance(description, str) or not description.strip() or len(description) > 300:
        errors.append("plugin_description must be text of at most 300 characters")
    errors += _rules().problems(cfg.get("deny", []))  # each rule parses, has a reason, and meets its examples
    if cfg.get("connector_source", "bundled") not in ("bundled", "path"):
        errors.append('connector_source must be "bundled" or "path"')
    if cfg.get("connector_source") == "path" and not cfg.get("connector_path"):
        errors.append('connector_source "path" needs connector_path')
    if not isinstance(cfg.get("diagnostics", False), bool):
        errors.append("diagnostics must be true or false")
    if cfg.get("support_email") and not EMAIL.match(str(cfg["support_email"])):
        errors.append("support_email must be one e-mail address")
    providers = cfg.get("providers")
    if not isinstance(providers, dict) or "git" not in providers:
        return errors + ['providers must be an object with at least a "git" provider']
    ports = {}
    for name, provider in providers.items():
        if name.startswith("_"):
            continue
        if not isinstance(provider, dict):
            errors.append(f"providers.{name} must be an object")
            continue
        errors += [f"providers.{name}: unknown field {key!r}" for key in provider if not key.startswith("_")
                   and key not in PROVIDER_KEYS]
        errors += [f"providers.{name}: missing {key}" for key in sorted(PROVIDER_REQUIRED - provider.keys())]
        for key in ("authorize_url", "token_url", "userinfo_url"):
            url = urlsplit(provider.get(key) or "")
            if provider.get(key) and url.scheme != "https" and not (url.scheme == "http" and url.hostname in LOOPBACK):
                errors.append(f"providers.{name}.{key} must be https")
        redirect = urlsplit(provider.get("redirect_uri") or "")
        if provider.get("redirect_uri"):
            if redirect.scheme != "http" or redirect.hostname not in LOOPBACK or not redirect.port:
                errors.append(f"providers.{name}.redirect_uri must be http://127.0.0.1:<port>/... or "
                              "http://localhost:<port>/...")
            elif redirect.port in ports:
                errors.append(f"providers.{name}.redirect_uri uses the same port as providers.{ports[redirect.port]}")
            else:
                ports[redirect.port] = name
    return errors


def _build_id() -> str:
    """The source commit (with "+changes" when built from uncommitted files), so IT reports name their build."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return commit + ("+changes" if dirty else "")


def _json_text(value) -> str:
    """Value escaped to sit inside a JSON string literal."""
    return json.dumps(str(value))[1:-1]


def _merge_hooks(folder: Path, diagnostics: bool) -> None:
    """The file guard always; the measurement hooks only with diagnostics."""
    extra = folder / "diagnostics.json"
    if diagnostics:
        hooks = json.loads((folder / "hooks.json").read_text(encoding="utf-8"))
        for event, entries in json.loads(extra.read_text(encoding="utf-8"))["hooks"].items():
            hooks["hooks"].setdefault(event, []).extend(entries)
        (folder / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8", newline="\n")
    extra.unlink()


def plugin_of(cfg: dict) -> str:
    return str(cfg.get("plugin_name") or DEFAULT_PLUGIN)


def build(cfg: dict, out_dir: Path) -> Path:
    """The plugin as the organization named it: <name>/ and <name>.zip in out_dir."""
    plugin = plugin_of(cfg)
    out, archive_path = out_dir / plugin, out_dir / f"{plugin}.zip"
    diagnostics = cfg.get("diagnostics", False)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(PLUGIN_SRC, out, ignore=IGNORE)
    if not diagnostics:  # validation skills ship only when asked for
        for skill in (out / "skills").glob("validate-*"):
            shutil.rmtree(skill)

    if cfg.get("connector_source", "bundled") == "bundled":
        shutil.copytree(CONNECTOR_SRC, out / "connector", ignore=IGNORE)
        connector = "${CLAUDE_PLUGIN_ROOT}/connector"
    else:
        connector = Path(cfg["connector_path"]).resolve().as_posix()

    uv = str(cfg.get("uv") or "uv").replace("\\", "/")
    values = {
        "UV": uv,
        # Hooks run through whatever shell Claude Desktop picks (Git Bash, cmd, PowerShell). A bare command works in
        # all of them; a quoted one breaks PowerShell, so quotes are only for a path with spaces.
        "UV_COMMAND": f'"{uv}"' if " " in uv else uv,
        "CONNECTOR": connector,
        "PROVIDERS": json.dumps({k: v for k, v in cfg["providers"].items() if not k.startswith("_")},
                                separators=(",", ":")),
        "WORKSPACES_ROOT": cfg.get("workspaces_root") or f"~/{plugin}-workspaces",
        "PLUGIN": plugin,
        "PLATFORM": cfg.get("platform") or PLATFORMS[0],
        "PLUGIN_DESCRIPTION": cfg.get("plugin_description") or DEFAULT_DESCRIPTION,
        # Claude keeps an installed plugin by its version: each release, and each change of IT's settings, needs its own
        "PLUGIN_VERSION": cfg.get("plugin_version") or eunomai_version(),
        "DIAGNOSTICS": "1" if diagnostics else "0",
        "BUILD": _build_id(),
        "SPECIALIST": json.dumps({k: cfg[k] for k in sorted(SPECIALIST_KEYS) if k in cfg}, separators=(",", ":"),
                                 ensure_ascii=False),
        "SUPPORT_EMAIL": cfg.get("support_email") or "",
    }
    for template in out.rglob("*.template"):
        text = template.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", _json_text(value))
        json.loads(text)  # fail here, not in Claude, if the result is not valid JSON
        template.with_suffix("").write_text(text, encoding="utf-8", newline="\n")  # LF on every OS
        template.unlink()
    # The skills name the plugin's own tools and skills, and IT's address for when the connector cannot start (they
    # cannot ask it then), by placeholders; nothing else of theirs is replaced
    support = cfg.get("support_email") or "IT"
    for skill in (out / "skills").rglob("*.md"):
        markdown = skill.read_text(encoding="utf-8")
        if "{{PLUGIN}}" in markdown or "{{SUPPORT_EMAIL}}" in markdown:
            markdown = markdown.replace("{{PLUGIN}}", plugin).replace("{{SUPPORT_EMAIL}}", support)
            skill.write_text(markdown, encoding="utf-8", newline="\n")

    policy = json.dumps({"deny": cfg.get("deny", [])}, indent=2, ensure_ascii=False) + "\n"
    (out / "policy.json").write_text(policy, encoding="utf-8", newline="\n")  # the guard's deny rules
    _merge_hooks(out / "hooks", diagnostics)
    archive_path.unlink(missing_ok=True)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(out).as_posix())
    return archive_path


def overlay(base: dict, changes: dict) -> dict:
    """A variant's configuration: the base with the variant's settings on top. Objects (providers, a provider)
    merge key by key; anything else is replaced."""
    merged = dict(base)
    for key, value in changes.items():
        both = isinstance(value, dict) and isinstance(base.get(key), dict)
        merged[key] = overlay(base[key], value) if both else value
    return merged


def _read(path: Path) -> dict | str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"cannot read {path}: {exc}"
    return value if isinstance(value, dict) else f"{path} must be a JSON object"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.json")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--variant", action="append", default=[],
                        help="build variants/<name>.json on top of the configuration, into <out>/<name>/")
    parser.add_argument("--all", action="store_true", help="build the configuration and every variant")
    parser.add_argument("--variants", type=Path, default=ROOT / "variants", help="the variants' folder")
    args = parser.parse_args(argv)
    if not args.config.exists():
        print(f"missing {args.config}: copy config.example.json and fill it in", file=sys.stderr)
        return 1
    base = _read(args.config)
    if isinstance(base, str):
        print(base, file=sys.stderr)
        return 1
    if args.all and args.variant:
        print("use --all or --variant, not both", file=sys.stderr)
        return 1
    names = sorted(p.stem for p in args.variants.glob("*.json")) if args.all else args.variant
    builds = ([("", base, args.out)] if args.all or not names else [])
    for name in names:
        if not VARIANT.match(name) or name == plugin_of(base):  # that folder is the base build's
            print(f"variant {name!r}: lowercase letters, digits and hyphens only, and not {plugin_of(base)}",
                  file=sys.stderr)
            return 1
        changes = _read(args.variants / f"{name}.json")
        if isinstance(changes, str):
            print(changes, file=sys.stderr)
            return 1
        builds.append((name, overlay(base, changes), args.out / name))
    failed = 0
    for name, cfg, out in builds:  # every problem of every build at once, and only valid builds are written
        errors = validate(cfg)
        if errors:
            failed += 1
            print(f"configuration errors{f' in variant {name}' if name else ''}:\n  " + "\n  ".join(errors),
                  file=sys.stderr)
    if failed:
        return 1
    for name, cfg, out in builds:
        archive = build(cfg, out)
        print(f"built {archive} (diagnostics {'on' if cfg.get('diagnostics') else 'off'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
