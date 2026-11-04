"""Build a project plugin from its configuration.

    python build.py                          # config.json -> dist/<name>/ and dist/<name>.zip
    python build.py --variant tests          # config.json + variants/tests.json -> dist/tests/
    python build.py --all                    # the configuration and every variant
    python build.py --config other.json --out some/folder

Standard library only, so IT needs nothing but Python to build. config.json and variants/ hold no secret (the build
refuses obvious ones) and are versioned with the project, so their rules are reviewed like the rest; dist/ is
git-ignored.
"""

import argparse
import importlib.util
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "*.egg-info", "build", "tests", ".pytest_cache",
                                ".env", "*.env", ".ruff_cache", ".mypy_cache", ".coverage", "htmlcov",
                                "requirements*.txt")
KEYS = {"name", "display_name", "description", "version", "uv", "repositories", "deny", "settings", "base_plugin"}
DEFAULT_BASE = "eunomai-business"
NAME = re.compile(r"^[a-z][a-z0-9-]{1,48}[a-z0-9]$")
DISPLAY_NAME = re.compile(r"^[\w .()-]{1,60}$")
VARIANT = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
# A setting the tools read must never be a secret: a secret on a user's computer is everyone's. These catch the
# obvious ones (a name that says so, credentials in an address, a bearer value); IT's review covers the rest.
SECRET_KEY = re.compile(r"pass|pwd|secret|token|key|credential|cookie|auth|bearer|dsn|session", re.IGNORECASE)
SECRET_VALUE = re.compile(r"://[^/\s]*@|^\s*(bearer|basic)\s", re.IGNORECASE)
# The uv path goes into a hook command that a shell runs: a plain path only.
UV_PATH = re.compile(r"^[^\"'&|;<>^%$`!\r\n]+$")


def _text(value, limit: int) -> bool:
    return isinstance(value, str) and value.strip() != "" and len(value) <= limit and "\n" not in value


def _rules():
    """The deny-rule module the hook uses, loaded from its file: the build keeps to the standard library."""
    spec = importlib.util.spec_from_file_location("eunomai_project_rules",
                                                  HERE / "server" / "src" / "eunomai_project" / "rules.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(cfg: dict) -> list[str]:
    """Every problem in the configuration, so IT fixes them in one pass. Keys starting with "_" are comments."""
    errors = [f"unknown setting {key!r}" for key in cfg if not key.startswith("_") and key not in KEYS]
    base = cfg.get("base_plugin", DEFAULT_BASE)
    if not isinstance(base, str) or not VARIANT.match(base):
        errors.append("base_plugin: the name of the organization's eunomai-business plugin, as its build named it "
                      "(lowercase letters, digits and hyphens)")
    if not NAME.match(str(cfg.get("name", ""))) or cfg.get("name") == base:
        errors.append(f"name must be lowercase letters, digits and hyphens (3 to 50), and not {base}")
    if not DISPLAY_NAME.match(str(cfg.get("display_name", ""))):
        errors.append("display_name must be up to 60 letters, digits, spaces, dots, hyphens or brackets")
    if not _text(cfg.get("description"), 300):
        errors.append("description must be one line of at most 300 characters")
    if not VERSION.match(str(cfg.get("version", ""))):
        errors.append("version must be MAJOR.MINOR.PATCH, such as 0.1.0")
    if "uv" in cfg and not (_text(cfg["uv"], 300) and UV_PATH.match(cfg["uv"])):
        errors.append("uv must be a plain path to uv, without quotes or shell characters")
    repositories = cfg.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        errors.append("repositories must list the project's repositories")
    else:
        for url in repositories:
            if not _text(url, 300) or urlsplit(url).scheme != "https" or SECRET_VALUE.search(url):
                errors.append(f"repositories: {url!r} must be an https address without credentials")
    errors += _rules().problems(cfg.get("deny", []))  # each rule parses, has a reason, and meets its examples
    settings = cfg.get("settings", {})
    if not isinstance(settings, dict):
        errors.append("settings must be an object")
    else:
        for key, value in settings.items():
            if SECRET_KEY.search(key) or (isinstance(value, str) and SECRET_VALUE.search(value)):
                errors.append(f"settings.{key} looks like a secret; secrets never go in a plugin")
            elif not isinstance(value, (str, int, float, bool)):
                errors.append(f"settings.{key} must be text, a number or true/false")
    return errors


def _substitute(text: str, values: dict, as_json: bool) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", json.dumps(value)[1:-1] if as_json else value)
    if as_json:
        json.loads(text)  # fail here, not in Claude, if the result is not valid JSON
    return text


def build(cfg: dict, out_dir: Path) -> Path:
    name = cfg["name"]
    out, archive_path = out_dir / name, out_dir / f"{name}.zip"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(HERE / "plugin", out, ignore=IGNORE)
    shutil.copytree(HERE / "server", out / "server", ignore=IGNORE)
    manifest = {"name": name, "version": cfg["version"], "description": cfg["description"],
                "dependencies": [cfg.get("base_plugin", DEFAULT_BASE)]}
    (out / ".claude-plugin").mkdir(exist_ok=True)
    (out / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
                                                        newline="\n")
    project = {key: cfg[key] for key in ("name", "display_name", "repositories", "deny", "settings") if key in cfg}
    project["base_plugin"] = cfg.get("base_plugin", DEFAULT_BASE)  # whose register of workspaces it reads
    (out / "project.json").write_text(json.dumps(project, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                      newline="\n")
    uv = str(cfg.get("uv") or "uv").replace("\\", "/")
    values = {"NAME": name, "DISPLAY_NAME": cfg["display_name"], "UV": uv,
              # hooks run through whatever shell the app picks: quotes only for a path with spaces
              "UV_COMMAND": f'"{uv}"' if " " in uv else uv}
    for template in out.rglob("*.template"):
        text = _substitute(template.read_text(encoding="utf-8"), values, template.name.endswith(".json.template"))
        template.with_suffix("").write_text(text, encoding="utf-8", newline="\n")  # LF on every OS
        template.unlink()
    archive_path.unlink(missing_ok=True)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(out).as_posix())
    return archive_path


def overlay(base: dict, changes: dict) -> dict:
    """A variant's configuration: the base with the variant's settings on top. Objects (settings) merge key by key;
    anything else (repositories, deny) is replaced."""
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
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--out", type=Path, default=HERE / "dist")
    parser.add_argument("--variant", action="append", default=[],
                        help="build variants/<name>.json on top of the configuration, into <out>/<name>/")
    parser.add_argument("--all", action="store_true", help="build the configuration and every variant")
    parser.add_argument("--variants", type=Path, default=HERE / "variants", help="the variants' folder")
    args = parser.parse_args(argv)
    base = _read(args.config)
    if isinstance(base, str):
        print(base, file=sys.stderr)
        return 1
    if args.all and args.variant:
        print("use --all or --variant, not both", file=sys.stderr)
        return 1
    names = sorted(p.stem for p in args.variants.glob("*.json")) if args.all else args.variant
    builds = [("", base, args.out)] if args.all or not names else []
    for name in names:
        if not VARIANT.match(name) or name == base.get("name"):  # that folder is the base package's
            print(f"variant {name!r}: lowercase letters, digits and hyphens only, and not the plugin's name",
                  file=sys.stderr)
            return 1
        changes = _read(args.variants / f"{name}.json")
        if isinstance(changes, str):
            print(changes, file=sys.stderr)
            return 1
        builds.append((name, overlay(base, changes), args.out / name))
    failed = False
    for name, cfg, _ in builds:  # every problem of every build at once, and only valid builds are written
        errors = validate(cfg)
        if errors:
            failed = True
            print(f"configuration errors{f' in variant {name}' if name else ''}:\n- " + "\n- ".join(errors),
                  file=sys.stderr)
    if failed:
        return 1
    for _, cfg, out in builds:
        print(f"built {build(cfg, out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
