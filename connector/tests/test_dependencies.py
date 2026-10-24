"""eunomai-business's own dependencies follow its rules: every package pinned, the bill of materials current."""

import json
import re
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
def test_the_sbom_lists_exactly_the_locked_runtime_tree_with_licenses():
    """sbom.cdx.json (tools/sbom.py) describes the packages and versions users' computers install from uv.lock."""
    exported = subprocess.run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes",
                               "--format", "requirements.txt"], cwd=CONNECTOR, capture_output=True, text=True,
                              check=True).stdout
    pins = set(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;]+)", exported, re.M))
    bom = json.loads((CONNECTOR / "sbom.cdx.json").read_text(encoding="utf-8"))
    listed = {(c["name"], c["version"]) for c in bom["components"]}
    assert bom["bomFormat"] == "CycloneDX" and listed == pins, "run python tools/sbom.py"
    assert all(c["licenses"] for c in bom["components"])
