"""Dependency check: which version of a package may be used, decided by rules, not by the model.

Deny by default. A version is usable only if it has no known vulnerability (OSV), is not yanked, deprecated or a
pre-release, and the package has a source repository that exists and recent releases. The newest usable version is
recommended; a release younger than two weeks is only chosen when every older one has a known vulnerability, since
then the fix outweighs the risk of a fresh release. IT's exceptions can lift the source and activity rules, never
a vulnerability.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
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
# Project links a package labels as its code, wherever it is hosted (foss.heptapod.net, a foundation's own forge...)
_SOURCE_LABELS = {"source", "source code", "sourcecode", "repository", "code", "github", "gitlab", "git", "scm"}
_PINNED_FILES = ("requirements*.txt", "package-lock.json")
_SKIP_FOLDERS = {".git", ".venv", "venv", "node_modules", "__pycache__", "archive"}


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


def _source(urls: list, labelled: list | None = None) -> str | None:
    """The first address on a known code host (checked on the host name, not the text), else the first https link
    the package itself labels as its code."""
    for url in urls:
        if not isinstance(url, str) or not url:
            continue
        host = urlsplit(url.removeprefix("git+")).hostname
        if (host and _SOURCE_HOST.search(host)) or _SOURCE_SHORT.match(url):
            return url
    return next((url for url in labelled or [] if isinstance(url, str)
                 and urlsplit(url.removeprefix("git+")).scheme == "https"), None)


def _web_address(url: str) -> str | None:
    """The https address of a repository written as git+https://, git://, git@host:path or github:owner/repo."""
    url = url.strip().removeprefix("git+").removesuffix(".git")
    short = re.match(r"^(github|gitlab|bitbucket):([\w.-]+/[\w.-]+)$", url)
    if short:
        return f"https://{short.group(1)}.{'org' if short.group(1) == 'bitbucket' else 'com'}/{short.group(2)}"
    ssh = re.match(r"^(?:ssh://)?git@([\w.-]+)[:/](.+)$", url)
    if ssh:
        return f"https://{ssh.group(1)}/{ssh.group(2)}"
    if url.startswith("git://"):
        url = "https://" + url.removeprefix("git://")
    return url if urlsplit(url).scheme == "https" else None


def _exists(url: str) -> bool | None:
    """Whether the source repository answers (None: it could not be reached)."""
    address = _web_address(url)
    if not address:
        return False
    try:
        with auth.http_client() as client:
            response = client.get(address, follow_redirects=True)
    except Exception:
        return None
    return response.status_code < 400


def _pypi(name: str) -> dict | None:
    data = _get(f"https://pypi.org/pypi/{name}/json")
    if data is None:
        return None
    info = data.get("info") or {}
    links = info.get("project_urls") or {}
    urls = list(links.values()) + [info.get("home_page") or ""]
    labelled = [url for label, url in links.items()
                if re.sub(r"[-_]+", " ", str(label)).strip().lower() in _SOURCE_LABELS]
    releases = {}
    for version, files in (data.get("releases") or {}).items():
        if not files:
            continue
        releases[version] = {
            "age_days": min(_days_ago(f["upload_time_iso_8601"]) for f in files),
            "unusable": "yanked" if all(f.get("yanked") for f in files) else None,
            "requires": next((f.get("requires_python") for f in files if f.get("requires_python")), None)}
    inactive = "Development Status :: 7 - Inactive" in (info.get("classifiers") or [])
    return {"source": _source(urls, labelled),
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
    declared = repository.get("url") if isinstance(repository, dict) else repository
    return {"source": _source([declared], [_web_address(declared)] if isinstance(declared, str) else []),
            "license": data.get("license") if isinstance(data.get("license"), str) else None,
            "inactive": False, "releases": releases}


def _excepted(ecosystem: str, name: str) -> bool:
    return any(e.get("package", "").lower() == f"{ecosystem}:{name}".lower()
               for e in settings.load()["dependency_exceptions"])


def _origin_reasons(ecosystem: str, name: str, package: dict) -> list[str]:
    """Where the package comes from and whether it is maintained; IT's exceptions lift these rules."""
    if _excepted(ecosystem, name):
        return []
    reasons = []
    if not package["source"]:
        reasons.append("no source repository is published: origin cannot be verified")
    else:
        found = _exists(package["source"])
        if found is False:
            reasons.append(f"the published source repository does not exist: {package['source']}")
        elif found is None:
            reasons.append(f"the published source repository could not be reached to verify it: {package['source']}")
    newest_age = min(r["age_days"] for r in package["releases"].values())
    if package["inactive"] or newest_age > MAX_SILENCE_DAYS:
        reasons.append("no release in more than three years, or marked inactive: likely unmaintained")
    return reasons


def check(ecosystem: str, name: str, version: str = "") -> dict:
    ecosystem = (ecosystem or "").lower()
    if ecosystem not in _ECOSYSTEMS:
        raise ValueError(f"ecosystem must be one of: {', '.join(_ECOSYSTEMS)}")
    package = (_pypi if ecosystem == "pypi" else _npm)(name)
    result = {"ecosystem": ecosystem, "package": name, "requested": version or None}
    if package is None or not package["releases"]:
        return {**result, "verdict": "blocked", "reasons": ["the package does not exist in the registry"]}

    reasons = _origin_reasons(ecosystem, name, package)
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


# --- the whole tree a project installs ----------------------------------------------------------------------

def _pinned_files(folder: Path) -> list[Path]:
    found = []
    for pattern in _PINNED_FILES:
        found += [f for f in folder.rglob(pattern) if not _SKIP_FOLDERS & set(f.relative_to(folder).parts[:-1])]
    return sorted(found)


def _requirements(text: str) -> tuple[list[tuple[str, str]], list[str], bool]:
    """(name, version) pins, lines that are not pinned exactly, and whether every pin carries a hash."""
    pins, loose, hashed = [], [], True
    for line in re.sub(r"\\\r?\n", " ", text).splitlines():
        line = line.split(" #")[0].strip()
        if not line or line.startswith(("#", "-r ", "--")):
            continue
        requirement = line.split(";")[0].split(" --hash")[0].strip()
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*===?\s*([A-Za-z0-9.+!_-]+)$", requirement)
        if match:
            pins.append((_normalized(match.group(1)), match.group(3)))
            hashed = hashed and "--hash=" in line
        else:
            loose.append(requirement)
    return pins, loose, hashed and bool(pins)


def _npm_lock(text: str) -> tuple[list[tuple[str, str]], list[str], bool]:
    packages = json.loads(text).get("packages") or {}
    pins, hashed = [], True
    for path, meta in packages.items():
        if not path or meta.get("link") or "version" not in meta:
            continue
        pins.append((path.rsplit("node_modules/", 1)[-1], meta["version"]))
        hashed = hashed and bool(meta.get("integrity"))
    return pins, [], hashed and bool(pins)


def _vulnerable(queries: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], list[str]]:
    """Known vulnerabilities of many exact versions in one request to OSV."""
    if not queries:
        return {}
    try:
        with auth.http_client() as client:
            response = client.post("https://api.osv.dev/v1/querybatch", json={"queries": [
                {"version": version, "package": {"name": name, "ecosystem": _ECOSYSTEMS[eco]}}
                for eco, name, version in queries]})
    except Exception as exc:
        raise Unreachable() from exc
    response.raise_for_status()
    results = response.json().get("results", [])
    return {query: sorted(v["id"] for v in (result or {}).get("vulns", []))
            for query, result in zip(queries, results)}


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _unpinned_requirements(pins: list[tuple[str, str]]) -> list[str]:
    """What the pinned PyPI packages require and the list leaves out, so a list of direct dependencies alone is not
    taken as the whole tree. Requirements that apply only to an extra or to some platforms are not counted."""
    pinned = {name for name, _ in pins}
    missing = []
    for name, version in pins:
        data = _get(f"https://pypi.org/pypi/{name}/{version}/json") or {}
        for requirement in (data.get("info") or {}).get("requires_dist") or []:
            if ";" in requirement:
                continue
            needed = _normalized(re.match(r"[A-Za-z0-9._-]+", requirement.strip()).group(0))
            if needed not in pinned:
                missing.append(f"{needed} (required by {name} {version})")
    return sorted(set(missing))


def audit(folder: Path) -> dict:
    """Every package a project pins, direct and indirect, against the same rules as `check`. A project that
    installs anything pins all of it in requirements*.txt or package-lock.json."""
    files = _pinned_files(folder)
    pins: dict[tuple[str, str, str], list[str]] = {}
    loose, unhashed = [], []
    for file in files:
        eco = "npm" if file.name == "package-lock.json" else "pypi"
        found, not_pinned, hashed = (_npm_lock if eco == "npm" else _requirements)(file.read_text(encoding="utf-8"))
        where = file.relative_to(folder).as_posix()
        loose += [f"{where}: {line}" for line in not_pinned]
        if not hashed:
            unhashed.append(where)
        for name, version in found:
            pins.setdefault((eco, name, version), []).append(where)
    loose += [f"missing from the pinned list: {item}"
              for item in _unpinned_requirements([(n, v) for eco, n, v in pins if eco == "pypi"])]
    vulnerabilities = _vulnerable(list(pins))
    blocked = []
    for (eco, name, version), where in sorted(pins.items()):
        package = (_pypi if eco == "pypi" else _npm)(name)
        release = (package or {}).get("releases", {}).get(version)
        if package is None or release is None:
            reasons = ["the package or this version does not exist in the registry"]
        else:
            reasons = _origin_reasons(eco, name, package)
            if release["unusable"]:
                reasons.append(f"version {version} is {release['unusable']}")
            if _PRERELEASE.search(version.lstrip("v")):
                reasons.append(f"version {version} is a pre-release")
            if vulnerabilities.get((eco, name, version)):
                reasons.append(f"known vulnerabilities: {', '.join(vulnerabilities[(eco, name, version)])}")
            elif release["age_days"] < MIN_AGE_DAYS and check(eco, name, version)["verdict"] != "allowed":
                reasons.append(f"version {version} is newer than two weeks and is not needed to fix a vulnerability")
        if reasons:
            blocked.append({"ecosystem": eco, "package": name, "version": version, "files": where, "reasons": reasons})
    result = {"verdict": "allowed" if files and not blocked and not loose else "blocked",
              "files": [f.relative_to(folder).as_posix() for f in files], "packages": len(pins),
              "blocked": blocked, "not_pinned": loose, "without_hashes": unhashed}
    if not files:
        result["reasons"] = ["no pinned list found: requirements*.txt or package-lock.json"]
    return result
