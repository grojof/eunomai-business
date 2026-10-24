"""Daily dependency maintenance: the newest versions the project's own rules allow, nothing else.

    uv run --project connector --frozen python tools/update_dependencies.py --summary summary.md --problems problems.md

1. Drop vulnerability overrides that the two-week window now covers.
2. Upgrade connector/uv.lock (uv refuses anything younger than two weeks: `exclude-newer`).
3. For each runtime package with a known vulnerability, move to the version dependency_check recommends, even if
   it is younger than two weeks (an `exclude-newer-package` override).
4. Refresh the bill of materials.

Writes a Markdown summary of what changed, and the problems no allowed version solves.
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eunomai_business import deps

ROOT = Path(__file__).resolve().parent.parent
CONNECTOR = ROOT / "connector"
PYPROJECT = CONNECTOR / "pyproject.toml"
OVERRIDES = re.compile(r"^exclude-newer-package = \{.*\}.*$", re.M)
WINDOW = timedelta(days=14)


def uv(*args: str) -> str:
    return subprocess.run(["uv", *args], cwd=CONNECTOR, capture_output=True, text=True, check=True).stdout


def runtime_pins() -> dict[str, str]:
    """Locked runtime packages, leaving out those only installed in web browsers (emscripten)."""
    exported = uv("export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--format", "requirements.txt")
    return {name: version for name, version, marker in
            re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;]+)(.*)$", exported, re.M) if "== 'emscripten'" not in marker}


def overrides() -> dict[str, str]:
    return dict(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["uv"].get("exclude-newer-package", {}))


def write_overrides(values: dict[str, str]) -> None:
    """Rewrite the overrides line only when its values change, so that a run without changes changes nothing."""
    if values == overrides():
        return
    body = ", ".join(f'{name} = "{date}"' for name, date in sorted(values.items()))
    line = f"exclude-newer-package = {{ {body} }}" if body else "exclude-newer-package = {}"
    text = PYPROJECT.read_text(encoding="utf-8")
    PYPROJECT.write_text(OVERRIDES.sub(line, text, count=1), encoding="utf-8", newline="\n")


def uploaded(name: str, version: str) -> datetime:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
        files = json.load(response)["urls"]
    return min(datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00")) for f in files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--problems", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # the summary has non-ASCII; some consoles default to a code page
    notes, problems = [], []
    before = runtime_pins()

    current = overrides()
    now = datetime.now(timezone.utc)
    dropped = [name for name, date in current.items()
               if datetime.fromisoformat(date.replace("Z", "+00:00")) < now - WINDOW]
    for name in dropped:
        del current[name]
    write_overrides(current)
    uv("lock", "--upgrade")

    for _ in range(5):  # a fix can pull in other packages: check again until stable
        moved = False
        for name, version in runtime_pins().items():
            verdict = deps.check("pypi", name, version)
            if verdict["verdict"] == "allowed":
                continue
            reasons = "; ".join(verdict.get("reasons") or [])
            recommended = (verdict.get("recommended") or {}).get("version")
            if "vulnerabilit" in reasons and recommended and recommended != version:
                current[name] = (uploaded(name, recommended) + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                write_overrides(current)
                uv("lock", "--upgrade-package", name)
                notes.append(f"`{name}` {version} → {recommended}: fixes a known vulnerability ({reasons})")
                moved = True
            elif (name, version, reasons) not in problems:
                problems.append((name, version, reasons))
        if not moved:
            break

    notes += [f"`{name}`: the vulnerability override is no longer needed" for name in dropped if name not in current]
    subprocess.run([sys.executable, str(ROOT / "tools" / "sbom.py")], check=True)
    after = runtime_pins()
    changed = [(n, before.get(n, "—"), after.get(n, "—")) for n in sorted(set(before) | set(after))
               if before.get(n) != after.get(n)]

    lines = ["## Dependency update", ""]
    if changed:
        lines += ["| Package | Before | After |", "|---|---|---|"] + [f"| `{n}` | {b} | {a} |" for n, b, a in changed]
    lines += [""] + [f"- {note}" for note in notes]
    args.summary.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    args.problems.write_text("".join(f"- `{n}` {v}: {r}\n" for n, v, r in problems), encoding="utf-8")
    print(args.summary.read_text(encoding="utf-8"))
    if problems:
        print("Problems:\n" + args.problems.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
