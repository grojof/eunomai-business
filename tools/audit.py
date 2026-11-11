"""The connector's dependency audit of a folder, as IT's configuration decides it: what a person's computer will
answer for that project. Run it on a template before publishing it, and on a project after changing what it installs.

    uv run --project connector --frozen python tools/audit.py <folder> [--config config.local.json]

It needs the connector's packages, so it runs in the connector's environment, as the line above does.

Ends with 0 when the audit allows the folder, 1 when it blocks it.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "connector" / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.json")
    arguments = parser.parse_args()
    if not arguments.folder.is_dir():
        parser.error(f"{arguments.folder} is not a folder")
    configured = json.loads(arguments.config.read_text(encoding="utf-8")) if arguments.config.is_file() else {}
    os.environ["EUNOMAI_SPECIALIST"] = json.dumps(
        {"dependency_exceptions": configured.get("dependency_exceptions", [])}
    )
    from eunomai_business import deps

    result = deps.audit(arguments.folder.resolve())
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result["verdict"] == "allowed" else 1


if __name__ == "__main__":
    sys.exit(main())
