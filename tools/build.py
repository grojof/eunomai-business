"""Build the uploadable plugin from the organization's configuration.

    python tools/build.py                      # config.local.json -> dist/eunomai-business/ and .zip
    python tools/build.py --config other.json --out some/folder

The configuration holds the organization's host names and public client IDs (no secrets); config.local.json and
dist/ are git-ignored. Standard library only, so IT needs nothing but Python to build.
"""

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_SRC = ROOT / "plugin"
CONNECTOR_SRC = ROOT / "connector"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "*.egg-info", "build", "tests", ".pytest_cache")
KEYS = {"uvx", "connector_source", "connector_path", "workspaces_root", "diagnostics", "providers"}
PROVIDER_KEYS = {"authorize_url", "token_url", "client_id", "scopes", "redirect_uri", "userinfo_url", "login_field"}
PROVIDER_REQUIRED = {"authorize_url", "token_url", "client_id", "redirect_uri", "userinfo_url"}
LOOPBACK = {"127.0.0.1", "localhost"}


def validate(cfg: dict) -> list[str]:
    """Every problem in the configuration, so IT fixes them in one pass. Keys starting with "_" are comments."""
    errors = [f"unknown setting {key!r}" for key in cfg if not key.startswith("_") and key not in KEYS]
    if cfg.get("connector_source", "bundled") not in ("bundled", "path"):
        errors.append('connector_source must be "bundled" or "path"')
    if cfg.get("connector_source") == "path" and not cfg.get("connector_path"):
        errors.append('connector_source "path" needs connector_path')
    if not isinstance(cfg.get("diagnostics", False), bool):
        errors.append("diagnostics must be true or false")
    providers = cfg.get("providers")
    if not isinstance(providers, dict) or "git" not in providers:
        return errors + ['providers must be an object with at least a "git" provider']
    ports = {}
    for name, provider in providers.items():
        if name.startswith("_"):
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


def _json_text(value) -> str:
    """Value escaped to sit inside a JSON string literal."""
    return json.dumps(str(value))[1:-1]


def build(cfg: dict, out_dir: Path) -> Path:
    out, archive_path = out_dir / "eunomai-business", out_dir / "eunomai-business.zip"
    diagnostics = cfg.get("diagnostics", False)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(PLUGIN_SRC, out, ignore=IGNORE)
    if not diagnostics:  # measurement hooks and validation skills ship only when asked for
        shutil.rmtree(out / "hooks", ignore_errors=True)
        for skill in (out / "skills").glob("validate-*"):
            shutil.rmtree(skill)

    if cfg.get("connector_source", "bundled") == "bundled":
        shutil.copytree(CONNECTOR_SRC, out / "connector", ignore=IGNORE)
        connector = "${CLAUDE_PLUGIN_ROOT}/connector"
    else:
        connector = Path(cfg["connector_path"]).resolve().as_posix()

    values = {
        "UVX": str(cfg.get("uvx") or "uvx").replace("\\", "/"),  # also safe inside the hooks' shell command
        "CONNECTOR": connector,
        "PROVIDERS": json.dumps({k: v for k, v in cfg["providers"].items() if not k.startswith("_")},
                                separators=(",", ":")),
        "WORKSPACES_ROOT": cfg.get("workspaces_root") or "~/eunomai-business-workspaces",
        "DIAGNOSTICS": "1" if diagnostics else "0",
    }
    for template in out.rglob("*.template"):
        text = template.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", _json_text(value))
        json.loads(text)  # fail here, not in Claude, if the result is not valid JSON
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
