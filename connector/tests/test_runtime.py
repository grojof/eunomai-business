"""The uv that runs the connector: too old for IT's minimum is said, a known vulnerability blocks the audit."""

import json
import sys

import pytest

from eunomai_business import deps, runtime, server
from eunomai_business.support import Unreachable


@pytest.fixture
def uv(monkeypatch):
    """A uv of the version a test names, with the advisories it names, and IT's minimum."""
    seen = {}

    def use(version, advisories=(), minimum=""):
        monkeypatch.setattr(runtime, "uv_version", lambda: version)
        runtime._vulnerabilities.cache_clear()

        def osv(ecosystem, name, asked):
            seen["asked"] = (ecosystem, name, asked)
            if advisories == "unreachable":
                raise Unreachable("api.osv.dev")
            return list(advisories)

        monkeypatch.setattr(deps, "_vulnerabilities", osv)
        monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"uv_minimum": minimum}))
        return seen

    yield use
    runtime._vulnerabilities.cache_clear()


def test_a_current_uv_raises_nothing(uv):
    seen = uv("0.13.5", minimum="0.13.5")
    assert runtime.problem() is None and runtime.vulnerable_uv() is None
    assert seen["asked"] == ("pypi", "uv", "0.13.5"), "OSV knows uv by its PyPI name"


def test_an_older_uv_than_it_validated_is_said_and_nothing_stops(uv):
    uv("0.13.4", minimum="0.13.5")
    found = runtime.problem()
    assert "older than the version IT validated (0.13.5)" in found["user_message"]
    assert "uv 0.13.4 is older than 0.13.5" in found["it_report"]
    assert runtime.vulnerable_uv() is None


def test_a_uv_with_an_advisory_is_said_and_blocks_the_audit(uv, tmp_path):
    uv("0.9.7", advisories=["GHSA-hq85-5cpj-mr62"])
    found = runtime.problem()
    assert "known security problem" in found["user_message"] and "GHSA-hq85-5cpj-mr62" in found["it_report"]
    result = deps.audit(tmp_path)  # a project that installs nothing is still not allowed
    assert result["verdict"] == "blocked"
    assert result["blocked"] == [{"ecosystem": "pypi", "package": "uv", "version": "0.9.7",
                                  "files": ["the uv that runs the connector on this computer"],
                                  "reasons": ["known vulnerabilities: GHSA-hq85-5cpj-mr62"]}]


def test_osv_out_of_reach_is_not_a_problem_with_uv_but_the_audit_says_it(uv, tmp_path):
    uv("0.13.5", advisories="unreachable")
    assert runtime.problem() is None
    with pytest.raises(Unreachable):
        deps.audit(tmp_path)


def test_a_uv_that_cannot_be_told_raises_nothing(uv):
    uv(None)
    assert runtime.problem() is None and runtime.vulnerable_uv() is None


def test_whoami_carries_what_is_wrong_with_uv(uv, monkeypatch):
    uv("0.13.4", minimum="0.13.5")
    monkeypatch.setattr(server.auth, "whoami", lambda provider: {"provider": provider, "signed_in": False})
    answer = server.whoami("git")
    assert answer["signed_in"] is False and "older than" in answer["uv_problem"]["user_message"]
    uv("0.13.5", minimum="0.13.5")
    assert "uv_problem" not in server.whoami("git")


def test_the_version_is_read_from_the_uv_that_names_itself(monkeypatch, tmp_path):
    fake = tmp_path / "uv.py"
    fake.write_text("print('uv 0.13.5 (46776a95d 2026-10-21 x86_64-pc-windows-msvc)')", encoding="utf-8")
    script = tmp_path / ("uv.cmd" if sys.platform == "win32" else "uv")
    if sys.platform == "win32":
        script.write_text(f'@"{sys.executable}" "{fake}"\n', encoding="utf-8")
    else:
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}"\n', encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.undo()  # the conftest's stand-in goes; this test reads a real program
    monkeypatch.setenv("UV", str(script))
    runtime.uv_version.cache_clear()
    try:
        assert runtime.uv_version() == "0.13.5"
    finally:
        runtime.uv_version.cache_clear()
