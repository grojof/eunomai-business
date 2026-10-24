"""Dependency check: which version of a package may be used, decided by rules, not by the model.

Deny by default. A version is usable only if it has no known vulnerability (OSV), is not yanked, deprecated or a
pre-release, and the package has a source repository and recent releases. The newest usable version is
recommended; a release younger than two weeks is only chosen when every older one has a known vulnerability, since
then the fix outweighs the risk of a fresh release. IT's exceptions can lift the source and activity rules, never
a vulnerability.
"""

import re
import time
from datetime import datetime
from urllib.parse import urlsplit

from . import auth, settings
from .support import Unreachable

MIN_AGE_DAYS = 14
MAX_SILENCE_DAYS = 3 * 365
_ECOSYSTEMS = {"pypi": "PyPI", "npm": "npm"}
_PRERELEASE = re.compile(r"(a|b|rc|dev|alpha|beta|pre|preview)\d*|-", re.IGNORECASE)
_OSV_CHECKS = 10  # mature versions checked for vulnerabilities before giving up on finding a clean one
_MAX_OSV_CHECKS = 40  # all versions checked at most, newest first
_SOURCE_HOST = re.compile(r"(^|\.)(github\.com|gitlab\.com|codeberg\.org|bitbucket\.org|sr\.ht)$|^git\.")
_SOURCE_SHORT = re.compile(r"^(github|gitlab|bitbucket):[\w.-]+/[\w.-]+$|^git@[\w.-]+:[\w.-]+/")


def _get(url: str) -> dict | None:
    try:
        with auth.http_client() as client:
            response = client.get(url, headers={"Accept": "application/json"})
    except Exception as exc:
        raise Unreachable() from exc
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _vulnerabilities(ecosystem: str, name: str, version: str) -> list[str]:
    try:
        with auth.http_client() as client:
            response = client.post("https://api.osv.dev/v1/query", json={
                "version": version, "package": {"name": name, "ecosystem": _ECOSYSTEMS[ecosystem]}})
    except Exception as exc:
        raise Unreachable() from exc
    response.raise_for_status()
    return sorted(v["id"] for v in response.json().get("vulns", []))


def _days_ago(stamp: str) -> float:
    return (time.time() - datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()) / 86400


def _order(version: str) -> tuple:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _source(urls: list) -> str | None:
    """The first address that points to a source repository host (checked on the host name, not the text)."""
    for url in urls:
        if not isinstance(url, str) or not url:
            continue
        host = urlsplit(url.removeprefix("git+")).hostname
        if (host and _SOURCE_HOST.search(host)) or _SOURCE_SHORT.match(url):
            return url
    return None


def _pypi(name: str) -> dict | None:
    data = _get(f"https://pypi.org/pypi/{name}/json")
    if data is None:
        return None
    info = data.get("info") or {}
    urls = list((info.get("project_urls") or {}).values()) + [info.get("home_page") or ""]
    releases = {}
    for version, files in (data.get("releases") or {}).items():
        if not files:
            continue
        releases[version] = {
            "age_days": min(_days_ago(f["upload_time_iso_8601"]) for f in files),
            "unusable": "yanked" if all(f.get("yanked") for f in files) else None,
            "requires": next((f.get("requires_python") for f in files if f.get("requires_python")), None)}
    inactive = "Development Status :: 7 - Inactive" in (info.get("classifiers") or [])
    return {"source": _source(urls),
            "license": info.get("license_expression") or info.get("license"), "inactive": inactive,
            "releases": releases}


def _npm(name: str) -> dict | None:
    data = _get(f"https://registry.npmjs.org/{name}")
    if data is None:
        return None
    times = data.get("time") or {}
    repository = data.get("repository") or {}
    releases = {}
    for version, meta in (data.get("versions") or {}).items():
        if version not in times:
            continue
        releases[version] = {"age_days": _days_ago(times[version]),
                             "unusable": "deprecated" if meta.get("deprecated") else None,
                             "requires": (meta.get("engines") or {}).get("node")}
    return {"source": _source([repository.get("url") if isinstance(repository, dict) else repository]),
            "license": data.get("license") if isinstance(data.get("license"), str) else None,
            "inactive": False, "releases": releases}


def check(ecosystem: str, name: str, version: str = "") -> dict:
    ecosystem = (ecosystem or "").lower()
    if ecosystem not in _ECOSYSTEMS:
        raise ValueError(f"ecosystem must be one of: {', '.join(_ECOSYSTEMS)}")
    package = (_pypi if ecosystem == "pypi" else _npm)(name)
    result = {"ecosystem": ecosystem, "package": name, "requested": version or None}
    if package is None or not package["releases"]:
        return {**result, "verdict": "blocked", "reasons": ["the package does not exist in the registry"]}

    excepted = any(e.get("package", "").lower() == f"{ecosystem}:{name}".lower()
                   for e in settings.load()["dependency_exceptions"])
    reasons = []
    if not package["source"] and not excepted:
        reasons.append("no source repository is published: origin cannot be verified")
    newest_age = min(r["age_days"] for r in package["releases"].values())
    if (package["inactive"] or newest_age > MAX_SILENCE_DAYS) and not excepted:
        reasons.append("no release in more than three years, or marked inactive: likely unmaintained")
    if reasons:
        return {**result, "verdict": "blocked", "reasons": reasons, "source": package["source"]}

    candidates = sorted((v for v, r in package["releases"].items()
                         if not r["unusable"] and not _PRERELEASE.search(v.lstrip("v"))), key=_order, reverse=True)
    if not any(package["releases"][v]["age_days"] >= MIN_AGE_DAYS for v in candidates):
        return {**result, "verdict": "blocked", "source": package["source"],
                "reasons": ["the package has no release older than two weeks"]}
    def is_mature(v: str) -> bool:
        return package["releases"][v]["age_days"] >= MIN_AGE_DAYS

    # Newest first, until the first clean mature version, or until enough mature ones were found vulnerable.
    checked: dict[str, list[str]] = {}
    for candidate in candidates[:_MAX_OSV_CHECKS]:
        checked[candidate] = _vulnerabilities(ecosystem, name, candidate)
        mature_checked = [v for v in checked if is_mature(v)]
        if (is_mature(candidate) and not checked[candidate]) or len(mature_checked) >= _OSV_CHECKS:
            break
    clean = [v for v in checked if not checked[v]]
    mature_clean = [v for v in clean if is_mature(v)]
    mature_checked = [v for v in checked if is_mature(v)]
    recommended, note = None, None
    if mature_clean:  # the newest version that is clean and at least two weeks old
        recommended = mature_clean[0]
    elif mature_checked and clean:  # every mature version checked is vulnerable: the fix outweighs the risk
        recommended = max(clean, key=lambda v: package["releases"][v]["age_days"])
        note = "newer than two weeks, chosen because every older version checked has a known vulnerability"

    def describe(v: str) -> dict:
        release = package["releases"][v]
        return {"version": v, "released_days_ago": round(release["age_days"]), "requires": release["requires"],
                "vulnerabilities": checked.get(v)}

    base = {**result, "source": package["source"], "license": package["license"],
            "recommended": describe(recommended) if recommended else None}
    if note:
        base["note"] = note
    if not version:
        if not recommended:
            return {**base, "verdict": "blocked", "reasons": ["no version passes the rules"]}
        return {**base, "verdict": "allowed", "version": recommended}

    release = package["releases"].get(version)
    if release is None:
        return {**base, "verdict": "blocked", "reasons": [f"version {version} does not exist"]}
    if release["unusable"]:
        return {**base, "verdict": "blocked", "reasons": [f"version {version} is {release['unusable']}"]}
    if _PRERELEASE.search(version.lstrip("v")):
        return {**base, "verdict": "blocked", "reasons": [f"version {version} is a pre-release"]}
    found = checked[version] if version in checked else _vulnerabilities(ecosystem, name, version)
    if found:
        return {**base, "verdict": "blocked", "reasons": [f"known vulnerabilities: {', '.join(found)}"]}
    if release["age_days"] < MIN_AGE_DAYS and version != recommended:
        return {**base, "verdict": "blocked",
                "reasons": [f"version {version} is newer than two weeks and is not needed to fix a vulnerability"]}
    return {**base, "verdict": "allowed", "version": version}
