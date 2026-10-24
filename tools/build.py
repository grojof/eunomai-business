"""Build the uploadable plugin from the organization's configuration.

    python tools/build.py                      # config.local.json -> dist/eunomai-business/ and .zip
    python tools/build.py --config other.json --out some/folder

The configuration holds the organization's host names and public client IDs (no secrets); config.local.json and
dist/ are git-ignored. Standard library only, so IT needs nothing but Python to build.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_SRC = ROOT / "plugin"
CONNECTOR_SRC = ROOT / "connector"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "*.egg-info", "build", "tests", ".pytest_cache",
                                ".env", "*.env", ".ruff_cache", ".mypy_cache", ".coverage", "htmlcov")
SPECIALIST_KEYS = {"docs_language", "code_language", "free_development", "allowed_technologies", "projects",
                   "dependency_exceptions", "organization_context", "organization_skills"}
KEYS = {"uv", "connector_source", "connector_path", "workspaces_root", "diagnostics", "support_email",
        "providers"} | SPECIALIST_KEYS
PROVIDER_KEYS = {"authorize_url", "token_url", "client_id", "scopes", "redirect_uri", "userinfo_url", "login_field"}
PROVIDER_REQUIRED = {"authorize_url", "token_url", "client_id", "redirect_uri", "userinfo_url"}
LOOPBACK = {"127.0.0.1", "localhost"}
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
EXCEPTION = re.compile(r"^(pypi|npm):[A-Za-z0-9@/._-]+$")


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def validate_specialist(cfg: dict) -> list[str]:
    errors = []
    for key in ("docs_language", "code_language"):
        if cfg.get(key) and not LANGUAGE.match(str(cfg[key])):
            errors.append(f"{key} must be a language code such as en or es")
    if not isinstance(cfg.get("free_development", False), bool):
        errors.append("free_development must be true or false")
    if not _strings(cfg.get("allowed_technologies", [])):
        errors.append("allowed_technologies must be a list of names")
    projects = cfg.get("projects", {})
    if not isinstance(projects, dict):
        errors.append("projects must be an object: repository URL -> {technologies}")
    else:
        for url, project in projects.items():
            if urlsplit(url).scheme != "https":
                errors.append(f"projects: {url!r} must be an https repository URL")
            if not isinstance(project, dict) or not _strings(project.get("technologies", [])):
                errors.append(f"projects.{url}: technologies must be a list of names")
    context = cfg.get("organization_context", "")
    if not isinstance(context, str) or len(context) > 4000:
        errors.append("organization_context must be text of at most 4000 characters")
    skills = cfg.get("organization_skills", [])
    if not isinstance(skills, list) or not all(
            isinstance(s, dict) and set(s) == {"skill", "use_for"} and _strings([s["skill"], s["use_for"]])
            for s in skills):
        errors.append('organization_skills must be a list of {"skill": "<plugin:skill>", "use_for": "<purpose>"}')
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
    errors = [f"unknown setting {key!r}" for key in cfg if not key.startswith("_") and key not in KEYS]
    errors += validate_specialist(cfg)
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


def build(cfg: dict, out_dir: Path) -> Path:
    out, archive_path = out_dir / "eunomai-business", out_dir / "eunomai-business.zip"
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
        "WORKSPACES_ROOT": cfg.get("workspaces_root") or "~/eunomai-business-workspaces",
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

    _merge_hooks(out / "hooks", diagnostics)
    archive_path.unlink(missing_ok=True)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(out).as_posix())
    return archive_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.json")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    if not args.config.exists():
        print(f"missing {args.config}: copy config.example.json and fill it in", file=sys.stderr)
        return 1
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    errors = validate(cfg)
    if errors:
        print("configuration errors:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    archive = build(cfg, args.out)
    print(f"built {archive} (diagnostics {'on' if cfg.get('diagnostics') else 'off'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
