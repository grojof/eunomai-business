"""Pack the spike: dist/eunomai-mcpb-spike.mcpb (the extension) and dist/eunomai-mcpb-spike-hooks.zip (the plugin)."""

import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP = {".venv", "__pycache__"}


def pack(source: Path, target: Path) -> None:
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and not SKIP & set(path.relative_to(source).parts):
                archive.write(path, path.relative_to(source).as_posix())
    print(f"built {target}")


pack(HERE / "extension", HERE / "dist" / "eunomai-mcpb-spike.mcpb")
pack(HERE / "plugin", HERE / "dist" / "eunomai-mcpb-spike-hooks.zip")
