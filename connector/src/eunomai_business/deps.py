"""Dependency check: which version of a package may be used, decided by rules, not by the model.

Deny by default. A version is usable only if it has no known vulnerability (OSV), is not yanked, deprecated or a
pre-release, and the package has a source repository that exists and recent releases. The newest usable version is
recommended; a release younger than two weeks is only chosen when every older one has a known vulnerability, since
then the fix outweighs the risk of a fresh release. IT's exceptions can lift the source and activity rules, never
a vulnerability.
"""

import fnmatch
import ipaddress
import json
import os
import re
import socket
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from packaging.markers import InvalidMarker, Marker, UndefinedComparison, UndefinedEnvironmentName
from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from . import auth, settings
from .support import Unreachable

MIN_AGE_DAYS = 14
MAX_SILENCE_DAYS = 3 * 365
_ECOSYSTEMS = {"pypi": "PyPI", "npm": "npm"}
_PRERELEASE = re.compile(r"(a|b|rc|dev|alpha|beta|pre|preview)\d*|-", re.IGNORECASE)
_OSV_CHECKS = 10  # mature versions checked for vulnerabilities before giving up on finding a clean one
_MAX_OSV_CHECKS = 40  # all versions checked at most, newest first
_SOURCE_HOST = re.compile(r"(^|\.)(github\.com|gitlab\.com|codeberg\.org|bitbucket\.org|sr\.ht|heptapod\.net|"
                          r"sourceforge\.net|launchpad\.net|pagure\.io|gitea\.com)$|^(git|gitlab|forge)\.")
_SOURCE_SHORT = re.compile(r"^(github|gitlab|bitbucket):[\w.-]+/[\w.-]+$|^git@[\w.-]+:[\w.-]+/")
# Project links a package labels as its code, wherever it is hosted (foss.heptapod.net, a foundation's own forge...)
_SOURCE_LABELS = {"source", "source code", "sourcecode", "repository", "code", "github", "gitlab", "git", "scm"}
_LOCKFILES = ("package-lock.json", "uv.lock", "vendor.json")
_PYPI_INDEX = "https://pypi.org/simple"
_PYPI_FILE = re.compile(r"https://files\.pythonhosted\.org/[\w./%+~-]+")  # no query, fragment or backslash to hide in
_UV_LOCK_FIELDS = {"version", "revision", "requires-python", "resolution-markers", "supported-markers",
                   "required-markers", "conflicts", "options", "manifest", "package"}
# Settings that change neither where a package comes from nor which one is installed. Any other is refused.
_UV_SETTINGS = {"cache-keys", "default-groups", "dev-dependencies", "environments", "exclude-newer",
                "exclude-newer-package", "managed", "package", "required-environments", "required-version"}
_NPM_NAME = re.compile(r"(@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*", re.IGNORECASE)
_VENDOR_URL = re.compile(r"https://(github\.com|gitlab\.com|codeberg\.org|registry\.npmjs\.org)/[\w./%+~{}-]+")
_VENDOR_HASHES = ("sha256", "sha384", "sha512", "executables")
_SKIP_FOLDERS = {".git", ".venv", "venv", "node_modules", "__pycache__", "archive"}
_UNREADABLE = (ValueError, UnicodeDecodeError, TypeError, AttributeError, KeyError, RecursionError)
_AT_ONCE = 8  # packages checked at the same time: the audit runs before every send


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
    try:
        return url if urlsplit(url).scheme == "https" else None
    except ValueError:
        return None


def _public(host: str) -> bool:
    """Whether every address of a host is on the public internet: the check never probes the user's network."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)


def _exists(url: str) -> bool | None:
    """Whether the source repository's web address answers (None: it could not be reached). A signal of origin, not
    proof: only https, only public hosts, no redirect followed (a redirect counts as an answer), body never read."""
    address = _web_address(url)
    if not address:
        return False
    host = urlsplit(address).hostname or ""
    if not _public(host):
        return None
    try:
        with auth.http_client() as client:
            with client.stream("GET", address, follow_redirects=False, timeout=10) as response:
                return response.status_code < 400
    except Exception:
        return None


def _pypi(name: str) -> dict | None:
    data = _get(f"https://pypi.org/pypi/{name}/json")
    if data is None:
        return None
    info = data.get("info") or {}
    links = info.get("project_urls") or {}
    urls = list(links.values()) + [info.get("home_page") or ""]
    labelled = [url for label, url in links.items() if _web_address(str(url))
                and re.sub(r"[-_]+", " ", str(label)).strip().lower() in _SOURCE_LABELS]
    releases = {}
    for version, files in (data.get("releases") or {}).items():
        if not files:
            continue
        releases[version] = {
            "age_days": min(_days_ago(f["upload_time_iso_8601"]) for f in files),
            "unusable": "yanked" if all(f.get("yanked") for f in files) else None,
            "requires": next((f.get("requires_python") for f in files if f.get("requires_python")), None),
            "digests": {(f.get("digests") or {}).get("sha256") for f in files}}
    inactive = "Development Status :: 7 - Inactive" in (info.get("classifiers") or [])
    return {"source": _source(labelled[:1] or urls, labelled),  # what it labels as its code before any other link
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
        engines = meta.get("engines")  # a list in some old versions
        releases[version] = {"age_days": _days_ago(times[version]),
                             "unusable": "deprecated" if meta.get("deprecated") else None,
                             "requires": engines.get("node") if isinstance(engines, dict) else None}
    declared = repository.get("url") if isinstance(repository, dict) else repository
    return {"source": _source([declared], [_web_address(declared)] if isinstance(declared, str) else []),
            "license": data.get("license") if isinstance(data.get("license"), str) else None,
            "inactive": False, "releases": releases}


def _excepted(ecosystem: str, name: str) -> bool:
    def key(text: str) -> str:
        return _normalized(text) if ecosystem == "pypi" else text.lower()

    return any(e.get("package", "").lower().startswith(f"{ecosystem}:")
               and key(e["package"].split(":", 1)[1]) == key(name)
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

def _project_files(folder: Path, links: bool = False):
    """Files of a project, never following a link or junction out of it, skipping environments and archives. With
    `links`, the links to files instead."""
    for current, folders, files in os.walk(folder, followlinks=False):
        here = Path(current)
        folders[:] = [f for f in folders if f not in _SKIP_FOLDERS
                      and not (here / f).is_symlink() and not (here / f).is_junction()]
        for name in files:
            if (here / name).is_symlink() is links:
                yield here / name


def _is_pinned_list(file: Path) -> bool:
    return file.name.lower() in _LOCKFILES or fnmatch.fnmatch(file.name.lower(), "requirements*.txt")


def _pinned_files(folder: Path) -> list[Path]:
    return sorted(filter(_is_pinned_list, _project_files(folder)))


# A marker that names one platform which is not a computer's (a web browser's "emscripten", for example): the pin
# is never installed on Windows, macOS or Linux. Anything more complex is audited as usual.
_ELSEWHERE = re.compile(r"""^\s*(sys_platform|platform_system|os_name)\s*==\s*['"]([^'"]+)['"]\s*$""")
_COMPUTERS = {"win32", "cygwin", "linux", "darwin", "windows", "nt", "posix"}


def _requirements(text: str, siblings: set[str]) -> tuple[list[tuple[str, str]], list[str], bool, list[str]]:
    """(name, version) pins, lines that are not exact pins of the public index, whether every pin has a hash, and
    pins that only other platforms install. `-r`/`-c` may only name another pinned list in the same folder (audited
    on its own); every other option, such as another index or a local path, is refused: pins are checked against
    the registry pip would not use."""
    pins, loose, hashed, elsewhere = [], [], True, []
    for line in re.sub(r"\\\r?\n", " ", text).splitlines():
        line = line.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        option = re.match(r"^(-r|-c|--requirement|--constraint)[ =]+(\S+)$", line)
        if option:
            if option.group(2) not in siblings:
                loose.append(f"{line} (only another pinned list in the same folder)")
            continue
        if line.startswith("-"):
            loose.append(f"{line} (options are not allowed in a pinned list)")
            continue
        requirement = line.split(";")[0].split(" --hash")[0].strip()
        marker = line.split(";", 1)[1].split(" --hash")[0] if ";" in line else ""
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*===?\s*([A-Za-z0-9.+!_-]+)$", requirement)
        platform_only = _ELSEWHERE.match(marker)
        if match and platform_only and platform_only.group(2).lower() not in _COMPUTERS:
            elsewhere.append(f"{requirement} (only on {platform_only.group(2)})")
        elif match:
            pins.append((_normalized(match.group(1)), match.group(3)))
            hashed = hashed and "--hash=" in line
        else:
            loose.append(requirement)
    return pins, loose, hashed and bool(pins), elsewhere


def _npm_lock(text: str) -> tuple[list[tuple[str, str]], list[str], bool, list[str]]:
    """Pins of an npm lockfile (version 2 or 3), each from the public registry under its own name."""
    data = json.loads(text)
    if "packages" not in data:
        return [], ["lockfile version 1 is not supported: regenerate it with npm 7 or later"], False, []
    pins, loose, hashed = [], [], True
    for path, meta in data["packages"].items():
        if not path or meta.get("link") or "version" not in meta:
            continue
        name = meta.get("name") or path.rsplit("node_modules/", 1)[-1]
        resolved = meta.get("resolved") or ""
        if not resolved.startswith(f"https://registry.npmjs.org/{name}/-/"):
            loose.append(f"{path}: not from the public registry under its own name ({resolved or 'no source'})")
            continue
        pins.append((name, meta["version"]))
        hashed = hashed and bool(meta.get("integrity"))
    return pins, loose, hashed and bool(pins), []


def _vulnerable(queries: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], list[str]]:
    """Known vulnerabilities of many exact versions in one request to OSV; an incomplete answer is no answer."""
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
    if len(results) != len(queries):
        raise Unreachable()
    return {query: sorted(v["id"] for v in (result or {}).get("vulns", []))
            for query, result in zip(queries, results)}


def _own_project(folder: Path) -> tuple[str, list[Requirement], list[str]]:
    """The project beside a lockfile: its name, every requirement its `pyproject.toml` declares, and the uv settings
    the audit cannot answer for, since they may install what the lockfile does not show."""
    file = folder / "pyproject.toml"
    if not file.is_file():
        return "", [], []
    data = tomllib.loads(file.read_text(encoding="utf-8"))
    project = data.get("project") or {}
    uv = (data.get("tool") or {}).get("uv") or {}
    lists = [project.get("dependencies") or [], uv.get("dev-dependencies") or [],
             *(project.get("optional-dependencies") or {}).values(), *(data.get("dependency-groups") or {}).values()]
    asked = [Requirement(item) for items in lists for item in items
             if isinstance(item, str)]  # a group may also include another group, which is not a requirement
    settings = [f"tool.uv.{key}" for key in sorted(set(uv) - _UV_SETTINGS)]
    return _normalized(project.get("name") or ""), asked, settings + ["uv.toml"] * (folder / "uv.toml").is_file()


def _uv_lock(text: str, folder: Path, digests: dict) -> tuple[list[tuple[str, str]], list[str], bool, list[str]]:
    """Pins of a uv lockfile, each with files on the public index, and their hashes in `digests` to compare with what
    the registry published: anyone can upload there, so the address does not say which package a file is. Only the
    project itself may come from anywhere else. The lockfile must also still answer what `pyproject.toml` asks for:
    if it does not, a plain `uv sync` writes a new one and installs what nobody audited."""
    data = tomllib.loads(text)
    if data.get("version") != 1 or set(data) - _UV_LOCK_FIELDS:  # uv also reads older names for the same tables
        raise ValueError("unknown lockfile format")
    own, asked, settings = _own_project(folder)
    pins, versions = [], {}
    loose = [f"{setting} (not a setting the audit can answer for)" for setting in settings]
    for package in data.get("package") or []:
        name, version, source = _normalized(package["name"]), package.get("version"), package.get("source") or {}
        versions.setdefault(name, set()).add(version)
        files = [*(package.get("wheels") or []), *([package["sdist"]] if "sdist" in package else [])]
        if name == own and source in ({"virtual": "."}, {"editable": "."}) and not files:
            continue
        if not version or not isinstance(version, str) or set(source) != {"registry"} or not files \
                or str(source["registry"]).rstrip("/") != _PYPI_INDEX or not all(
                    _PYPI_FILE.fullmatch(str(file.get("url", ""))) and file.get("hash") for file in files):
            loose.append(f"{name} (only the public index)")
            continue
        pins.append((name, version))
        digests.setdefault(("pypi", name, version), set()).update(
            str(file["hash"]).removeprefix("sha256:") for file in files)
    python_from = _lowest_python(data.get("requires-python")) or _declared_python(folder) or _SUPPORTED_PYTHONS[0]
    for requirement in asked:
        name, marker = _normalized(requirement.name), str(requirement.marker or "")
        if requirement.url:
            loose.append(f"{name} (only the public index)")
        elif marker and not _needed_on_a_computer(marker, python_from):  # uv rightly drops what no Python here needs
            continue
        elif name not in versions:
            loose.append(f"{name} (in pyproject.toml, not in the lockfile)")
        elif name != own and not any(requirement.specifier.contains(v, prereleases=True) for v in versions[name]):
            loose.append(f"{name} (pyproject.toml asks for {requirement.specifier}, not in the lockfile)")
    return pins, loose, True, []


def _vendored(text: str) -> tuple[list[tuple[str, str]], list[str], bool, list[str]]:
    """Files a project keeps in its own tree: `vendor.json` maps a name to its `version` on npm, and to the `package`
    it was published under when that is not the name. A `url` says where the file really comes from. The project
    checks the bytes itself, against the hashes kept here."""
    pins, loose, hashed = [], [], True
    for key, entry in json.loads(text).items():
        if key == "$schema" and isinstance(entry, str):
            continue
        name, version, url = entry.get("package", key), entry.get("version"), entry.get("url")
        if not (isinstance(name, str) and _NPM_NAME.fullmatch(name) and version and isinstance(version, str)):
            loose.append(f"{key} (a vendored file names its package and version)")
        elif url is not None and not _VENDOR_URL.fullmatch(str(url)):
            loose.append(f"{key} (only over https from a known code host or the npm registry)")
        else:
            pins.append((name, version))
            hashed = hashed and any(entry.get(field) for field in _VENDOR_HASHES)
    return pins, loose, hashed, []


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# Windows, Linux and macOS on the usual processors, with the CPython versions still supported upstream.
_SUPPORTED_PYTHONS = ((3, 10), (3, 11), (3, 12), (3, 13), (3, 14), (3, 15))
_COMPUTER_ENVIRONMENTS = [
    {"sys_platform": sys_platform, "platform_system": system, "os_name": os_name, "platform_machine": machine,
     "python_version": python, "python_full_version": f"{python}.0", "implementation_name": "cpython",
     "platform_python_implementation": "CPython", "implementation_version": f"{python}.0",
     "platform_release": "", "platform_version": ""}
    for sys_platform, system, os_name in (("win32", "Windows", "nt"), ("linux", "Linux", "posix"),
                                          ("darwin", "Darwin", "posix"))
    for machine in ("AMD64", "x86_64", "ARM64", "aarch64", "arm64")
    for python in (f"{major}.{minor}" for major, minor in _SUPPORTED_PYTHONS)]

# The Python a list was compiled for, from the header `uv pip compile` writes.
_COMPILED_FOR = re.compile(r"^#.*--python-version[ =](\d+)\.(\d+)", re.MULTILINE)


def _declared_python(folder: Path) -> tuple[int, int] | None:
    """The lowest supported Python a `pyproject.toml` beside a list accepts (`requires-python`), if it says.
    A minor version counts if any of its releases is accepted (`>=3.11.4` still runs on 3.11)."""
    try:
        project = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8")).get("project")
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return _lowest_python(project.get("requires-python") if isinstance(project, dict) else None)


def _lowest_python(declared: object) -> tuple[int, int] | None:
    try:
        spec = SpecifierSet(declared) if isinstance(declared, str) and declared.strip() else None
    except InvalidSpecifier:
        return None
    if spec is None:
        return None
    return next((v for v in _SUPPORTED_PYTHONS
                 if any(spec.contains(f"{v[0]}.{v[1]}.{patch}") for patch in (0, 99))), None)


def _needed_on_a_computer(marker: str, python_from: tuple[int, int] = (3, 10)) -> bool:
    """Whether a requirement's marker (PEP 508) holds on Windows, Linux or macOS with a supported Python from
    `python_from` on: such a computer installs it, so a list without it fails there (`--require-hashes` refuses what
    is not listed). A marker that cannot be read or evaluated counts as needed."""
    try:
        parsed = Marker(marker)
        return any(parsed.evaluate(environment) for environment in _COMPUTER_ENVIRONMENTS
                   if tuple(int(n) for n in environment["python_version"].split(".")) >= python_from)
    except (InvalidMarker, UndefinedComparison, UndefinedEnvironmentName):
        return True


def _unpinned_requirements(pins: list[tuple[str, str]], python_from: tuple[int, int] = (3, 10)
                           ) -> tuple[list[str], list[str]]:
    """What the pinned PyPI packages require and the list leaves out, so a list of direct dependencies alone is not
    taken as the whole tree (a requirement only for Windows, Linux or macOS counts: one of them installs it); and,
    apart, what they require only on other platforms or Python versions, which the list may rightly leave out.
    Requirements of extras not asked for are not counted."""
    pinned = {name for name, _ in pins}
    missing, conditional = set(), set()
    with ThreadPoolExecutor(_AT_ONCE) as pool:
        answers = list(pool.map(lambda pin: _get(f"https://pypi.org/pypi/{pin[0]}/{pin[1]}/json") or {}, pins))
    for (name, version), data in zip(pins, answers):
        for requirement in (data.get("info") or {}).get("requires_dist") or []:
            found = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
            if not found or _normalized(found.group(1)) in pinned:
                continue
            marker = requirement.split(";", 1)[1] if ";" in requirement else ""
            needed = f"{_normalized(found.group(1))} (required by {name} {version})"
            if "extra" in marker:
                continue
            (conditional if marker and not _needed_on_a_computer(marker, python_from) else missing).add(
                needed + (f" when{marker}" if marker else ""))
    return sorted(missing), sorted(conditional)


def _declares_packages(folder: Path) -> bool:
    """Whether a project without a pinned list still declares packages to install."""
    for file in _project_files(folder):
        name = file.name.lower()
        if name in ("setup.py", "setup.cfg", "pipfile", "requirements.in", "poetry.lock", "yarn.lock",
                    "pnpm-lock.yaml"):
            return True
        try:
            if name == "pyproject.toml":
                data = tomllib.loads(file.read_text(encoding="utf-8"))
                project, tool = data.get("project") or {}, data.get("tool") or {}
                if project.get("dependencies") or tool.get("poetry") or (tool.get("uv") or {}).get("dev-dependencies") \
                        or "dependencies" in (project.get("dynamic") or []) \
                        or any((project.get("optional-dependencies") or {}).values()) \
                        or any((data.get("dependency-groups") or {}).values()):
                    return True
            if name == "package.json":
                data = json.loads(file.read_text(encoding="utf-8"))
                if data.get("dependencies") or data.get("devDependencies"):
                    return True
        except _UNREADABLE:
            return True  # unreadable: treat as declaring, so it is not waved through
    return False


def audit(folder: Path) -> dict:
    """Every package a project pins, direct and indirect, against the same rules as `check`. A project that
    installs anything pins all of it in requirements*.txt, package-lock.json or uv.lock; the files it keeps in its
    own tree are listed in vendor.json."""
    files = _pinned_files(folder)
    pins: dict[tuple[str, str, str], list[str]] = {}
    loose, unhashed, elsewhere, compiled_for = [], [], [], []
    # a tool follows a link the audit never reads
    loose += [f"{f.relative_to(folder).as_posix()}: a link, not a pinned list"
              for f in sorted(filter(_is_pinned_list, _project_files(folder, links=True)))]
    listed: dict[tuple[str, str], None] = {}  # a requirements list may leave something out; a lockfile cannot
    digests: dict[tuple[str, str, str], set[str]] = {}
    installs = False  # whether any file says what the project installs
    for file in files:
        kind = file.name.lower()
        eco = "npm" if kind in ("package-lock.json", "vendor.json") else "pypi"
        where = file.relative_to(folder).as_posix()
        try:
            text = file.read_text(encoding="utf-8")
            if kind == "package-lock.json":
                found, not_pinned, hashed, skipped = _npm_lock(text)
            elif kind == "vendor.json":
                found, not_pinned, hashed, skipped = _vendored(text)
            elif kind == "uv.lock":
                found, not_pinned, hashed, skipped = _uv_lock(text, file.parent, digests)
            else:
                siblings = {f.name for f in files if f.parent == file.parent and f != file}
                found, not_pinned, hashed, skipped = _requirements(text, siblings)
        except _UNREADABLE:
            loose.append(f"{where}: not readable as a pinned list")
            continue
        if eco == "pypi" and kind != "uv.lock":  # each list counts with its own Python; one that says nothing, with
            header = [(int(a), int(b)) for a, b in _COMPILED_FOR.findall(text)]  # every supported one
            compiled_for.append(min(header) if header else _declared_python(file.parent) or _SUPPORTED_PYTHONS[0])
            listed.update(dict.fromkeys(found))
        loose += [f"{where}: {line}" for line in not_pinned]
        elsewhere += [f"{where}: {line}" for line in skipped]
        if not hashed:
            unhashed.append(where)
        if not found and not not_pinned and not skipped and kind != "uv.lock":  # a project with no packages locks too
            loose.append(f"{where}: pins nothing")
        installs = installs or (kind != "vendor.json" and bool(found or kind != "uv.lock"))
        for name, version in found:
            pins.setdefault((eco, name, version), []).append(where)
    # a list compiled for a given Python (uv's header, or the project's `requires-python`) may leave out what only
    # older ones need; when neither says, every supported Python counts
    missing, conditional = _unpinned_requirements(list(listed), min(compiled_for, default=_SUPPORTED_PYTHONS[0]))
    loose += [f"missing from the pinned list: {item}" for item in missing]
    vulnerabilities = _vulnerable(list(pins))

    def judged(pin: tuple[tuple[str, str, str], list[str]]) -> dict | None:
        (eco, name, version), where = pin
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
            if digests.get((eco, name, version), set()) - release.get("digests", set()):
                reasons.append(f"a file in the lockfile is not one the registry published for version {version}")
        return {"ecosystem": eco, "package": name, "version": version, "files": where,
                "reasons": reasons} if reasons else None

    with ThreadPoolExecutor(_AT_ONCE) as pool:
        blocked = [found for found in pool.map(judged, sorted(pins.items())) if found]
    undeclared = not installs and not loose and _declares_packages(folder)
    result = {"verdict": "allowed" if files and not blocked and not loose and not undeclared else "blocked",
              "files": [f.relative_to(folder).as_posix() for f in files], "packages": len(pins),
              "blocked": blocked, "not_pinned": loose, "without_hashes": unhashed}
    if conditional:
        result["only_on_some_platforms"] = conditional
    if elsewhere:
        result["not_installed_on_computers"] = elsewhere
    if undeclared:  # vendored files are not a list of what the project installs
        result["reasons"] = ["packages are declared but not pinned: requirements*.txt, package-lock.json or uv.lock"]
    elif not files and not loose:
        result.update(verdict="allowed", note="the project installs no packages: nothing to check")
    return result
