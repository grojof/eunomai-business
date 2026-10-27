"""The template's build variants: one configuration, several packages."""

import copy
import json
import zipfile

import pytest

from test_build import EXAMPLE, build


def setup(tmp_path, **variants):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(EXAMPLE), encoding="utf-8")
    folder = tmp_path / "variants"
    folder.mkdir()
    for name, changes in variants.items():
        (folder / f"{name}.json").write_text(json.dumps(changes), encoding="utf-8")
    return ["--config", str(config), "--variants", str(folder), "--out", str(tmp_path / "dist")]


def test_a_variant_changes_only_what_it_names():
    merged = build.overlay(EXAMPLE, {"settings": {"api": "https://api-test.example.test"},
                                     "repositories": ["https://git-test.example.test/team/x"]})
    assert merged["settings"] == {**EXAMPLE["settings"], "api": "https://api-test.example.test"}
    assert merged["repositories"] == ["https://git-test.example.test/team/x"] and merged["deny"] == EXAMPLE["deny"]
    assert EXAMPLE == json.loads(json.dumps(copy.deepcopy(EXAMPLE)))


def test_every_variant_is_built_in_its_own_folder(tmp_path):
    args = setup(tmp_path, tests={"repositories": ["https://git-test.example.test/team/x"]})
    assert build.main(args + ["--all"]) == 0
    dist = tmp_path / "dist"
    assert (dist / "example-project.zip").exists()
    with zipfile.ZipFile(dist / "tests" / "example-project.zip") as built:
        assert json.loads(built.read("project.json"))["repositories"] == ["https://git-test.example.test/team/x"]


@pytest.mark.parametrize("variants, argument, message", [
    ({"tests": {"settings": {"db_password": "x"}}}, "--all", "in variant tests"),
    ({}, "--variant=missing", "cannot read"),
    ({}, "--variant=../x", "lowercase letters, digits and hyphens"),
    ({"example-project": {}}, "--all", "not the plugin's name"),
])
def test_a_wrong_variant_builds_nothing(tmp_path, capsys, variants, argument, message):
    args = setup(tmp_path, **variants)
    assert build.main(args + [argument]) == 1
    assert message in capsys.readouterr().err and not (tmp_path / "dist").exists()
