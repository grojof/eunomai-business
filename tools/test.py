"""The tests, fast: in parallel on every core, then the few that cannot share the computer, one at a time.

    python tools/test.py              every suite: the connector's, the project plugin template's, the agent's
    python tools/test.py --affected   only what the files changed against main can break, by the rules in RULES
    python tools/test.py --list       says what --affected would run, and runs nothing

The connector's tests run with pytest-xdist in three passes: on every core, what neither starts real applications nor
waits on the clock; four at a time, what starts applications (`preview`); then, two at a time, what waits on the clock to
see a process end or a limit pass (`serial`, marked by the conftest). Beside other tests those last ones get slow or
wrong, not the connector. Plain `pytest` still runs everything one at a time, as before. Standard library only.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONNECTOR = ROOT / "connector"
TESTS = CONNECTOR / "tests"
PROJECT_PLUGIN = ROOT / "templates" / "project-plugin" / "server"
AGENT = ROOT / "templates" / "test-environment-agent"
UV_PYTEST = ["uv", "run", "--frozen", "--group", "dev", "--python", "3.12", "pytest", "-q"]
NO_TESTS = 5  # pytest's exit code when the selection holds no test: nothing failed

# What a change can break, read top to bottom; the first rule that matches a path decides for it. `everything` means
# the connector's whole suite; tests are found by what their source names, so a new test file follows the same rules.
RULES = (
    (r"connector/tests/test_\w+\.py", "that test file"),
    (r"connector/(tests/(conftest|preview_keyring)\.py|pyproject\.toml|uv\.lock)|tools/test\.py", "everything"),
    (r"connector/src/eunomai_business/(\w+)\.py", "test_<module>.py and every test that names the module"),
    (r"plugin/.*|config\.example\.json", "every test that reads the plugin's files, and the build's"),
    (r"docs/.*|[^/]+\.md", "every test that reads the documentation"),
    (r"tools/(\w+)\.py|(\w+)\.example\.json", "every test that names the tool"),
    (r"templates/project-plugin/.*", "the project plugin template's own tests"),
    (r"templates/test-environment-agent/.*", "the test environment agent's own tests"),
    (r"\.github/workflows/.*", "every test that reads the workflows"),
)


@dataclass
class Selection:
    files: set[Path] = field(default_factory=set)
    everything: bool = False
    project_plugin: bool = False
    agent: bool = False
    why: list[str] = field(default_factory=list)


def _tests_naming(pattern: str) -> set[Path]:
    found = re.compile(pattern)
    return {path for path in TESTS.glob("test_*.py") if found.search(path.read_text(encoding="utf-8"))}


def changed_files() -> list[str]:
    """What differs from main: committed on this branch, staged, changed and new, as git names them."""
    def names(*arguments: str) -> list[str]:
        done = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=True)
        return [line for line in done.stdout.splitlines() if line]

    base = names("merge-base", "main", "HEAD")[0]
    files = names("diff", "--name-only", base) + names("ls-files", "--others", "--exclude-standard")
    return sorted(set(files))


def select(paths: list[str]) -> Selection:
    chosen = Selection()
    for path in paths:
        for pattern, rule in RULES:
            match = re.fullmatch(pattern, path)
            if not match:
                continue
            if rule == "that test file":
                tests = {ROOT / path} if (ROOT / path).exists() else set()
            elif rule == "everything":
                chosen.everything = True
                tests = set()
            elif rule.startswith("test_<module>"):
                module = match[1]
                tests = _tests_naming(rf"\b{module}\b") | {TESTS / f"test_{module}.py"}
                tests = {test for test in tests if test.exists()}
                if module == "__init__":
                    chosen.everything = True
            elif rule.startswith("every test that reads the plugin"):
                tests = _tests_naming(r'"plugin"|"skills"|import build')
            elif rule == "every test that reads the documentation":
                tests = _tests_naming(r'"docs"|"README\.md"|"CHANGELOG\.md"')
            elif rule == "every test that names the tool":
                name = match[1] or match[2]
                tests = _tests_naming(rf"\b{name}\b")
            elif rule.startswith("the project plugin"):
                chosen.project_plugin, tests = True, set()
            elif rule.startswith("the test environment agent"):
                chosen.agent, tests = True, set()
            else:
                tests = _tests_naming(r"workflows")
            chosen.files |= tests
            chosen.why.append(f"{path}: {rule}" + (f" ({len(tests)} files)" if tests else ""))
            break
        else:
            chosen.everything = True
            chosen.why.append(f"{path}: no rule knows it, so everything")
    return chosen


def _run(command: list[str], folder: Path) -> int:
    print("$", " ".join(command), flush=True)
    code = subprocess.run(command, cwd=folder).returncode
    return 0 if code == NO_TESTS else code


PREVIEW_WORKERS = "4"
"""How many tests that start real applications run at once: more, and their own waits are starved."""
CLOCK_WORKERS = "2"
"""How many tests that wait on the clock run at once: with every core busy, a time limit or a stop was missed; two at a
time passed twice in a row, in half the time of one."""


def run_connector(files: list[str]) -> int:
    """Three passes over the same selection: every core for what neither starts applications nor waits on the clock,
    a few at a time for what starts applications, then what waits on the clock, two at a time."""
    codes = [_run([*UV_PYTEST, "-n", "auto", "-m", "not serial and not preview", *files], CONNECTOR),
             _run([*UV_PYTEST, "-n", PREVIEW_WORKERS, "-m", "preview and not serial", *files], CONNECTOR),
             _run([*UV_PYTEST, "-n", CLOCK_WORKERS, "-m", "serial", *files], CONNECTOR)]
    return next((code for code in codes if code), 0)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The tests, fast.")
    parser.add_argument("--affected", action="store_true", help="only what the changes against main can break")
    parser.add_argument("--list", action="store_true", help="say what --affected would run, and run nothing")
    options = parser.parse_args(arguments)
    if options.affected or options.list:
        paths = changed_files()
        chosen = select(paths)
        print("Changed against main:" if paths else "Nothing changed against main: no test to run.")
        for line in chosen.why:
            print("  " + line)
        if chosen.everything:
            print("Runs: the connector's whole suite.")
        else:
            print("Runs:", ", ".join(sorted(path.relative_to(ROOT).as_posix() for path in chosen.files)) or "no connector test")
        if options.list:
            return 0
        codes = []
        if chosen.everything:
            codes.append(run_connector([]))
        elif chosen.files:
            codes.append(run_connector(sorted(str(path.relative_to(CONNECTOR)) for path in chosen.files)))
        if chosen.project_plugin:
            codes.append(_run(UV_PYTEST, PROJECT_PLUGIN))
        if chosen.agent:
            codes.append(_run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], AGENT))
        return max(codes, default=0)
    codes = [run_connector([]), _run(UV_PYTEST, PROJECT_PLUGIN)]
    if sys.platform != "win32":  # it starts the agent with POSIX tools, as CI does on Linux
        codes.append(_run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], AGENT))
    return max(codes)


if __name__ == "__main__":
    sys.exit(main())
