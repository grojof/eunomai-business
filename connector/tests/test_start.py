"""connector/start.py: the connector's environment outside the plugin's folder, so Windows lets the folder go."""

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

CONNECTOR = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("start", CONNECTOR / "start.py")
start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(start)
WEEK = 7 * 24 * 3600


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path / "acme-apps" / "environments"


def test_the_environment_is_in_the_plugins_data_folder_not_in_the_plugin(data):
    folder = start.environment("acme-apps")
    assert folder.parent == data
    assert CONNECTOR not in folder.parents


def test_another_connector_folder_or_other_packages_get_another_environment(data, tmp_path):
    copy = tmp_path / "copy"
    copy.mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        (copy / name).write_bytes((CONNECTOR / name).read_bytes())
    assert start.environment("acme-apps", copy) != start.environment("acme-apps")
    other = start.environment("acme-apps", copy)
    (copy / "uv.lock").write_bytes(b"another lock")
    assert start.environment("acme-apps", copy) != other
    assert start.environment("acme-apps") == start.environment("acme-apps")


def test_the_marker_is_beside_the_environment_so_uv_makes_the_folder(data):
    folder = data / "abc"
    start.mark_used(folder)
    assert (data / "abc.used").is_file() and not folder.exists()
    assert start.remove_unused("acme-apps", folder) == []
    assert (data / "abc.used").is_file(), "the marker of the environment being started stays"


def old(folder, days):
    folder.mkdir(parents=True)
    start.mark_used(folder)
    moment = time.time() - days * 24 * 3600
    os.utime(start.marker(folder), (moment, moment))


def test_only_environments_unused_for_a_week_go(data):
    keep, recent, stale = data / "keep", data / "recent", data / "stale"
    old(keep, 30)
    old(recent, 2)
    old(stale, 8)
    assert start.remove_unused("acme-apps", keep) == ["stale"]
    assert keep.exists() and recent.exists() and not stale.exists()
    assert not (data / "stale.used").exists()


def test_an_environment_in_use_stays(data, monkeypatch):
    stale = data / "stale"
    old(stale, 8)
    real_rename = Path.rename

    def refused(self, target):
        if self == stale:
            raise PermissionError(5, "Access is denied")  # as Windows answers while a program runs from it
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", refused)
    assert start.remove_unused("acme-apps", data / "keep") == []
    assert stale.exists()


def test_a_removal_that_stopped_half_way_is_finished(data):
    (data / "x.removing" / "Lib").mkdir(parents=True)
    start.remove_unused("acme-apps", data / "keep")
    assert not (data / "x.removing").exists()


@pytest.mark.parametrize("argv", [[], ["acme-apps"], ["Acme", "eunomai-business"], ["acme-apps", "ruby"]])
def test_only_the_connectors_programs_start(argv, capsys):
    assert start.main(argv) == 2
    assert "usage" in capsys.readouterr().err


def test_the_program_runs_with_its_environment_and_its_exit_code(data, monkeypatch):
    seen = {}

    def call(command, env):
        seen.update(command=command, env=env)
        return 3

    monkeypatch.setattr(start.subprocess, "call", call)
    assert start.main(["acme-apps", "eunomai-business-guard", "--plugin", "acme-apps"]) == 3
    assert seen["env"]["UV_PROJECT_ENVIRONMENT"] == str(start.environment("acme-apps"))
    assert seen["command"][-5:] == ["--project", str(CONNECTOR), "eunomai-business-guard", "--plugin", "acme-apps"]
    assert "--frozen" in seen["command"] and "--managed-python" in seen["command"]


@pytest.mark.skipif(sys.platform != "win32", reason="the lock is Windows' own")
def test_on_windows_a_folder_goes_while_a_program_from_another_folder_runs(tmp_path):
    """What the plugin's folder needs: nothing in it running. Shown with a Python outside and a script inside."""
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    script = plugin / "wait.py"
    script.write_text("import time\ntime.sleep(15)\n", encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(script)])
    try:
        time.sleep(1)
        script.unlink()
        plugin.rmdir()
        assert not plugin.exists()
    finally:
        process.kill()
        process.wait()


def test_a_set_environment_folder_is_used_instead(data, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(start.subprocess, "call", lambda command, env: seen.update(env=env) or 0)
    monkeypatch.setenv(start.OVERRIDE, str(tmp_path / "shared"))
    assert start.main(["acme-apps", "python", "-c", "pass"]) == 0
    assert seen["env"]["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / "shared")
