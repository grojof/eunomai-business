"""The specialist's settings and the dependency check, with registry and OSV answers simulated."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from eunomai_business import deps, server as tools, settings


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
