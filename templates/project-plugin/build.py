"""Build a project plugin from its configuration.

    python build.py                          # config.json -> dist/<name>/ and dist/<name>.zip
    python build.py --config other.json --out some/folder

Standard library only, so IT needs nothing but Python to build. config.json holds no secret (the build refuses obvious
ones) and is versioned with the project, so its rules are reviewed like the rest; dist/ is git-ignored.
"""

import argparse
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
KEYS = {"name", "display_name", "description", "version", "uv", "repositories", "deny", "settings"}
NAME = re.compile(r"^[a-z][a-z0-9-]{1,48}[a-z0-9]$")
DISPLAY_NAME = re.compile(r"^[\w .()-]{1,60}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
# A setting the tools read must never be a secret: a secret on a user's computer is everyone's. These catch the
# obvious ones (a name that says so, credentials in an address, a bearer value); IT's review covers the rest.
SECRET_KEY = re.compile(r"pass|pwd|secret|token|key|credential|cookie|auth|bearer|dsn|session", re.IGNORECASE)
SECRET_VALUE = re.compile(r"://[^/\s]*@|^\s*(bearer|basic)\s", re.IGNORECASE)
# The uv path goes into a hook command that a shell runs: a plain path only.
UV_PATH = re.compile(r"^[^\"'&|;<>^%$`!\r\n]+$")


def _text(value, limit: int) -> bool:
    return isinstance(value, str) and value.strip() != "" and len(value) <= limit and "\n" not in value


def _relative_glob(value) -> bool:
    """A path relative to the workspace, with / only: the guard compares it to paths written that way."""
    if not _text(value, 200) or "\\" in value or re.match(r"^(/|[A-Za-z]:|\./)", value):
        return False
    return ".." not in value.split("/")


def validate(cfg: dict) -> list[str]:
    """Every problem in the configuration, so IT fixes them in one pass. Keys starting with "_" are comments."""
    errors = [f"unknown setting {key!r}" for key in cfg if not key.startswith("_") and key not in KEYS]
    if not NAME.match(str(cfg.get("name", ""))) or cfg.get("name") == "eunomai-business":
        errors.append("name must be lowercase letters, digits and hyphens (3 to 50), and not eunomai-business")
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
    deny = cfg.get("deny", [])
    if not isinstance(deny, list):
        errors.append("deny must be a list of {paths, reason}")
    else:
        for index, rule in enumerate(deny):
            if not isinstance(rule, dict) or set(rule) != {"paths", "reason"}:
                errors.append(f"deny[{index}] must have exactly paths and reason")
                continue
            if not isinstance(rule["paths"], list) or not rule["paths"] \
                    or not all(_relative_glob(path) for path in rule["paths"]):
                errors.append(f"deny[{index}].paths must be paths relative to the workspace, with / and without "
                              "./ or ..")
            if not _text(rule["reason"], 300):
                errors.append(f"deny[{index}].reason must be one line of at most 300 characters")
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
                "dependencies": ["eunomai-business"]}
    (out / ".claude-plugin").mkdir(exist_ok=True)
    (out / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
                                                        newline="\n")
    project = {key: cfg[key] for key in ("name", "display_name", "repositories", "deny", "settings") if key in cfg}
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--out", type=Path, default=HERE / "dist")
    args = parser.parse_args(argv)
    try:
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.config}: {exc}", file=sys.stderr)
        return 1
    errors = validate(cfg) if isinstance(cfg, dict) else ["the configuration must be a JSON object"]
    if errors:
        print("configuration errors:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print(f"built {build(cfg, args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
