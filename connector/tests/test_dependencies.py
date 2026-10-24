"""eunomai-business's own dependencies follow its rules: every package pinned, the pins match the lock."""

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

CONNECTOR = Path(__file__).resolve().parents[1]


def test_direct_dependencies_are_pinned_exactly():
    project = tomllib.loads((CONNECTOR / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert all("==" in requirement for requirement in project["dependencies"])


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_constraints_match_the_lock():
    """constraints.txt is what users' computers install; it must be exactly what uv.lock says."""
    exported = subprocess.run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes",
                               "--format", "requirements.txt"], cwd=CONNECTOR, capture_output=True, text=True,
                              check=True).stdout
    committed = (CONNECTOR / "constraints.txt").read_text(encoding="utf-8")

    def pins(text: str) -> list[str]:
        return [line for line in text.splitlines() if line and not line.lstrip().startswith("#")]

    assert pins(committed) == pins(exported), "run the uv export command at the top of constraints.txt"
