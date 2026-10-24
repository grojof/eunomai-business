"""Zip the spike plugin for upload to Claude Desktop: research/node-connector/spike/dist/eunomai-node-spike.zip."""

import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "plugin"
TARGET = HERE / "dist" / "eunomai-node-spike.zip"

TARGET.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(SOURCE.rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(SOURCE).as_posix())
print(f"built {TARGET}")
