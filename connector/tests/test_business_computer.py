"""A business user's computer: uv deployed by IT, and neither git nor a Python on the path.

Those marked `preview` run the real thing. What the computer lacks is proved two ways: the path holds uv and the
system's folders, and in the folder uv's own children look in first stand a `git` and a `python` that write down that
they were started. The proxy nobody answers at stands for a network that lets nothing out, so no test here needs one.
"""

import ast
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from conftest import stop_previews
from test_preview import APP, LOCK, PYPROJECT, declaration, show

from eunomai_business import __file__ as package_file
from eunomai_business import deps, gitops, preview, server as tools

needs_uv = pytest.mark.skipif(not (os.environ.get("UV") or shutil.which("uv")), reason="needs uv")


def real(test):
    return pytest.mark.preview(needs_uv(test))


WINDOWS = sys.platform == "win32"

PACKAGE_PROJECT = b'[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n' \
                  b'dependencies = ["iniconfig"]\n\n[tool.uv]\npackage = false\n'
WHEEL = "packages/2c/e1/e6716421ea10d38022b952c159d5161ca1193197fb744506875fbb87ea7b/iniconfig-2.1.0-py3-none-any.whl"
PACKAGE_LOCK = '''version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "demo"
version = "0.1.0"
source = { virtual = "." }
dependencies = [{ name = "iniconfig" }]

[package.metadata]
requires-dist = [{ name = "iniconfig" }]

[[package]]
name = "iniconfig"
version = "2.1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://HOST/WHEEL", hash = "sha256:9deba5723312380e77435581c6bf4935c94cbfab9b1ed33ef8d238ea168eb760", size = 6050 }]
'''.replace("WHEEL", WHEEL)
ALLOWED = {"verdict": "allowed", "files": [], "packages": 1, "blocked": [], "not_pinned": [], "without_hashes": []}


@pytest.fixture(autouse=True)
def nothing_left_behind():
    gitops._audits.clear()
    yield
    stop_previews()


@pytest.fixture
def turned_on(monkeypatch):
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"app_preview": True}))
    monkeypatch.setattr(preview.webbrowser, "open", lambda url: True)


@pytest.fixture
def pids(tmp_path) -> Path:
    return tmp_path / "pids.json"


def project(server, files: dict) -> tuple[str, str]:
    name = f"computer-{uuid.uuid4().hex[:8]}"
    server.initialize(name)
    server.server_commit(name, "main", files)
    return name, f"{server.url}/me/{name}.git"


def application(pids: Path, **more) -> dict:
    return {"pyproject.toml": PYPROJECT, "uv.lock": LOCK, "app.py": APP, "message.txt": b"saved\n",
            ".eunomai/project.toml": declaration(pids), **more}


# --- what the connector starts ---------------------------------------------------------------------------------------

STARTERS = {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput", "system", "popen",
            "execv", "execve", "execvp", "execvpe", "execl", "execlp", "spawnv", "spawnve", "spawnl", "spawnlp",
            "startfile", "create_subprocess_exec", "create_subprocess_shell"}


MODULES = {"subprocess", "os", "asyncio"}


def starts_a_program(called: ast.expr) -> bool:
    """`subprocess.run`, `os.system`, or a bare `Popen`, not the `run` of something else."""
    if isinstance(called, ast.Attribute):
        return called.attr in STARTERS and isinstance(called.value, ast.Name) and called.value.id in MODULES
    return isinstance(called, ast.Name) and called.id in STARTERS


def programs_named(source: str) -> set[str]:
    """Every program a source starts that is written out in it, and every git client that starts one."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and node.args and starts_a_program(node.func):
            first = node.args[0]
            words = first.elts if isinstance(first, (ast.List, ast.Tuple)) else [first]
            if words and isinstance(words[0], ast.Constant) and isinstance(words[0].value, str):
                found.add(words[0].value.split()[0].lower())
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in ("SubprocessGitClient", "SubprocessSSHVendor"):
                found.add(name)
        if isinstance(node, ast.ImportFrom):
            found |= {alias.name for alias in node.names if alias.name in ("SubprocessGitClient", "SubprocessSSHVendor")}
    return found


@pytest.mark.parametrize("line", [
    'subprocess.run(["git", "status"])', 'subprocess.Popen(("git.exe", "log"))', 'os.system("git status")',
    'subprocess.check_output("git rev-parse HEAD", shell=True)', 'os.execvp("git", ["git"])', 'Popen(["git"])',
    "from dulwich.client import SubprocessGitClient"])
def test_the_scan_sees_git_being_started(line):
    assert programs_named(line) & {"git", "git.exe", "SubprocessGitClient"}


def test_no_connector_source_starts_git():
    """The only program named in the source is lsof, on a system without /proc. uv and netstat are worked out."""
    sources = sorted(Path(package_file).parent.rglob("*.py"))
    assert len(sources) > 5
    assert {program for source in sources for program in programs_named(source.read_text(encoding="utf-8"))} == {"lsof"}


def test_netstat_is_named_by_its_whole_path(monkeypatch):
    """Never looked for on a path: a folder earlier on it could hold another program of that name."""
    seen = []
    monkeypatch.setattr(preview.sys, "platform", "win32")
    monkeypatch.setenv("SYSTEMROOT", r"D:\Windows")
    monkeypatch.setattr(preview.subprocess, "run", lambda arguments, **options: seen.append(arguments[0])
                        or subprocess.CompletedProcess(arguments, 0, "", ""))

    class Current:
        ask = staticmethod(lambda request: {"ids": [1]})

    assert preview._listens_beyond_this_computer(Current, 1234) is False
    assert seen == [r"D:\Windows/System32/netstat.exe"] * 2


@pytest.fixture
def business_computer(tmp_path, monkeypatch) -> dict:
    """The path of a computer IT set up: its uv and the system's folders, and what looks for a git or a Python finds
    one that only writes down it was started. uv's folder comes first on the path of whatever uv starts."""
    uv = Path(os.environ.get("UV") or shutil.which("uv"))
    deployed = tmp_path / "deployed-by-it"
    deployed.mkdir()
    shutil.copy2(uv, deployed / uv.name)
    trace = tmp_path / "started-by-name.txt"
    for program in ("git", "python", "python3"):
        if WINDOWS:
            (deployed / f"{program}.cmd").write_text(f'@echo {program}>>"{trace}"\r\n')
        else:
            file = deployed / program
            file.write_text(f'#!/bin/sh\necho {program} >> "{trace}"\n')
            file.chmod(file.stat().st_mode | stat.S_IEXEC)
    root = os.environ.get("SYSTEMROOT", "")
    system = [f"{root}\\System32", root, f"{root}\\System32\\Wbem"] if WINDOWS else []
    for program in ("git", "python", "python3"):
        assert not system or shutil.which(program, path=os.pathsep.join(system)) is None
    monkeypatch.setenv("PATH", os.pathsep.join([str(deployed), *system]))
    monkeypatch.setenv("UV", str(deployed / uv.name))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    started = []
    original = subprocess.Popen

    class Noted(original):
        def __init__(self, arguments, *rest, **options):
            started.append(str(arguments[0]))
            super().__init__(arguments, *rest, **options)

    monkeypatch.setattr(subprocess, "Popen", Noted)
    return {"trace": trace, "started": started, "uv": str(deployed / uv.name)}


@real
def test_the_whole_path_needs_neither_git_nor_a_python(signed_in, workspaces, turned_on, business_computer, pids):
    name, url = project(signed_in, application(pids))
    ws = Path(tools.workspace_clone(url)["path"])
    assert (ws / ".git").is_dir()
    assert tools.version_create(name, "draft/work").get("status") != "needs_it"
    (ws / "message.txt").write_bytes(b"changed\n")
    assert tools.version_save(name, "A change").get("status") != "needs_it"
    assert tools.dependency_audit(name)["verdict"] == "allowed"
    assert tools.version_send(name)["pushed"]
    assert tools.version_propose(name, "A change", "It changes the message.")["url"]
    assert signed_in.pulls_of(name)
    answer = show(name)
    assert answer["status"] == "ready", answer
    assert httpx.get(answer["url"], timeout=10).text == "changed\n"
    assert tools.app_preview_stop(name)["status"] == "stopped"
    assert not business_computer["trace"].exists(), business_computer["trace"].read_text()
    names = {Path(program.replace("\\", "/")).name.lower() for program in business_computer["started"]}
    assert not {n for n in names if n.removesuffix(".exe") not in ("uv", "netstat") and not n.startswith("python")}, names
    if WINDOWS:
        assert "netstat.exe" in names


# --- what a person sees when a download cannot get through ---------------------------------------------------------

@pytest.fixture
def no_way_out(tmp_path, monkeypatch) -> Path:
    """An empty cache behind a proxy nobody answers at. The fake server is here, so it stays reachable."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{closed}")
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{closed}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "empty-cache"))
    return tmp_path


def plain(message: str) -> None:
    assert "http" not in message and "cause" not in message and "error" not in message.lower() and "\n" not in message


@real
def test_a_python_that_cannot_be_downloaded_names_the_addresses_and_the_version(
        signed_in, workspaces, turned_on, no_way_out, pids, monkeypatch):
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(no_way_out / "no-pythons"))
    monkeypatch.setattr(deps, "audit", lambda folder: dict(ALLOWED))
    name, url = project(signed_in, application(pids, **{".python-version": b"3.13\n"}))
    gitops.clone(url)
    gitops.branch(name, "draft/work")
    answer = show(name)
    assert answer["status"] == "needs_it", answer
    plain(answer["user_message"])
    report = answer["it_report"]
    assert "Cannot reach: releases.astral.sh and github.com" in report and "Python to deploy: 3.13\n" in report
    assert "uv python install 3.13" in report and not pids.exists()
    assert not preview._previews and not preview._unread


@pytest.mark.parametrize("host", ["files.pythonhosted.org", "pypi.org"])
@real
def test_a_package_that_cannot_be_downloaded_names_the_address(
        signed_in, workspaces, turned_on, no_way_out, pids, monkeypatch, host):
    """A Python is there, in uv's own folder; what is not is the package."""
    monkeypatch.setattr(deps, "audit", lambda folder: dict(ALLOWED))
    name, url = project(signed_in, application(pids, **{"pyproject.toml": PACKAGE_PROJECT,
                                                        "uv.lock": PACKAGE_LOCK.replace("HOST", host).encode()}))
    gitops.clone(url)
    gitops.branch(name, "draft/work")
    answer = show(name)
    assert answer["status"] == "needs_it", answer
    plain(answer["user_message"])
    assert f"Cannot reach: {host}\n" in answer["it_report"] and "Python to deploy" not in answer["it_report"]
    assert not pids.exists()


def test_an_installation_that_was_not_blocked_stays_a_plain_stop_without_a_guess():
    assert preview._download_problem("error: Failed to install x\n  cause: the disk is full\n") is None
    assert preview._download_problem(
        "error: Failed to download `x==1`\n  cause: Hash mismatch for `x==1`\n"
        "  cause: https://files.pythonhosted.org/packages/x.whl\n") is None


@pytest.mark.parametrize("cause", [
    "tunnel error: unsuccessful", "operation timed out", "tcp connect error", "dns error: failed to lookup address",
    "invalid peer certificate: UnknownIssuer"])
def test_each_way_a_network_says_no(cause):
    log = ("error: Request failed after 3 retries in 8.2s\n"
           "  cause: Failed to download `https://github.com/astral-sh/python-build-standalone/releases/download/1/"
           "cpython-3.15.1%2B1-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`\n"
           f"  cause: client error (Connect)\n  cause: {cause}\n")
    assert preview._download_problem(log) == ("python", "3.15")


def test_a_python_uv_does_not_know():
    log = "error: No interpreter found for Python 3.99 in managed installations\nhint: uv embeds available Python downloads"
    assert preview._download_problem(log) == ("unknown", "3.99")


@pytest.mark.parametrize(("host", "open_first"), [("api.osv.dev", False), ("pypi.org", True)])
@pytest.mark.parametrize("tool", ["preview", "send"])
def test_an_audit_that_cannot_get_out_names_the_address(signed_in, workspaces, turned_on, no_way_out, pids, monkeypatch,
                                                        host, open_first, tool):
    if open_first:
        monkeypatch.setattr(deps, "_vulnerable", lambda queries: {query: [] for query in queries})
    name, url = project(signed_in, application(pids, **{"pyproject.toml": PACKAGE_PROJECT, "uv.lock": PACKAGE_LOCK.replace(
        "HOST", "files.pythonhosted.org").encode()}))
    ws = Path(gitops.clone(url)["path"])
    gitops.branch(name, "draft/work")
    (ws / "notes.md").write_bytes(b"Work.\n")
    gitops.save(name, "Work")
    answer = show(name) if tool == "preview" else tools.version_send(name)
    assert answer["status"] == "audit_unavailable", answer
    plain(answer["user_message"])
    assert f"Cannot reach: {host}\n" in answer["it_report"]


CLOSED = {"package": "alpha", "version": "1.0", "reasons": [
    f"{deps._NOT_VERIFIED}git+https://github.com/example/alpha.git"]}


def audited(*blocked) -> dict:
    return {"verdict": "blocked", "files": ["uv.lock"], "packages": 2, "blocked": list(blocked), "not_pinned": [],
            "without_hashes": []}


def test_a_source_host_the_network_closes_is_not_a_fault_of_the_packages(signed_in, workspaces, pids, monkeypatch):
    """With github.com closed, every package seemed not to show where it comes from, and a report that said nothing."""
    monkeypatch.setattr(deps, "audit", lambda folder: audited(CLOSED, {**CLOSED, "package": "beta"}))
    name, url = project(signed_in, application(pids))
    ws = Path(gitops.clone(url)["path"])
    gitops.branch(name, "draft/work")
    (ws / "notes.md").write_bytes(b"Work.\n")
    gitops.save(name, "Work")
    answer = tools.version_send(name)
    assert answer["status"] == "audit_unavailable" and not answer.get("pushed"), answer
    plain(answer["user_message"])
    assert "Cannot reach: github.com\n" in answer["it_report"] and "does not show" not in answer["user_message"]


def test_a_closed_host_does_not_hide_a_real_reason(signed_in, workspaces, pids, monkeypatch):
    bad = {"package": "beta", "version": "1.0", "reasons": ["known vulnerabilities: X-1"]}
    answer = deps.refusal("work", {**audited(CLOSED, bad), "head": "0" * 40}, "This version was not sent")
    assert answer["status"] == "audit_refused" and "Cannot reach: github.com\n" in answer["it_report"]
    assert "alpha could not be checked from this network" in answer["reasons"]
    assert "beta has a known security problem" in answer["reasons"]


def test_a_failure_with_no_address_stays_as_it_was(signed_in, workspaces, pids, monkeypatch):
    """A server's answer that is incomplete names no address, and there is nothing for IT to allow."""
    name, url = project(signed_in, application(pids))
    ws = Path(gitops.clone(url)["path"])
    gitops.branch(name, "draft/work")
    (ws / "notes.md").write_bytes(b"Work.\n")
    gitops.save(name, "Work")

    def audit(folder):
        raise deps.Unreachable()

    monkeypatch.setattr(deps, "audit", audit)
    answer = tools.version_send(name)
    assert answer["status"] == "audit_unavailable" and "it_report" not in answer
