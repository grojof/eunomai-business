"""The uv that runs the connector: its version against IT's minimum, and against the vulnerabilities known for it.

uv is not one of the project's packages, so the audit of a project never saw it: a computer with an old uv, or one a
security advisory names, ran everything all the same. uv is published on PyPI too, so OSV knows its advisories by the
same name and version. Too old for IT's minimum is said to the person and to IT, and nothing stops; a known
vulnerability blocks the audit, as a vulnerable package does, until IT updates it.
"""

import os
import re
import shutil
import subprocess
from functools import lru_cache

from . import settings
from .support import NeedsIT, Unreachable

_VERSION = re.compile(r"\buv (\d+(?:\.\d+){1,3})\b")


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


@lru_cache(maxsize=1)
def uv_version() -> str | None:
    """The version of the uv that started this connector, which names itself in `UV`; None when it cannot be told."""
    program = os.environ.get("UV") or shutil.which("uv")
    if not program:
        return None
    try:
        said = subprocess.run([program, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = _VERSION.search(said or "")
    return found.group(1) if found else None


@lru_cache(maxsize=4)
def _vulnerabilities(version: str) -> tuple[str, ...]:
    from . import deps  # deps uses this module in its audit

    return tuple(deps._vulnerabilities("pypi", "uv", version))


def vulnerable_uv() -> tuple[str, tuple[str, ...]] | None:
    """(version, advisories) when the uv running the connector has known vulnerabilities. An OSV that cannot be
    reached raises Unreachable, as for any package: the audit says so instead of passing."""
    version = uv_version()
    if version is None:
        return None
    found = _vulnerabilities(version)
    return (version, found) if found else None


def problem() -> dict | None:
    """What a person and IT should know about this computer's uv, as a report for IT, or None when all is well."""
    version = uv_version()
    if version is None:
        return None
    minimum = str(settings.load().get("uv_minimum") or "")
    try:
        advisories = _vulnerabilities(version)
    except Unreachable:
        advisories = ()  # the audit names the closed address when it runs
    if advisories:
        error = NeedsIT(
            f"The uv on this computer ({version}) has a known security problem, so nothing will be shown, tested or "
            "sent until IT updates it. Your work is safe on this computer.",
            f"uv {version} has known vulnerabilities",
            {"uv": version, "Advisories": ", ".join(advisories), "Minimum set by IT": minimum or "none",
             "What IT can do": "Update uv on this computer to a version without them."})
    elif minimum and _key(version) < _key(minimum):
        error = NeedsIT(
            f"The uv on this computer ({version}) is older than the version IT validated ({minimum}). Everything keeps "
            "working; IT should update it.",
            f"uv {version} is older than {minimum}",
            {"uv": version, "Minimum set by IT": minimum, "What IT can do": f"Update uv to {minimum} or later."})
    else:
        return None
    from .support import report

    return report(error)
