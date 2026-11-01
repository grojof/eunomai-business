"""The specialist's settings and the dependency check, with registry and OSV answers simulated."""

import json
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from eunomai_business import deps, server as tools, settings


REAL_EXISTS = deps._exists  # before the fixture below replaces it


@pytest.fixture(autouse=True)
def source_repositories_exist(monkeypatch):
    monkeypatch.setattr(deps, "_exists", lambda url: True)


def configure(monkeypatch, **values):
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps(values))


# --- settings ------------------------------------------------------------------------------------------------

def test_defaults_deny_free_development(monkeypatch):
    monkeypatch.delenv("EUNOMAI_SPECIALIST", raising=False)
    assert settings.load()["docs_language"] == "en" and settings.load()["code_language"] == "en"
    assert settings.development(None)["code_allowed"] is False


def test_code_language_follows_the_docs_language(monkeypatch):
    configure(monkeypatch, docs_language="es")
    assert settings.load()["code_language"] == "es"


def declared(text: str) -> dict:
    return {"file": ".eunomai/project.toml", "from": "the main branch on the server", "text": text}


def test_a_project_declares_its_technologies(monkeypatch):
    monkeypatch.delenv("EUNOMAI_SPECIALIST", raising=False)
    allowed = settings.development(declared('[development]\ncode = true\ntechnologies = ["Python"]\n'))
    assert allowed == {"code_allowed": True, "technologies": ["Python"], "reason": "the project declares it"}


@pytest.mark.parametrize("text, reason", [
    ("[development]\ncode = false\n", "declares that no code is written here"),
    ('[development]\ncode = "yes"\n', "is not valid: [development] takes code"),
    ('[development]\ncode = true\ntechnologies = "Python"\n', "is not valid"),
    ('[development]\ncode = true\ntechnologies = [""]\n', "is not valid"),
    ("development = true\n", "is not valid"),
    ("[development\ncode = true\n", "is not valid TOML"),
    ('[development]\ncode = true\ntechnologie = ["Python"]\n', "unknown keys in [development] (technologie)"),
])
def test_the_project_decides_even_against_free_development(monkeypatch, text, reason):
    configure(monkeypatch, free_development=True)
    refused = settings.development(declared(text))
    assert refused["code_allowed"] is False and reason in refused["reason"]


def test_a_declaration_without_development_leaves_it_to_the_build(monkeypatch):
    configure(monkeypatch, free_development=True, allowed_technologies=["Python"])
    assert settings.development(declared('[test]\nbranch = "pruebas"\n'))["reason"] == "free development is enabled"
    configure(monkeypatch)
    assert settings.development(declared(""))["code_allowed"] is False


def test_free_development_with_a_list(monkeypatch):
    configure(monkeypatch, free_development=True, allowed_technologies=["Python"])
    assert settings.development(None) == {"code_allowed": True, "technologies": ["Python"],
                                          "reason": "free development is enabled"}


# --- dependency check ----------------------------------------------------------------------------------------

def stamp(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def pypi(monkeypatch, releases: dict, vulns: dict | None = None, source="https://github.com/org/pkg",
         classifiers=()):
    """releases: version -> (days ago, yanked)."""
    data = {"info": {"project_urls": {"Source": source} if source else {}, "home_page": "",
                     "classifiers": list(classifiers), "license": "MIT"},
            "releases": {v: [{"upload_time_iso_8601": stamp(days), "yanked": yanked, "requires_python": ">=3.10"}]
                         for v, (days, yanked) in releases.items()}}
    monkeypatch.setattr(deps, "_get", lambda url: data)
    monkeypatch.setattr(deps, "_vulnerabilities", lambda eco, name, version: (vulns or {}).get(version, []))


def test_newest_clean_mature_version_is_recommended(monkeypatch):
    pypi(monkeypatch, {"1.0.0": (400, False), "1.1.0": (100, False), "1.2.0": (30, False)})
    result = deps.check("pypi", "pkg")
    assert result["verdict"] == "allowed" and result["version"] == "1.2.0"
    assert result["recommended"]["requires"] == ">=3.10"


def test_a_vulnerable_newest_version_falls_back_to_a_clean_one(monkeypatch):
    pypi(monkeypatch, {"1.1.0": (100, False), "1.2.0": (30, False)}, vulns={"1.2.0": ["GHSA-x"]})
    assert deps.check("pypi", "pkg")["version"] == "1.1.0"
    blocked = deps.check("pypi", "pkg", "1.2.0")
    assert blocked["verdict"] == "blocked" and "GHSA-x" in blocked["reasons"][0]


def test_a_fresh_release_wins_only_when_it_fixes_a_vulnerability(monkeypatch):
    pypi(monkeypatch, {"1.1.0": (100, False), "1.2.0": (3, False)}, vulns={"1.1.0": ["CVE-1"]})
    result = deps.check("pypi", "pkg")
    assert result["version"] == "1.2.0" and "vulnerability" in result["note"]


def test_a_fresh_release_without_a_reason_is_refused(monkeypatch):
    pypi(monkeypatch, {"1.1.0": (100, False), "1.2.0": (3, False)})
    assert deps.check("pypi", "pkg")["version"] == "1.1.0"
    refused = deps.check("pypi", "pkg", "1.2.0")
    assert refused["verdict"] == "blocked" and "two weeks" in refused["reasons"][0]


def test_yanked_and_pre_releases_are_never_used(monkeypatch):
    pypi(monkeypatch, {"1.0.0": (200, False), "1.1.0": (100, True), "2.0.0rc1": (60, False)})
    assert deps.check("pypi", "pkg")["version"] == "1.0.0"
    assert "yanked" in deps.check("pypi", "pkg", "1.1.0")["reasons"][0]
    assert "pre-release" in deps.check("pypi", "pkg", "2.0.0rc1")["reasons"][0]


@pytest.mark.parametrize("case, expected", [
    ({"source": None}, "no source repository"),
    ({"classifiers": ["Development Status :: 7 - Inactive"]}, "unmaintained"),
])
def test_unknown_origin_and_unmaintained_packages_are_blocked(monkeypatch, case, expected):
    pypi(monkeypatch, {"1.0.0": (100, False)}, **case)
    result = deps.check("pypi", "pkg")
    assert result["verdict"] == "blocked" and expected in result["reasons"][0]


def test_a_package_silent_for_years_is_blocked(monkeypatch):
    pypi(monkeypatch, {"1.0.0": (4 * 365, False)})
    assert "unmaintained" in deps.check("pypi", "pkg")["reasons"][0]


def test_it_exceptions_lift_origin_rules_but_never_vulnerabilities(monkeypatch):
    configure(monkeypatch, dependency_exceptions=[{"package": "pypi:pkg", "reason": "vetted by IT"}])
    pypi(monkeypatch, {"1.0.0": (4 * 365, False)}, source=None)
    assert deps.check("pypi", "pkg")["verdict"] == "allowed"
    pypi(monkeypatch, {"1.0.0": (4 * 365, False)}, vulns={"1.0.0": ["CVE-2"]}, source=None)
    assert deps.check("pypi", "pkg")["verdict"] == "blocked"


def test_a_brand_new_package_is_blocked(monkeypatch):
    pypi(monkeypatch, {"0.1.0": (2, False)})
    assert "older than two weeks" in deps.check("pypi", "pkg")["reasons"][0]


def test_a_missing_package_is_blocked(monkeypatch):
    monkeypatch.setattr(deps, "_get", lambda url: None)
    assert deps.check("npm", "nothing-here")["verdict"] == "blocked"


def test_npm_deprecated_versions_are_skipped(monkeypatch):
    data = {"time": {"1.0.0": stamp(200), "1.1.0": stamp(100)}, "repository": {"url": "git+https://github.com/o/p"},
            "license": "MIT", "versions": {"1.0.0": {"engines": {"node": ">=18"}},
                                           "1.1.0": {"deprecated": "use another package"}}}
    monkeypatch.setattr(deps, "_get", lambda url: data)
    monkeypatch.setattr(deps, "_vulnerabilities", lambda *a: [])
    result = deps.check("npm", "p")
    assert result["version"] == "1.0.0" and result["recommended"]["requires"] == ">=18"


def test_in_doubt_the_answer_is_no(monkeypatch):
    def down(url):
        raise deps.Unreachable()

    monkeypatch.setattr(deps, "_get", down)
    assert tools._safe(deps.check, "pypi", "pkg")["status"] == "unreachable"
    assert "error" in tools._safe(deps.check, "maven", "pkg")


def test_a_burst_of_fresh_releases_does_not_get_past_the_two_weeks(monkeypatch):
    """Many clean releases in a few days: the newest mature one is recommended, never a fresh one."""
    releases = {f"1.{n}.0": (30 + n, False) for n in range(5)}
    releases.update({f"2.{n}.0": (10 - n * 0.5, False) for n in range(11)})
    pypi(monkeypatch, releases)
    result = deps.check("pypi", "pkg")
    assert result["version"] == "1.4.0" and "note" not in result  # the newest mature one, no 2.x


@pytest.mark.parametrize("url, has_source", [
    ("https://github.com/org/pkg", True), ("git+https://gitlab.com/org/pkg.git", True),
    ("https://git.example.org/org/pkg", True), ("github:org/pkg", True), ("git@github.com:org/pkg.git", True),
    ("https://digit.example/pkg", False), ("https://example.org/github.com", False), ("", False),
])
def test_the_source_check_looks_at_the_host(url, has_source):
    assert (deps._source([url]) is not None) is has_source


def test_a_source_labelled_by_the_package_counts_wherever_it_is_hosted(monkeypatch):
    """openpyxl publishes its code on foss.heptapod.net: a known host is not required, an existing one is."""
    pypi(monkeypatch, {"3.1.5": (800, False)}, source="https://foss.heptapod.net/openpyxl/openpyxl")
    assert deps.check("pypi", "openpyxl")["verdict"] == "allowed"


@pytest.mark.parametrize("exists, expected", [(False, "does not exist"), (None, "could not be reached")])
def test_a_source_repository_that_does_not_answer_blocks(monkeypatch, exists, expected):
    pypi(monkeypatch, {"1.0.0": (100, False)})
    monkeypatch.setattr(deps, "_exists", lambda url: exists)
    result = deps.check("pypi", "pkg")
    assert result["verdict"] == "blocked" and expected in result["reasons"][0]


@pytest.mark.parametrize("url, web", [
    ("git+https://github.com/o/p.git", "https://github.com/o/p"), ("git@gitlab.com:o/p.git", "https://gitlab.com/o/p"),
    ("github:o/p", "https://github.com/o/p"), ("git://code.example.org/p", "https://code.example.org/p"),
    ("http://insecure.example/p", None),
])
def test_repository_addresses_are_turned_into_web_addresses(url, web):
    assert deps._web_address(url) == web


# --- the whole pinned tree -----------------------------------------------------------------------------------

def registry(monkeypatch, packages: dict, vulns: dict | None = None, requires: dict | None = None):
    """packages: name -> {version: days ago}; requires: name -> requires_dist of every version."""
    def get(url):
        parts = url.rstrip("/").split("/")
        if "pypi.org" in url and len(parts) == 7:  # https://pypi.org/pypi/<name>/<version>/json
            return {"info": {"requires_dist": (requires or {}).get(parts[4], [])}}
        name = url.rstrip("/").split("/")[-2] if "pypi.org" in url else url.split("registry.npmjs.org/")[1]
        if name not in packages:
            return None
        if "pypi.org" in url:
            return {"info": {"project_urls": {"Source": f"https://github.com/o/{name}"}, "license": "MIT"},
                    "releases": {v: [{"upload_time_iso_8601": stamp(d), "yanked": False, "digests": {"sha256": "aa"}}]
                                 for v, d in packages[name].items()}}
        return {"time": {v: stamp(d) for v, d in packages[name].items()},
                "repository": "github:o/" + name.split("/")[-1],
                "versions": {v: {} for v in packages[name]}}

    monkeypatch.setattr(deps, "_get", get)
    monkeypatch.setattr(deps, "_vulnerable", lambda queries: {q: (vulns or {}).get(q[1:], []) for q in queries})
    monkeypatch.setattr(deps, "_vulnerabilities", lambda eco, name, version: (vulns or {}).get((name, version), []))


def test_the_audit_checks_every_pinned_package_direct_and_indirect(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}, "starlette": {"1.0.0": 100}, "h11": {"0.16.0": 100}},
             vulns={("h11", "0.16.0"): ["GHSA-h11"]})
    (tmp_path / "requirements.txt").write_text(
        "fastapi==0.1.0 \\\n    --hash=sha256:aa\nstarlette==1.0.0 --hash=sha256:bb\nh11==0.16.0 --hash=sha256:cc\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "requirements.txt").write_text("ignored\n")
    result = deps.audit(tmp_path)
    assert result["files"] == ["requirements.txt"] and result["packages"] == 3 and result["without_hashes"] == []
    assert result["verdict"] == "blocked"
    assert [(b["package"], b["reasons"][0]) for b in result["blocked"]] == [("h11", "known vulnerabilities: GHSA-h11")]


def test_the_audit_refuses_loose_pins_and_notes_missing_hashes(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    (tmp_path / "requirements.txt").write_text("fastapi==0.1.0\nuvicorn>=0.30\n")
    result = deps.audit(tmp_path)
    assert result["not_pinned"] == ["requirements.txt: uvicorn>=0.30"] and result["verdict"] == "blocked"
    assert result["without_hashes"] == ["requirements.txt"]


@pytest.mark.parametrize("line", ["--index-url https://mirror.example/simple", "--extra-index-url https://x.example",
                                  "--find-links ./wheels", "-e ./local", "-r ../elsewhere.txt",
                                  "pkg @ https://example.com/pkg.whl", "git+https://example.com/pkg.git"])
def test_the_audit_refuses_anything_installed_from_elsewhere(monkeypatch, tmp_path, line):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    (tmp_path / "requirements.txt").write_text(f"fastapi==0.1.0\n{line}\n")
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_an_include_of_another_pinned_list_is_accepted(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}, "pytest": {"9.1.1": 100}})
    (tmp_path / "requirements.txt").write_text("fastapi==0.1.0\n")
    (tmp_path / "requirements-dev.txt").write_text("-r requirements.txt\npytest==9.1.1\n")
    result = deps.audit(tmp_path)
    assert result["verdict"] == "allowed" and result["packages"] == 2


def test_a_list_that_pins_nothing_is_not_a_pass(monkeypatch, tmp_path):
    registry(monkeypatch, {})
    (tmp_path / "requirements.txt").write_text("# nothing here\n")
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "pins nothing" in result["not_pinned"][0]


def test_an_old_npm_lockfile_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {})
    (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 1, "dependencies": {"x": {}}}))
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "version 1" in result["not_pinned"][0]


def test_an_npm_entry_from_elsewhere_or_under_another_name_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"lodash": {"4.17.21": 100}})
    (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "node_modules/lodash": {"version": "4.17.21", "name": "evil-pkg",
                                "resolved": "https://evil.example/x.tgz", "integrity": "sha512-x"}}}))
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "not from the public registry" in result["not_pinned"][0]


def test_a_requirement_only_for_windows_must_be_pinned(monkeypatch, tmp_path):
    # a list written on Linux leaves it out, and `pip install --require-hashes` then fails on Windows
    registry(monkeypatch, {"click": {"8.3.0": 100}},
             requires={"click": ["colorama; platform_system == 'Windows'"]})
    (tmp_path / "requirements.txt").write_text("click==8.3.0\n")
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked"
    assert result["not_pinned"] == ["missing from the pinned list: colorama (required by click 8.3.0) when "
                                    "platform_system == 'Windows'"]


@pytest.mark.parametrize("marker, needed", [
    ("platform_system != 'Windows'", True),
    ("sys_platform == 'win32' or python_version < '3.8'", True),
    ("platform_machine == 'x86_64'", True),
    ("sys_platform == 'darwin' and platform_python_implementation == 'CPython'", True),
    ("sys_platform == 'win32' and implementation_name == 'pypy'", False),
    ("python_version < '3.8'", False),
    ("sys_platform == 'emscripten'", False),
    ("not a marker ==", True),  # unreadable: counted as needed
    ("python_version ~= 'abc'", True),  # cannot be evaluated: counted as needed
    ("dependency_groups == 'x'", True),
])
def test_which_markers_a_computer_installs(marker, needed):
    assert deps._needed_on_a_computer(marker) is needed


def test_a_list_compiled_for_a_python_need_not_pin_what_only_older_ones_install(monkeypatch, tmp_path):
    registry(monkeypatch, {"pytest": {"9.1.1": 100}}, requires={"pytest": ["tomli>=1; python_version < '3.11'"]})
    (tmp_path / "requirements.txt").write_text("pytest==9.1.1\n")
    assert deps.audit(tmp_path)["verdict"] == "blocked"  # no header: Python 3.10 counts, and it needs tomli
    (tmp_path / "requirements.txt").write_text(
        "# This file was autogenerated by uv via the following command:\n"
        "#    uv pip compile requirements.in --universal --generate-hashes --python-version 3.12 -o requirements.txt\n"
        "pytest==9.1.1\n")
    result = deps.audit(tmp_path)
    assert result["verdict"] == "allowed"
    assert result["only_on_some_platforms"] == ["tomli (required by pytest 9.1.1) when python_version < '3.11'"]


@pytest.mark.parametrize("pyproject, verdict", [
    ('[project]\nrequires-python = ">=3.12"\n', "allowed"),
    ('[project]\nrequires-python = ">=3.11.4"\n', "allowed"),  # still runs on 3.11, which needs no tomli
    ('[project]\nrequires-python = ">3.11"\n', "allowed"),
    ('[project]\nrequires-python = "~=3.11"\n', "allowed"),
    ('[project]\nrequires-python = "==3.12.*"\n', "allowed"),
    ('[project]\nrequires-python = ">=3.9"\n', "blocked"),
    ('[project]\nrequires-python = ""\n', "blocked"),
    ('[project]\nrequires-python = "not a range"\n', "blocked"),
    ('[project]\nrequires-python = 3.12\n', "blocked"),  # not text: ignored, never a crash
    ('project = "x"\n', "blocked"),
])
def test_a_projects_declared_python_counts_for_its_list(monkeypatch, tmp_path, pyproject, verdict):
    # `uv export` writes no --python-version: the project's own pyproject.toml says which Pythons it runs on
    registry(monkeypatch, {"pytest": {"9.1.1": 100}}, requires={"pytest": ["tomli>=1; python_version < '3.11'"]})
    (tmp_path / "pyproject.toml").write_text(pyproject)
    (tmp_path / "requirements.txt").write_text("# uv export --frozen --no-dev\npytest==9.1.1\n")
    assert deps.audit(tmp_path)["verdict"] == verdict


def test_a_list_that_says_nothing_counts_with_every_supported_python(monkeypatch, tmp_path):
    registry(monkeypatch, {"pytest": {"9.1.1": 100}}, requires={"pytest": ["tomli>=1; python_version < '3.11'"]})
    (tmp_path / "requirements.txt").write_text("#    uv pip compile x.in --python-version 3.12\npytest==9.1.1\n")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "requirements.txt").write_text("pytest==9.1.1\n")  # no header, no pyproject beside it
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_requirements_for_other_platforms_or_pythons_are_listed_apart(monkeypatch, tmp_path):
    registry(monkeypatch, {"click": {"8.3.0": 100}}, requires={"click": [
        "importlib-metadata; python_version < '3.8'", "jsfetch; sys_platform == 'emscripten'"]})
    (tmp_path / "requirements.txt").write_text("click==8.3.0\n")
    result = deps.audit(tmp_path)
    assert result["verdict"] == "allowed"
    assert result["only_on_some_platforms"] == [
        "importlib-metadata (required by click 8.3.0) when python_version < '3.8'",
        "jsfetch (required by click 8.3.0) when sys_platform == 'emscripten'"]


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.5", "localhost"])
def test_the_source_check_never_probes_the_users_network(host):
    assert REAL_EXISTS(f"https://{host}/repo") is None


def test_the_audit_reads_npm_lockfiles(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}, "@scope/tool": {"2.0.0": 5, "1.9.0": 100}})
    (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "app"},
        "node_modules/left-pad": {"version": "1.3.0", "integrity": "sha512-x",
                                  "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz"},
        "node_modules/@scope/tool": {"version": "2.0.0", "integrity": "sha512-y",
                                     "resolved": "https://registry.npmjs.org/@scope/tool/-/tool-2.0.0.tgz"}}}))
    result = deps.audit(tmp_path)
    assert result["packages"] == 2 and result["without_hashes"] == []
    assert [b["package"] for b in result["blocked"]] == ["@scope/tool"]
    assert "two weeks" in result["blocked"][0]["reasons"][0]


PYPI = 'source = { registry = "https://pypi.org/simple" }'
HASHED = 'wheels = [{ url = "https://files.pythonhosted.org/x.whl", hash = "sha256:aa" }]'


def uv_project(folder, *packages, pyproject='[project]\nname = "app"\ndependencies = ["fastapi"]\n'):
    (folder / "pyproject.toml").write_text(pyproject)
    own = '[[package]]\nname = "app"\nversion = "1.0.0"\nsource = { virtual = "." }\n'
    (folder / "uv.lock").write_text("version = 1\nrevision = 5\n\n" + own + "\n".join(packages))


def locked(name, version, source=PYPI, files=HASHED):
    return f'[[package]]\nname = "{name}"\nversion = "{version}"\n{source}\n{files}\n'


def test_the_audit_reads_uv_lockfiles_with_development_packages(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}, "ruff": {"1.0.0": 5, "0.9.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), locked("ruff", "1.0.0"))
    result = deps.audit(tmp_path)
    assert result["files"] == ["uv.lock"] and result["packages"] == 2 and result["without_hashes"] == []
    assert [b["package"] for b in result["blocked"]] == ["ruff"] and result["verdict"] == "blocked"
    assert "two weeks" in result["blocked"][0]["reasons"][0]


def test_an_audited_uv_project_passes(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"))
    assert deps.audit(tmp_path)["verdict"] == "allowed"


@pytest.mark.parametrize("source", [
    'source = { registry = "https://mirror.example/simple" }',
    'source = { git = "https://example.com/pkg.git?rev=abc#abc" }',
    'source = { url = "https://example.com/pkg.whl" }',
    'source = { path = "../pkg.whl" }',
    'source = { directory = "../pkg" }',
    'source = { editable = "../pkg" }',
    'source = { virtual = "../pkg" }',
])
def test_the_audit_refuses_a_uv_package_from_anywhere_else(monkeypatch, tmp_path, source):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}, "other": {"1.0.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), locked("other", "1.0.0", source=source))
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and result["not_pinned"] == ["uv.lock: other (only the public index)"]


def test_a_uv_package_named_like_the_project_is_not_waved_through(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fastapi"\ndependencies = []\n')
    (tmp_path / "uv.lock").write_text("version = 1\n\n" + locked("fastapi", "0.1.0", source='source = { path = "x" }'))
    assert deps.audit(tmp_path)["not_pinned"] == ["uv.lock: fastapi (only the public index)"]


def test_a_uv_lockfile_out_of_date_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), pyproject=(
        '[project]\nname = "app"\ndependencies = ["fastapi>=0.1", "uvicorn[standard]<1"]\n'
        '[project.optional-dependencies]\nextra = ["httpx"]\n'
        '[dependency-groups]\ndev = ["pytest", { include-group = "other" }]\nother = []\n'))
    assert sorted(line.split(": ")[1] for line in deps.audit(tmp_path)["not_pinned"]) == [
        "httpx (in pyproject.toml, not in the lockfile)", "pytest (in pyproject.toml, not in the lockfile)",
        "uvicorn (in pyproject.toml, not in the lockfile)"]


@pytest.mark.parametrize("text", ["not toml", "version = 2\n", '[[package]]\nversion = "1"\n',
                                  'version = 1\n[[package]]\nversion = "1"\n', "version = 1\npackage = 3\n"])
def test_a_uv_lockfile_that_cannot_be_read_is_refused(tmp_path, text):
    (tmp_path / "uv.lock").write_text(text)
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and result["not_pinned"] == ["uv.lock: not readable as a pinned list"]


def test_the_audit_applies_the_same_rules_to_vendored_files(monkeypatch, tmp_path):
    registry(monkeypatch, {"some-library": {"2.0.0": 100}, "other-library": {"1.0.0": 100}},
             vulns={("some-library", "2.0.0"): ["GHSA-lib"]})
    (tmp_path / "vendor.json").write_text(json.dumps({
        "some-library": {"version": "2.0.0", "sha384": "x"},
        "other-library": {"version": "1.0.0"},
        "a-derived-file": {"package": "other-library", "version": "1.0.0"}}))
    result = deps.audit(tmp_path)
    assert result["files"] == ["vendor.json"] and result["packages"] == 2 and result["verdict"] == "blocked"
    assert [(b["ecosystem"], b["package"]) for b in result["blocked"]] == [("npm", "some-library")]


def test_a_vendored_file_that_was_never_published_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"some-library": {"2.0.0": 100}})
    (tmp_path / "vendor.json").write_text(json.dumps({"some-library": {"version": "9.9.9"}}))
    assert "does not exist" in deps.audit(tmp_path)["blocked"][0]["reasons"][0]


@pytest.mark.parametrize("text", ['{"x": {}}', '{"x": {"version": ""}}', '{"x": {"version": 1}}', "{}", "[]",
                                  '{"x": 1}', "not json"])
def test_a_vendor_list_that_says_nothing_certain_is_refused(tmp_path, text):
    (tmp_path / "vendor.json").write_text(text)
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def wheel(url, digest="aa"):
    return f'wheels = [{{ url = "{url}", hash = "sha256:{digest}" }}]'


@pytest.mark.parametrize("files", [
    wheel("http://127.0.0.1:8000/fastapi.whl"),
    wheel("http://files.pythonhosted.org/fastapi.whl"),
    wheel("https://files.pythonhosted.org.evil.example/fastapi.whl"),
    'sdist = { url = "https://evil.example/fastapi.tar.gz", hash = "sha256:aa" }',
    'sdist = { path = "fastapi.tar.gz", hash = "sha256:aa" }',
])
def test_a_uv_file_downloaded_from_anywhere_else_is_refused(monkeypatch, tmp_path, files):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0", files=files))
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and result["not_pinned"] == ["uv.lock: fastapi (only the public index)"]


@pytest.mark.parametrize("source", ['source = { registry = "https://pypi.org/simple", git = "https://evil.example" }',
                                    "source = {}"])
def test_a_uv_source_that_is_not_only_the_public_index_is_refused(monkeypatch, tmp_path, source):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0", source=source))
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_the_public_index_may_end_in_a_slash(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0", source='source = { registry = "https://pypi.org/simple/" }'))
    assert deps.audit(tmp_path)["verdict"] == "allowed"


def test_a_uv_package_without_a_version_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, f'[[package]]\nname = "fastapi"\n{PYPI}\n{HASHED}\n')
    assert deps.audit(tmp_path)["not_pinned"] == ["uv.lock: fastapi (only the public index)"]


def test_a_uv_project_built_in_place_is_not_a_pin(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = ["fastapi"]\n')
    (tmp_path / "uv.lock").write_text('version = 1\n\n[[package]]\nname = "app"\nversion = "1"\n'
                                      'source = { editable = "." }\n\n' + locked("fastapi", "0.1.0"))
    result = deps.audit(tmp_path)
    assert result["verdict"] == "allowed" and result["packages"] == 1


def test_a_uv_project_with_no_packages_passes(tmp_path):
    uv_project(tmp_path, pyproject='[project]\nname = "app"\ndependencies = []\n')
    result = deps.audit(tmp_path)
    assert result["verdict"] == "allowed" and result["without_hashes"] == []


def test_a_project_requiring_itself_is_not_out_of_date(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), pyproject=(
        '[project]\nname = "app"\ndependencies = ["fastapi"]\n[dependency-groups]\ndev = ["app[extra]>=9"]\n'))
    assert deps.audit(tmp_path)["verdict"] == "allowed"


def test_names_are_compared_as_pypi_compares_them(monkeypatch, tmp_path):
    registry(monkeypatch, {"my-pkg": {"1.0.0": 100}})
    uv_project(tmp_path, locked("My_Pkg", "1.0.0"), pyproject=(
        '[project]\nname = "My.App"\ndependencies = ["MY.PKG"]\n'))
    (tmp_path / "uv.lock").write_text((tmp_path / "uv.lock").read_text().replace('name = "app"', 'name = "my-app"'))
    assert deps.audit(tmp_path)["verdict"] == "allowed"


def test_a_marker_on_the_project_takes_nothing_out_of_the_audit(monkeypatch, tmp_path):
    registry(monkeypatch, {"evil": {"1.0.0": 100}}, vulns={("evil", "1.0.0"): ["GHSA-evil"]})
    lock = locked("evil", "1.0.0")
    uv_project(tmp_path, lock, pyproject='[project]\nname = "app"\ndependencies = ["evil"]\n')
    text = (tmp_path / "uv.lock").read_text().replace(
        'source = { virtual = "." }\n', 'source = { virtual = "." }\n'
        'dependencies = [{ name = "evil", marker = "sys_platform == \'emscripten\'" }]\n')
    (tmp_path / "uv.lock").write_text(text)
    assert [b["package"] for b in deps.audit(tmp_path)["blocked"]] == ["evil"]


def test_a_uv_package_only_a_browser_installs_is_audited_all_the_same(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), locked("web", "1.0"))
    assert [b["package"] for b in deps.audit(tmp_path)["blocked"]] == ["web"]


def test_a_uv_lockfile_is_complete_so_nothing_is_reported_missing_from_it(monkeypatch, tmp_path):
    """uv leaves out what no path reaches: keyring only off Windows, and what keyring needs only on Windows."""
    registry(monkeypatch, {"keyring": {"1.0.0": 100}},
             requires={"keyring": ['pywin32-ctypes; sys_platform == "win32"']})
    uv_project(tmp_path, locked("keyring", "1.0.0"), pyproject='[project]\nname = "app"\ndependencies = ["keyring"]\n')
    assert deps.audit(tmp_path)["verdict"] == "allowed"


@pytest.mark.parametrize("pyproject", [
    '[project]\nname = "app"\ndependencies = ["fastapi @ https://evil.example/f.whl"]\n',
    '[project]\nname = "app"\ndependencies = ["fastapi"]\n[tool.uv.sources]\nfastapi = { git = "https://x.example" }\n',
    '[project]\nname = "app"\ndependencies = ["fastapi"]\n[[tool.uv.index]]\nurl = "https://x.example"\n',
    '[project]\nname = "app"\ndependencies = ["fastapi"]\n[tool.uv]\nindex-url = "https://x.example"\n',
    '[project]\nname = "app"\ndependencies = ["fastapi"]\n[tool.uv]\nextra-index-url = ["https://x.example"]\n',
    '[project]\nname = "app"\ndependencies = ["fastapi"]\n[tool.uv]\nfind-links = ["./wheels"]\n',
    '[project]\nname = "app"\ndependencies = ["fastapi>=2"]\n',
    '[project]\nname = "app"\ndependencies = ["fastapi", "evil"]\n',
    '[project]\nname = "app"\ndependencies = ["fastapi"]\n[tool.uv]\ndev-dependencies = ["evil"]\n',
])
def test_a_pyproject_the_lockfile_no_longer_answers_is_refused(monkeypatch, tmp_path, pyproject):
    """A plain `uv sync` would write a new lockfile and install what the audit never saw."""
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), pyproject=pyproject)
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_what_no_python_here_needs_may_be_out_of_the_lockfile(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), pyproject=(
        '[project]\nname = "app"\nrequires-python = ">=3.12"\n'
        'dependencies = ["fastapi", "tomli; python_version < \'3.11\'"]\n'))
    assert deps.audit(tmp_path)["verdict"] == "allowed"


def test_a_lockfile_with_a_name_in_capitals_is_read(tmp_path):
    (tmp_path / "UV.LOCK").write_text("version = 2\n")
    assert deps.audit(tmp_path)["not_pinned"] == ["UV.LOCK: not readable as a pinned list"]


@pytest.mark.parametrize("name", ["moment#", "moment?a=1", "moment/", "moment\n", "@babel%2ftraverse", "../moment",
                                  "a b", ""])
def test_a_vendored_name_npm_could_not_publish_is_refused(monkeypatch, tmp_path, name):
    """OSV would receive it literally and find nothing, while the address still reaches the real package."""
    registry(monkeypatch, {"moment": {"2.0.0": 100}})
    (tmp_path / "vendor.json").write_text(json.dumps({"x": {"package": name, "version": "2.0.0", "sha384": "x"}}))
    assert deps.audit(tmp_path)["not_pinned"] == ["vendor.json: x (a vendored file names its package and version)"]


def test_a_scoped_vendored_name_is_read(monkeypatch, tmp_path):
    registry(monkeypatch, {"@scope/tool": {"2.0.0": 100}})
    (tmp_path / "vendor.json").write_text(json.dumps({"@scope/tool": {"version": "2.0.0", "sha384": "x"}}))
    assert deps.audit(tmp_path)["verdict"] == "allowed"


@pytest.mark.parametrize("url", ["http://github.com/o/x.js", "https://evil.example/x.js", "ftp://github.com/x", 5,
                                 "https://github.com.evil.example/x.js", "https://evil.example\\@github.com/x.js"])
def test_a_vendored_file_from_anywhere_else_is_refused(monkeypatch, tmp_path, url):
    registry(monkeypatch, {"some-library": {"2.0.0": 100}})
    (tmp_path / "vendor.json").write_text(json.dumps({"some-library": {"version": "2.0.0", "url": url}}))
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_a_vendored_file_from_a_release_passes_and_a_schema_is_not_an_entry(monkeypatch, tmp_path):
    registry(monkeypatch, {"some-library": {"2.0.0": 100}})
    (tmp_path / "vendor.json").write_text(json.dumps({"$schema": "x", "some-library": {
        "version": "2.0.0", "sha384": "x", "url": "https://github.com/o/x/releases/download/v{version}/x.js"}}))
    result = deps.audit(tmp_path)
    assert result["verdict"] == "allowed" and result["packages"] == 1 and result["without_hashes"] == []


def test_a_vendored_file_without_a_hash_is_noted(monkeypatch, tmp_path):
    registry(monkeypatch, {"some-library": {"2.0.0": 100}})
    (tmp_path / "vendor.json").write_text(json.dumps({"some-library": {"version": "2.0.0"}}))
    assert deps.audit(tmp_path)["without_hashes"] == ["vendor.json"]


@pytest.mark.parametrize("manifest, text", [
    ("pyproject.toml", '[project]\nname = "app"\ndependencies = ["evil"]\n'),
    ("package.json", '{"dependencies": {"evil": "1.0.0"}}'),
])
def test_vendored_files_do_not_hide_packages_left_unpinned(monkeypatch, tmp_path, manifest, text):
    registry(monkeypatch, {"clean": {"1.0.0": 100}})
    (tmp_path / manifest).write_text(text)
    (tmp_path / "vendor.json").write_text(json.dumps({"clean": {"version": "1.0.0", "sha384": "x"}}))
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "not pinned" in result["reasons"][0]


@pytest.mark.parametrize("text", [
    '[project]\nname = "app"\n[dependency-groups]\ndev = ["evil"]\n',
    '[project]\nname = "app"\n[project.optional-dependencies]\nextra = ["evil"]\n',
    '[project]\nname = "app"\n[tool.uv]\ndev-dependencies = ["evil"]\n',
])
def test_packages_declared_only_for_development_or_an_extra_must_be_pinned(tmp_path, text):
    (tmp_path / "pyproject.toml").write_text(text)
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_input_nested_too_deeply_is_refused_without_stopping(tmp_path):
    (tmp_path / "vendor.json").write_text("[" * 200000)
    assert deps.audit(tmp_path)["not_pinned"] == ["vendor.json: not readable as a pinned list"]


def pypi_links(monkeypatch, links):
    releases = {"1.0.0": [{"upload_time_iso_8601": stamp(100), "yanked": False}]}
    monkeypatch.setattr(deps, "_get", lambda url: {"releases": releases, "info": {"project_urls": links}})


@pytest.mark.parametrize("links, source", [
    ({"Changelog": "https://github.com/o/x/release-notes.md", "Repository": "https://github.com/o/x"},
     "https://github.com/o/x"),
    ({"Changelog": "https://github.com/o/x/CHANGES.md", "Source": "https://code.example.org/o/x"},
     "https://code.example.org/o/x"),
    ({"Homepage": "https://github.com/o/x", "Source": "http://github.com/o/x"}, "https://github.com/o/x"),
    ({"Homepage": "https://github.com/o/x"}, "https://github.com/o/x"),
])
def test_the_source_is_what_the_package_labels_as_its_code(monkeypatch, links, source):
    pypi_links(monkeypatch, links)
    assert deps._pypi("x")["source"] == source


def test_an_old_npm_version_listing_engines_as_a_list_is_read(monkeypatch):
    monkeypatch.setattr(deps, "_get", lambda url: {"time": {"1.0.0": stamp(100)}, "repository": "github:o/x",
                                                   "versions": {"1.0.0": {"engines": ["node >= 0.8"]}}})
    assert deps._npm("x")["releases"]["1.0.0"]["requires"] is None


@pytest.mark.parametrize("source, files", [
    ('source = { registry = "https://evil.example/simple", virtual = "." }', wheel("https://evil.example/app.whl")),
    ('source = { url = "https://evil.example/app.whl", virtual = "." }', ""),
    ('source = { virtual = "." }', wheel("https://evil.example/app.whl")),
])
def test_the_project_itself_is_only_skipped_when_it_comes_from_nowhere(monkeypatch, tmp_path, source, files):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = ["fastapi"]\n')
    (tmp_path / "uv.lock").write_text("version = 1\n\n" + locked("app", "1.0.0", source=source, files=files) + "\n"
                                      + locked("fastapi", "0.1.0"))
    assert deps.audit(tmp_path)["not_pinned"] == ["uv.lock: app (only the public index)"]


def test_a_file_the_registry_did_not_publish_for_that_version_is_refused(monkeypatch, tmp_path):
    """Anyone can upload to the public index, so a good address may hold another package's wheel."""
    registry(monkeypatch, {"iniconfig": {"2.1.0": 100}})
    other = 'wheels = [{ url = "https://files.pythonhosted.org/tomli-2.1.0-py3-none-any.whl", hash = "sha256:bb" }]'
    uv_project(tmp_path, locked("iniconfig", "2.1.0", files=other), pyproject=(
        '[project]\nname = "app"\ndependencies = ["iniconfig"]\n'))
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "not one the registry published" in result["blocked"][0]["reasons"][0]


def test_an_exception_from_it_does_not_lift_the_published_files(monkeypatch, tmp_path):
    registry(monkeypatch, {"iniconfig": {"2.1.0": 100}})
    monkeypatch.setattr(deps, "_excepted", lambda ecosystem, name: True)
    uv_project(tmp_path, locked("iniconfig", "2.1.0", files=wheel("https://files.pythonhosted.org/x.whl", "bb")),
               pyproject='[project]\nname = "app"\ndependencies = ["iniconfig"]\n')
    assert deps.audit(tmp_path)["verdict"] == "blocked"


@pytest.mark.parametrize("url", [
    "https://evil.example:8443\\\\@files.pythonhosted.org/fastapi.whl",
    "https://files.pythonhosted.org/fastapi.whl?/x.whl",
    "https://files.pythonhosted.org/fastapi.whl#/x.whl",
])
def test_an_address_two_parsers_could_read_differently_is_refused(monkeypatch, tmp_path, url):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0", files=wheel(url)))
    assert deps.audit(tmp_path)["not_pinned"] == ["uv.lock: fastapi (only the public index)"]


@pytest.mark.parametrize("files", ["", 'wheels = [{ url = "https://files.pythonhosted.org/x.whl" }]'])
def test_a_uv_package_without_files_or_hashes_is_refused(monkeypatch, tmp_path, files):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0", files=files))
    assert deps.audit(tmp_path)["not_pinned"] == ["uv.lock: fastapi (only the public index)"]


@pytest.mark.parametrize("lock", ["version = 1\n", 'version = 1\n[[package]]\nname = "app"\nversion = "1"\n'
                                                   'source = { virtual = "." }\n'])
@pytest.mark.parametrize("manifest, text", [("package.json", '{"dependencies": {"evil": "1.0.0"}}'),
                                            ("requirements.in", "evil\n"), ("poetry.lock", "")])
def test_an_empty_lockfile_does_not_hide_packages_left_unpinned(tmp_path, lock, manifest, text):
    (tmp_path / "uv.lock").write_text(lock)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')
    (tmp_path / manifest).write_text(text)
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "not pinned" in result["reasons"][0]


@pytest.mark.parametrize("setting", [
    '[tool.uv]\noverride-dependencies = ["fastapi @ https://x.example/f.whl"]\n',
    '[tool.uv]\nconstraint-dependencies = ["fastapi @ https://x.example/f.whl"]\n',
    '[tool.uv.pip]\nindex-url = "https://x.example"\n',
    '[tool.uv]\nsome-setting-not-yet-invented = true\n',
])
def test_a_uv_setting_the_audit_does_not_know_is_refused(monkeypatch, tmp_path, setting):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), pyproject=(
        '[project]\nname = "app"\ndependencies = ["fastapi"]\n' + setting))
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_settings_that_do_not_change_the_packages_are_accepted(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), pyproject=(
        '[project]\nname = "app"\ndependencies = ["fastapi"]\n'
        '[tool.uv]\nexclude-newer = "14 days"\ncache-keys = []\npackage = false\n'))
    assert deps.audit(tmp_path)["verdict"] == "allowed"


def test_a_uv_toml_beside_a_lockfile_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"))
    (tmp_path / "uv.toml").write_text('index-url = "https://x.example"\n')
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_a_requirement_for_a_python_nobody_runs_says_nothing_about_the_lockfile(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"2.0.0": 100}})
    uv_project(tmp_path, locked("fastapi", "2.0.0"), pyproject=(
        '[project]\nname = "app"\nrequires-python = ">=3.12"\n'
        'dependencies = ["fastapi<2; python_version<\'3.12\'", "fastapi>=2; python_version>=\'3.12\'"]\n'))
    text = (tmp_path / "uv.lock").read_text().replace("revision = 5\n", 'revision = 5\nrequires-python = ">=3.12"\n')
    (tmp_path / "uv.lock").write_text(text)
    assert deps.audit(tmp_path)["verdict"] == "allowed"


def test_the_python_of_a_lockfile_is_its_own(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), pyproject=(
        '[project]\nname = "app"\ndependencies = ["fastapi", "tomli; python_version < \'3.11\'"]\n'))
    text = (tmp_path / "uv.lock").read_text().replace("revision = 5\n", 'revision = 5\nrequires-python = ">=3.13"\n')
    (tmp_path / "uv.lock").write_text(text)
    assert deps.audit(tmp_path)["verdict"] == "allowed"


def test_a_requirement_with_a_marker_a_computer_needs_must_be_in_the_lockfile(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    uv_project(tmp_path, locked("fastapi", "0.1.0"), pyproject=(
        '[project]\nname = "app"\ndependencies = ["fastapi", "evil; sys_platform == \'win32\'"]\n'))
    assert deps.audit(tmp_path)["not_pinned"] == ["uv.lock: evil (in pyproject.toml, not in the lockfile)"]


@pytest.mark.parametrize("table", ["distribution", "something-newer"])
def test_a_uv_lockfile_with_a_table_the_audit_does_not_read_is_refused(tmp_path, table):
    """uv still reads `distribution` as an older name for `package`, so such a lockfile installs what is not seen."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')
    (tmp_path / "uv.lock").write_text(f'version = 1\n\n[[{table}]]\nname = "evil"\nversion = "1.0.0"\n')
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and result["not_pinned"] == ["uv.lock: not readable as a pinned list"]


def test_a_real_lockfile_has_no_table_the_audit_refuses():
    fields = tomllib.loads((Path(__file__).parents[1] / "uv.lock").read_text(encoding="utf-8"))
    assert set(fields) <= deps._UV_LOCK_FIELDS


@pytest.mark.parametrize("name", ["uv.lock", "requirements.txt", "vendor.json"])
def test_a_pinned_list_that_is_a_link_is_refused(monkeypatch, tmp_path, name):
    (tmp_path / name).write_text("version = 1\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')
    monkeypatch.setattr(deps.Path, "is_symlink", lambda path: path.name == name)  # not every account can create one
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and result["not_pinned"] == [f"{name}: a link, not a pinned list"]


def test_a_dollar_does_not_hide_a_vendored_file(monkeypatch, tmp_path):
    registry(monkeypatch, {"evil": {"1.0.0": 100}}, vulns={("evil", "1.0.0"): ["GHSA-evil"]})
    (tmp_path / "vendor.json").write_text(json.dumps({"$moment": {"package": "evil", "version": "1.0.0"}}))
    assert [b["package"] for b in deps.audit(tmp_path)["blocked"]] == ["evil"]


def test_an_empty_hash_is_no_hash(monkeypatch, tmp_path):
    registry(monkeypatch, {"some-library": {"2.0.0": 100}})
    (tmp_path / "vendor.json").write_text(json.dumps({"some-library": {"version": "2.0.0", "sha384": ""}}))
    assert deps.audit(tmp_path)["without_hashes"] == ["vendor.json"]


def test_a_vendored_tool_with_several_files_counts_as_hashed(monkeypatch, tmp_path):
    registry(monkeypatch, {"some-tool": {"2.0.0": 100}})
    (tmp_path / "vendor.json").write_text(json.dumps({"some-tool": {"version": "2.0.0", "executables": {"a": "x"}}}))
    assert deps.audit(tmp_path)["without_hashes"] == []


def test_a_malformed_link_beside_the_repository_changes_nothing(monkeypatch):
    pypi_links(monkeypatch, {"Source": "https://github.com/o/x", "Docs": "https://[bad"})
    assert deps._pypi("x")["source"] == "https://github.com/o/x"


@pytest.mark.parametrize("manifest, text", [("PYPROJECT.TOML", '[project]\nname = "a"\ndependencies = ["evil"]\n'),
                                            ("Package.json", '{"dependencies": {"evil": "1.0.0"}}'),
                                            ("pyproject.toml", '[project]\nname = "a"\ndynamic = ["dependencies"]\n')])
def test_packages_declared_in_any_case_or_dynamically_must_be_pinned(tmp_path, manifest, text):
    (tmp_path / manifest).write_text(text)
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_a_project_without_packages_has_nothing_to_audit(tmp_path):
    (tmp_path / "index.html").write_text("<p>Hello</p>")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')
    result = deps.audit(tmp_path)
    assert result["verdict"] == "allowed" and "nothing to check" in result["note"]


@pytest.mark.parametrize("manifest, text", [
    ("pyproject.toml", '[project]\nname = "app"\ndependencies = ["fastapi"]\n'),
    ("package.json", '{"dependencies": {"left-pad": "^1.3.0"}}'),
    ("requirements.in", "fastapi\n"),
])
def test_declared_packages_without_a_pinned_list_are_blocked(tmp_path, manifest, text):
    (tmp_path / manifest).write_text(text)
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "not pinned" in result["reasons"][0]


def test_settings_carry_the_organization_and_project_context(monkeypatch):
    configure(monkeypatch, organization_context="We make power supplies.",
              organization_skills=[{"skill": "brand:web", "use_for": "web pages"}])
    result = tools._specialist_settings("")
    assert result["organization"] == {"context": "We make power supplies.",
                                      "skills": [{"skill": "brand:web", "use_for": "web pages"}]}


def test_the_audit_finds_indirect_dependencies_left_out_of_the_list(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}, "starlette": {"1.0.0": 100}},
             requires={"fastapi": ["starlette>=1", "pydantic>=2", "uvicorn; extra == 'standard'"],
                       "starlette": ["anyio>=4", "colorama; sys_platform == 'win32'"]})
    (tmp_path / "requirements.txt").write_text("fastapi==0.1.0\nstarlette==1.0.0\n")
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked"
    assert result["not_pinned"] == ["missing from the pinned list: anyio (required by starlette 1.0.0)",
                                    "missing from the pinned list: colorama (required by starlette 1.0.0) when "
                                    "sys_platform == 'win32'",
                                    "missing from the pinned list: pydantic (required by fastapi 0.1.0)"]


def test_pins_only_other_platforms_install_are_listed_apart(monkeypatch, tmp_path):
    registry(monkeypatch, {"httpx2": {"2.13.1": 100}})
    (tmp_path / "requirements.txt").write_text(
        "httpx2==2.13.1 --hash=sha256:aa\n"
        "httpx2-jsfetch==1.0 ; sys_platform == 'emscripten' --hash=sha256:bb\n"
        "pywin32-ctypes==0.2.3 ; sys_platform == 'win32' --hash=sha256:cc\n")
    result = deps.audit(tmp_path)
    assert result["not_installed_on_computers"] == ["requirements.txt: httpx2-jsfetch==1.0 (only on emscripten)"]
    assert any(b["package"] == "pywin32-ctypes" for b in result["blocked"])  # a Windows pin is still audited


# --- ways around the audit, found by an independent review ---------------------------------------------------------

def tree(folder, files: dict):
    for path, text in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_text(text, newline="\n")


LEFT_PAD = {"version": "1.3.0", "integrity": "sha512-x",
            "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz"}


def npm_lock(root: dict, **packages) -> str:
    return json.dumps({"lockfileVersion": 3, "packages": {"": root, "node_modules/left-pad": LEFT_PAD, **packages}})


def test_a_package_json_that_asks_for_what_its_lockfile_omits_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    tree(tmp_path, {"package.json": json.dumps({"dependencies": {"evil": "*"}, "scripts": {"postinstall": "node x.js"}}),
                    "package-lock.json": npm_lock({"name": "x"})})
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "package.json" in result["not_pinned"][0]


def test_a_lockfile_root_that_lists_a_package_it_does_not_hold_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    declared = {"dependencies": {"evil": "*", "left-pad": "1.3.0"}}
    tree(tmp_path, {"package.json": json.dumps(declared), "package-lock.json": npm_lock({"name": "x", **declared})})
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_a_package_json_its_lockfile_answers_passes(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    declared = {"dependencies": {"left-pad": "1.3.0"}, "peerDependencies": {"left-pad": "*"}}
    tree(tmp_path, {"package.json": json.dumps({"name": "x", **declared}),
                    "package-lock.json": npm_lock({"name": "x", **declared})})
    assert deps.audit(tmp_path)["verdict"] == "allowed"


@pytest.mark.parametrize("entry", [{"resolved": "https://evil.example/e.tgz", "integrity": "sha512-x"},
                                   {"link": True, "resolved": "../evil", "version": "1.0.0"},
                                   {"link": True, "resolved": "packages/evil"}])
def test_an_npm_entry_with_no_version_or_a_link_is_refused_not_skipped(monkeypatch, tmp_path, entry):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    tree(tmp_path, {"package-lock.json": json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "x"}, "node_modules/left-pad": LEFT_PAD, "node_modules/evil": entry}})})
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "node_modules/evil" in result["not_pinned"][0]


@pytest.mark.parametrize("field", ["peerDependencies", "optionalDependencies"])
def test_packages_declared_as_peers_or_optional_must_be_pinned(tmp_path, field):
    tree(tmp_path, {"package.json": json.dumps({field: {"evil": "*"}})})
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_a_pyproject_that_asks_for_what_the_list_beside_it_omits_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    tree(tmp_path, {"requirements.txt": "left-pad==1.3.0 --hash=sha256:ab\n",
                    "pyproject.toml": '[project]\nname = "x"\nversion = "1"\ndependencies = ["evil"]\n'})
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "evil (in pyproject.toml" in result["not_pinned"][0]


def test_a_pyproject_the_list_beside_it_answers_passes(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    tree(tmp_path, {"requirements.txt": "left-pad==1.3.0 --hash=sha256:ab\n",
                    "pyproject.toml": '[project]\nname = "x"\nversion = "1"\nrequires-python = ">=3.12"\ndependencies = '
                                      '["Left_Pad>=1", "tomli; python_version < \'3.11\'", "x[extra]"]\n'})
    assert deps.audit(tmp_path)["verdict"] == "allowed"


@pytest.mark.parametrize("manifest, text", [
    ("services/api/pyproject.toml", '[project]\nname = "x"\nversion = "1"\ndependencies = ["evil"]\n'),
    ("services/api/package.json", '{"dependencies": {"evil": "*"}}'),
    ("services/web/requirements.in", "evil\n"),
])
def test_a_project_in_a_subfolder_needs_a_list_of_its_own(monkeypatch, tmp_path, manifest, text):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    tree(tmp_path, {"requirements.txt": "left-pad==1.3.0 --hash=sha256:ab\n", manifest: text})
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and manifest in result["reasons"][0]


def test_a_list_for_another_ecosystem_does_not_answer_for_a_manifest(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    tree(tmp_path, {"requirements.txt": "left-pad==1.3.0\n", "package.json": '{"dependencies": {"evil": "*"}}'})
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_a_folder_called_archive_is_read_like_any_other(tmp_path):
    tree(tmp_path, {"archive/requirements.txt": "evil>=1\n"})
    assert deps.audit(tmp_path)["verdict"] == "blocked"


def test_lists_in_a_requirements_folder_are_read(monkeypatch, tmp_path):
    registry(monkeypatch, {"evil": {"6.6.6": 100}}, vulns={("evil", "6.6.6"): ["GHSA-x"]})
    tree(tmp_path, {"requirements/base.txt": "evil==6.6.6\n"})
    result = deps.audit(tmp_path)
    assert result["files"] == ["requirements/base.txt"] and [b["package"] for b in result["blocked"]] == ["evil"]


def test_a_requirements_folder_answers_for_the_project_above_it(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}})
    tree(tmp_path, {"requirements/base.txt": "left-pad==1.3.0\n",
                    "pyproject.toml": '[project]\nname = "x"\nversion = "1"\ndependencies = ["left-pad"]\n'})
    assert deps.audit(tmp_path)["verdict"] == "allowed"


@pytest.mark.parametrize("name", ["app.py.lock", "tools/run.py.lock", "Gemfile.lock", "composer.lock", "x.LOCK"])
def test_a_lockfile_the_audit_does_not_read_is_refused(tmp_path, name):
    """`uv run script.py` honours a `script.py.lock` beside it: it installs what no audit saw."""
    tree(tmp_path, {name: "version = 1\n"})
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "a lockfile the audit does not read" in result["not_pinned"][0]


def test_a_wheel_with_a_local_path_beside_its_address_is_refused(monkeypatch, tmp_path):
    registry(monkeypatch, {"fastapi": {"0.1.0": 100}})
    files = 'wheels = [{ url = "https://files.pythonhosted.org/x.whl", path = "../../x.whl", hash = "sha256:aa" }]'
    uv_project(tmp_path, locked("fastapi", "0.1.0", files=files))
    assert deps.audit(tmp_path)["not_pinned"] == ["uv.lock: fastapi (only the public index)"]
