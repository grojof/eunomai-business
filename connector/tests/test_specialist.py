"""The specialist's settings and the dependency check, with registry and OSV answers simulated."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from eunomai_business import deps, server as tools, settings


@pytest.fixture(autouse=True)
def source_repositories_exist(monkeypatch):
    monkeypatch.setattr(deps, "_exists", lambda url: True)


def configure(monkeypatch, **values):
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps(values))


# --- settings ------------------------------------------------------------------------------------------------

def test_defaults_deny_free_development(monkeypatch):
    monkeypatch.delenv("EUNOMAI_SPECIALIST", raising=False)
    assert settings.load()["docs_language"] == "en" and settings.load()["code_language"] == "en"
    assert settings.development("https://git.example.test/team/app")["code_allowed"] is False


def test_code_language_follows_the_docs_language(monkeypatch):
    configure(monkeypatch, docs_language="es")
    assert settings.load()["code_language"] == "es"


def test_a_configured_project_allows_its_technologies(monkeypatch):
    configure(monkeypatch, projects={"https://git.example.test/team/app": {"technologies": ["Python"]}})
    allowed = settings.development("https://git.example.test/team/App.git")
    assert allowed["code_allowed"] and allowed["technologies"] == ["Python"]
    assert settings.development("https://git.example.test/team/other")["code_allowed"] is False


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
                    "releases": {v: [{"upload_time_iso_8601": stamp(d), "yanked": False}]
                                 for v, d in packages[name].items()}}
        return {"time": {v: stamp(d) for v, d in packages[name].items()}, "repository": "github:o/" + name.split("/")[-1],
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
    (tmp_path / "requirements.txt").write_text("fastapi==0.1.0\nuvicorn>=0.30\n-r other.txt\n")
    result = deps.audit(tmp_path)
    assert result["not_pinned"] == ["requirements.txt: uvicorn>=0.30"] and result["verdict"] == "blocked"
    assert result["without_hashes"] == ["requirements.txt"]


def test_the_audit_reads_npm_lockfiles(monkeypatch, tmp_path):
    registry(monkeypatch, {"left-pad": {"1.3.0": 100}, "@scope/tool": {"2.0.0": 5, "1.9.0": 100}})
    (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "app"},
        "node_modules/left-pad": {"version": "1.3.0", "integrity": "sha512-x"},
        "node_modules/@scope/tool": {"version": "2.0.0", "integrity": "sha512-y"}}}))
    result = deps.audit(tmp_path)
    assert result["packages"] == 2 and result["without_hashes"] == []
    assert [b["package"] for b in result["blocked"]] == ["@scope/tool"]
    assert "two weeks" in result["blocked"][0]["reasons"][0]


def test_the_audit_without_pinned_files_is_blocked(tmp_path):
    result = deps.audit(tmp_path)
    assert result["verdict"] == "blocked" and "no pinned list" in result["reasons"][0]


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
                                    "missing from the pinned list: pydantic (required by fastapi 0.1.0)"]
