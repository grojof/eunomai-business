"""tools/test.py: what a change can break, by fixed rules, and the two passes of a fast run."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("test_runner", ROOT / "tools" / "test.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
TESTS = ROOT / "connector" / "tests"


def names(selection) -> set[str]:
    return {path.name for path in selection.files}


def test_a_changed_test_file_runs_itself_alone():
    chosen = runner.select(["connector/tests/test_hosting.py"])
    assert names(chosen) == {"test_hosting.py"} and not chosen.everything


def test_a_module_runs_its_own_tests_and_those_that_name_it():
    chosen = runner.select(["connector/src/eunomai_business/hosting.py"])
    assert "test_hosting.py" in names(chosen) and not chosen.everything
    assert "test_auth.py" not in names(chosen)


@pytest.mark.parametrize("path", ["connector/pyproject.toml", "connector/uv.lock", "connector/tests/conftest.py",
                                  "connector/src/eunomai_business/__init__.py", "something/unknown.txt"])
def test_what_everything_rests_on_or_no_rule_knows_runs_everything(path):
    assert runner.select([path]).everything


def test_documentation_runs_the_tests_that_read_it():
    chosen = runner.select(["docs/barriers.md"])
    assert {"test_skill.py", "test_preview_hostile.py"} <= names(chosen) and not chosen.everything


def test_the_plugin_runs_the_tests_that_read_its_files():
    chosen = runner.select(["plugin/skills/specialist/SKILL.md"])
    assert "test_skill.py" in names(chosen) and not chosen.everything


def test_a_tool_runs_the_tests_that_name_it():
    assert "test_new_project.py" in names(runner.select(["tools/new_project.py"]))


def test_the_templates_run_their_own_suites():
    assert runner.select(["templates/project-plugin/server/main.py"]).project_plugin
    assert runner.select(["templates/test-environment-agent/agent.py"]).agent


def test_every_choice_says_why():
    chosen = runner.select(["docs/barriers.md", "something/unknown.txt"])
    assert len(chosen.why) == 2 and "everything" in chosen.why[1]


def test_a_fast_run_is_three_passes_over_the_same_selection(monkeypatch):
    commands = []
    monkeypatch.setattr(runner, "_run", lambda command, folder: commands.append(command) or 0)
    assert runner.run_connector(["tests/test_hosting.py"]) == 0
    assert commands[0][-5:] == ["-n", "auto", "-m", "not serial and not preview", "tests/test_hosting.py"]
    assert commands[1][-5:] == ["-n", runner.PREVIEW_WORKERS, "-m", "preview and not serial", "tests/test_hosting.py"]
    assert commands[2][-5:] == ["-n", runner.CLOCK_WORKERS, "-m", "serial", "tests/test_hosting.py"]


def test_a_failed_pass_fails_the_run_and_the_others_still_run(monkeypatch):
    codes = iter([0, 1, 0])
    commands = []
    monkeypatch.setattr(runner, "_run", lambda command, folder: commands.append(command) or next(codes))
    assert runner.run_connector([]) == 1 and len(commands) == 3


def test_no_test_in_a_pass_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: type("Done", (), {"returncode": runner.NO_TESTS}))
    assert runner._run(["pytest"], ROOT) == 0


def test_what_waits_on_the_clock_is_serial_and_this_test_is_not(request):
    """The conftest marks them by what their body calls; this test does not wait, so it is not."""
    assert request.node.get_closest_marker("serial") is None
    conftest = (TESTS / "conftest.py").read_text(encoding="utf-8")
    assert "CLOCK = re.compile" in conftest and "item.add_marker(pytest.mark.serial)" in conftest
