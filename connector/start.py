"""Starts one of the connector's programs with its Python environment outside the plugin's folder.

    uv run --no-project --no-config --managed-python --python 3.12 <connector>/start.py <plugin> <program> [arguments]

Windows does not let a folder go while a program runs from it. With the environment inside the plugin's folder, the
connector, running as long as Claude Desktop is open, kept that folder: uninstalling the plugin did nothing and said
nothing, and an update could not replace it. The environment lives in `%LOCALAPPDATA%\\<plugin>\\environments\\`, one
for each connector folder and set of locked packages, so a new version gets its own while the old one may still run;
the plugin's folder holds only files nobody keeps open. This file runs on uv's own Python, outside the plugin's
folder too, with the standard library alone, and waits for the program: its input and output are the program's.

An environment nobody has started for a week is removed once nothing runs from it: it is first renamed, which Windows
refuses while any of its files is in use.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAMS = ("eunomai-business", "eunomai-business-hook", "eunomai-business-guard", "python")
"""What the plugin starts; `python` lets the tests start the connector with a shorter time limit."""
OVERRIDE = "EUNOMAI_CONNECTOR_ENVIRONMENT"
"""Another folder for the environment: tests share one across the folders they give each person."""
PLUGIN_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")  # as eunomai_business.PLUGIN_NAME
UNUSED_FOR = 7 * 24 * 3600
USED = ".used"
UV_ARGUMENTS = ["run", "--frozen", "--no-dev", "--no-config", "--system-certs", "--managed-python", "--python", "3.12"]


def environments(plugin: str) -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    return Path(base) / plugin / "environments"


def environment(plugin: str, connector: Path = HERE) -> Path:
    """One for each connector folder and each set of locked packages: a copy in another folder, or another version,
    never shares one with a connector that may still be running."""
    digest = hashlib.sha256(str(connector).encode("utf-8"))
    for name in ("pyproject.toml", "uv.lock"):
        digest.update(b"\0" + (connector / name).read_bytes())
    return environments(plugin) / digest.hexdigest()[:16]


def marker(folder: Path) -> Path:
    """When an environment was last started: beside it, since uv makes the environment's folder itself."""
    return folder.with_name(folder.name + USED)


def mark_used(folder: Path) -> None:
    folder.parent.mkdir(parents=True, exist_ok=True)
    marker(folder).touch()


def remove_unused(plugin: str, keep: Path, now: float | None = None) -> list[str]:
    """The environments nobody started for a week, and that nothing runs from, removed. Returns their names."""
    now = time.time() if now is None else now
    removed = []
    root = environments(plugin)
    if not root.is_dir():
        return removed
    for folder in root.iterdir():
        gone = not folder.with_name(folder.name.removesuffix(USED)).exists()
        if folder.name.endswith(USED) and folder != marker(keep) and gone:
            folder.unlink(missing_ok=True)  # its environment went
            continue
        if not folder.is_dir() or folder == keep:
            continue
        if folder.name.endswith(".removing"):  # a removal that stopped half way
            shutil.rmtree(folder, ignore_errors=True)
            continue
        used = marker(folder)
        last = used.stat().st_mtime if used.exists() else folder.stat().st_mtime
        if now - last < UNUSED_FOR:
            continue
        aside = folder.with_name(folder.name + ".removing")
        try:
            folder.rename(aside)  # refused on Windows while a program runs from it
        except OSError:
            continue
        shutil.rmtree(aside, ignore_errors=True)
        used.unlink(missing_ok=True)
        removed.append(folder.name)
    return removed


def uv() -> str:
    """uv names itself to what it runs; otherwise the one on the PATH."""
    return os.environ.get("UV") or shutil.which("uv") or "uv"


def command(program: str, arguments: list[str]) -> list[str]:
    return [uv(), *UV_ARGUMENTS, "--project", str(HERE), program, *arguments]


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not PLUGIN_NAME.match(argv[0]) or argv[1] not in PROGRAMS:
        print(f"usage: start.py <plugin> <{'|'.join(PROGRAMS)}> [arguments]", file=sys.stderr)
        return 2
    plugin, program, arguments = argv[0], argv[1], argv[2:]
    folder = Path(os.environ[OVERRIDE]) if os.environ.get(OVERRIDE) else environment(plugin)
    mark_used(folder)
    if program == "eunomai-business":  # once a session, not on every hook
        remove_unused(plugin, folder)
    variables = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(folder))
    return subprocess.call(command(program, arguments), env=variables)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
