import json

import pytest

REPOSITORY = "https://git.example.test/team/example-project"
OTHER = "https://git.example.test/team/other"


@pytest.fixture
def config(tmp_path, monkeypatch):
    """eunomai-business's register with two workspaces of the project (one written with .git and capitals), one of
    another project, and one registered whose folder is gone. A folder no one registered, and a .git/config that
    says otherwise, count for nothing."""
    root = tmp_path / "workspaces"
    for name in ("Ventas", "ventas-copia", "otra", "suelta"):
        (root / name / ".git").mkdir(parents=True)
    (root / "Ventas" / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {OTHER}\n', encoding="utf-8")
    (root / "otra" / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {REPOSITORY}\n', encoding="utf-8")
    data = tmp_path / "localappdata"
    (data / "eunomai-business").mkdir(parents=True)
    registry = {str(root / "Ventas"): {"origin": REPOSITORY, "main_branch": "main"},
                str(root / "ventas-copia"): {"origin": REPOSITORY.upper() + ".git/", "main_branch": "main"},
                str(root / "otra"): {"origin": OTHER, "main_branch": "main"},
                str(root / "gone"): {"origin": REPOSITORY, "main_branch": "main"}}
    (data / "eunomai-business" / "workspaces.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(data))
    return {"name": "example-project", "display_name": "Example project", "repositories": [REPOSITORY],
            "deny": [{"rule": "Edit(/data/raw/**)", "reason": "the project keeps these as they are"},
                     {"rule": "Edit(/*.lock)", "reason": "the project keeps these as they are"}],
            "settings": {"example_folder": "docs"}, "_root": root}
