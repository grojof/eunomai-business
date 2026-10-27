"""Pack the H10 spike: three project plugins next to eunomai-business, the same except for `dependencies`.

dist/eunomai-project-spike.zip          "dependencies": ["eunomai-business"]                (a bare name)
dist/eunomai-project-spike-named.zip    "dependencies": ["eunomai-business@organization"]   (a name with a marketplace)
dist/eunomai-project-spike-nodep.zip    no dependencies (to tell the dependency's effect from the rest)

uv comes from the repository's config.local.json (`uv`), as in the base plugin's build.
"""

import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = HERE / "plugin"
SKIP = {".venv", "__pycache__"}


def config_uv() -> str:
    try:
        return json.loads((ROOT / "config.local.json").read_text(encoding="utf-8")).get("uv") or "uv"
    except (OSError, ValueError):
        return "uv"


def pack(target: Path, manifest: dict) -> None:
    uv = config_uv().replace("\\", "/")
    # every template is JSON: values go in escaped, and the result must parse
    values = {"UV": uv, "UV_COMMAND": f'"{uv}"' if " " in uv else uv}
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(".claude-plugin/plugin.json", json.dumps(manifest, indent=2))
        for path in sorted(SOURCE.rglob("*")):
            relative = path.relative_to(SOURCE)
            if not path.is_file() or SKIP & set(relative.parts):
                continue
            if path.name.endswith(".template"):
                text = path.read_text(encoding="utf-8")
                for key, value in values.items():
                    text = text.replace("{{" + key + "}}", json.dumps(value)[1:-1])
                json.loads(text)
                archive.writestr(relative.as_posix().removesuffix(".template"), text)
            else:
                archive.write(path, relative.as_posix())
    print(f"built {target}")


def main() -> None:
    base = {"version": "0.1.0", "description": "H10 spike: a project plugin with its own skill, local server and "
                                               "hook, next to eunomai-business."}
    dist = HERE / "dist"
    pack(dist / "eunomai-project-spike.zip",
         {"name": "eunomai-project-spike", **base, "dependencies": ["eunomai-business"]})
    pack(dist / "eunomai-project-spike-named.zip",
         {"name": "eunomai-project-spike-named", **base, "dependencies": ["eunomai-business@organization"]})
    pack(dist / "eunomai-project-spike-nodep.zip", {"name": "eunomai-project-spike-nodep", **base})


if __name__ == "__main__":
    main()
