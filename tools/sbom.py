"""Write the software bill of materials of the connector's runtime tree: connector/sbom.cdx.json (CycloneDX 1.5).

    python tools/sbom.py

uv exports the locked tree (versions, hashes, dependency graph); this adds each package's license from PyPI.
The result is deterministic (no timestamp, no serial number), so it only changes when the tree does. Run it
whenever connector/uv.lock changes; a test checks it matches the locked runtime tree.
"""

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

CONNECTOR = Path(__file__).resolve().parent.parent / "connector"
OUT = CONNECTOR / "sbom.cdx.json"


def _license(name: str, version: str) -> list[dict]:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
        info = json.load(response)["info"]
    if info.get("license_expression"):
        return [{"expression": info["license_expression"]}]
    classifiers = [c.split(" :: ")[-1] for c in info.get("classifiers") or [] if c.startswith("License ::")]
    named = (info.get("license") or "").strip()
    if named and len(named) <= 80:
        return [{"license": {"name": named}}]
    if classifiers:
        return [{"license": {"name": classifiers[0]}}]
    return []


def main() -> int:
    exported = subprocess.run(["uv", "export", "--frozen", "--no-dev", "--format", "cyclonedx1.5"], cwd=CONNECTOR,
                              capture_output=True, text=True, check=True).stdout
    bom = json.loads(exported)
    bom.pop("serialNumber", None)
    bom["metadata"].pop("timestamp", None)
    missing = []
    for component in bom["components"]:
        component["licenses"] = _license(component["name"], component["version"])
        if not component["licenses"]:
            missing.append(component["name"])
    OUT.write_text(json.dumps(bom, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(CONNECTOR.parent)}: {len(bom['components'])} components"
          + (f"; no license found for {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
