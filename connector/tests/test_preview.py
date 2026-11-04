"""`app_preview`: the real application on the person's computer, through the connector.

Those marked `preview` start real processes with uv, from a small project with no packages, so nothing but a Python
for uv is downloaded, and only if the computer has none. The process tree and the temporary folder are checked for
real: a preview that survives its stop is the failure these exist for.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import httpx
import pytest

from conftest import alive, stop_previews
from eunomai_business import data_dir, deps, gitops, guard, preview, server as tools, settings, support, watcher

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
real = [pytest.mark.preview, needs_uv]

PYPROJECT = b'[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.12"\ndependencies = []\n\n' \
            b'[tool.uv]\npackage = false\n'
LOCK = b'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n\n[[package]]\nname = "demo"\nversion = "0.1.0"\n' \
       b'source = { virtual = "." }\n'
# A small web application, with a child of its own, as a reloader or a worker would have. It reports its processes.
APP = textwrap.dedent('''\
    import http.server, json, os, pathlib, subprocess, sys, time

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    arguments = sys.argv[1:]
    host, port = arguments[arguments.index("--host") + 1], int(arguments[arguments.index("--port") + 1])
    pathlib.Path(os.environ["PIDS_FILE"]).write_text(json.dumps([os.getpid(), child.pid]))
    if os.environ.get("APP_MODE") == "exit":
        print("the application could not start")
        sys.exit(3)
    if os.environ.get("APP_MODE") == "everywhere":
        host = "0.0.0.0"
    if os.environ.get("APP_MODE") == "second":
        import socket

        second = socket.socket()
        second.bind(("0.0.0.0", 0))
        second.listen()


    class Answer(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            text = json.dumps(dict(os.environ)) if self.path == "/env" else pathlib.Path("message.txt").read_text()
            text = "%d.%d" % sys.version_info[:2] if self.path == "/python" else text
            self.send_response(200)
            self.end_headers()
            self.wfile.write(text.encode())

        def log_message(self, *args):
            pass


    http.server.HTTPServer((host, port), Answer).serve_forever()
    ''').encode()
RUN = '["python", "app.py", "--host", "127.0.0.1", "--port", "{port}"]'
# A setup step that ends and leaves a child running: on Linux that child is in a process group of its own step's.
LEAVE = b"""import os, pathlib, subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
pathlib.Path(os.environ["LEFT_FILE"]).write_text(str(child.pid))
"""


def declaration(pids: Path, *setup: str, run: str = RUN, mode: str = "") -> bytes:
    steps = ", ".join(setup)
    return (f'[development]\ncode = true\n\n[preview]\nsetup = [{steps}]\nrun = {run}\n\n[preview.environment]\n'
            f'APP_ENVIRONMENT = "development"\nPIDS_FILE = "{pids.as_posix()}"\nAPP_MODE = "{mode}"\n').encode()


@pytest.fixture(autouse=True)
def nothing_left_behind():
    gitops._audits.clear()
    yield
    stop_previews()


@pytest.fixture
def browser(monkeypatch) -> list:
    opened = []
    monkeypatch.setattr(preview.webbrowser, "open", lambda url: opened.append(url) or True)
    return opened


@pytest.fixture
def turned_on(monkeypatch, browser):
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"app_preview": True}))


@pytest.fixture
def pids(tmp_path) -> Path:
    return tmp_path / "pids.json"


def project(server, text: bytes | None, lock: bool = True, app: bytes = APP) -> tuple[str, Path]:
    """A project with an application on its main branch, cloned, on a version."""
    name = f"preview-{uuid.uuid4().hex[:8]}"
    server.initialize(name)
    files = {"pyproject.toml": PYPROJECT, "app.py": app, "message.txt": b"saved\n", "fail.py": b"print('setup broke')\n"
             b"import sys; sys.exit(4)\n", "generate.py": b"import pathlib; pathlib.Path('message.txt')"
             b".write_text('generated')\n", **({"uv.lock": LOCK} if lock else {})}
    server.server_commit(name, "main", files)
    if text is not None:
        server.server_commit(name, "main", {".eunomai/project.toml": text})
    ws = Path(gitops.clone(f"{server.url}/me/{name}.git")["path"])
    gitops.branch(name, "draft/work")
    return name, ws


def show(name: str) -> dict:
    """What the specialist does: ask, and ask again while it is getting ready."""
    for _ in range(100):
        answer = tools.app_preview(name)
        if answer.get("status") != "starting":
            return answer
        time.sleep(0.2)
    raise AssertionError("never ready")


def gone(*numbers: int, wait: float = 15.0) -> bool:
    deadline = time.time() + wait
    while time.time() < deadline:
        if not any(alive(number) for number in numbers):
            return True
        time.sleep(0.1)
    return False


def folders() -> list[Path]:
    """The temporary folders of previews on this computer: the ones being prepared here, and the running ones."""
    states = (data_dir() / "previews").glob("*.json")
    running = [Path(state["folder"]) for state in map(preview._read_state, states) if state.get("folder")]
    return sorted({*running, *(p.folder for p in preview._previews.values())})


def wait_for_file(path: Path, wait: float = 30.0) -> None:
    deadline = time.time() + wait
    while time.time() < deadline:
        if path.exists() and path.read_text():
            return
        time.sleep(0.05)
    raise AssertionError(f"no {path}")


# --- the two keys --------------------------------------------------------------------------------------------------

def test_off_by_default(signed_in, workspaces, browser, pids, monkeypatch):
    monkeypatch.delenv("EUNOMAI_SPECIALIST", raising=False)
    name, _ = project(signed_in, declaration(pids))
    answer = tools.app_preview(name)
    assert answer["status"] == "not_turned_on" and "IT" in answer["user_message"]
    assert browser == [] and not pids.exists() and settings.load()["app_preview"] is False


def test_a_project_that_declares_nothing_is_refused(signed_in, workspaces, turned_on, browser):
    name, _ = project(signed_in, b"[development]\ncode = true\n")
    answer = tools.app_preview(name)
    assert answer["status"] == "not_declared" and browser == []


def test_the_declaration_is_read_from_the_main_branch_never_the_folder(signed_in, workspaces, turned_on, pids):
    name, ws = project(signed_in, b"[development]\ncode = true\n")
    (ws / ".eunomai" / "project.toml").write_bytes(declaration(pids))
    assert tools.app_preview(name)["status"] == "not_declared" and not pids.exists()


def test_a_main_branch_that_cannot_be_read_declares_nothing(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids))
    monkeypatch.setattr(gitops, "project_files", lambda workspace: {"context": None, "declaration": None, "read": False})
    assert tools.app_preview(name)["status"] == "not_declared"


def test_a_declaration_that_is_not_valid_goes_to_it(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, b'[preview]\nrun = "uvicorn app:app"\n')
    answer = tools.app_preview(name)
    assert answer["status"] == "needs_it" and "preview" in answer["it_report"] and not pids.exists()


GOOD = 'run = ["x", "--host", "127.0.0.1", "--port", "{port}"]'


@pytest.mark.parametrize("text, reason", [
    ('run = "uvicorn app:app --host 127.0.0.1 --port {port}"', "a list"),
    ('run = "python app.py && del *"', "a list"),
    ('run = []', "a list"),
    ('run = ["uvicorn app:app --host 127.0.0.1 --port {port}"]', "program"),
    ('run = ["/usr/bin/python", "--host", "127.0.0.1", "--port", "{port}"]', "program"),
    ('run = ["..\\\\evil.exe", "--host", "127.0.0.1", "--port", "{port}"]', "program"),
    ('run = ["app.py", "--host", "127.0.0.1", "--port", "{port}"]', "program"),
    ('run = ["app.pyw", "--host", "127.0.0.1", "--port", "{port}"]', "program"),
    ('run = ["APP.PYZ", "--host", "127.0.0.1", "--port", "{port}"]', "program"),
    ('run = ["python", "-c", "x", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python3", "-X", "dev", "app.py", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python", "../app.py", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python", "/tmp/app.py", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python", "-m", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python", "-m", "pip", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python", "-m", "pip.__main__", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python", "-m", "ensurepip", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python", "-m", "venv", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    (GOOD + '\nsetup = [["python", "-m", "pip", "install", "evil"]]', "python"),
    (GOOD + '\nsetup = [["python", "-c", "print(1)"]]', "python"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}", "&&", "del"]', "shell"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}; del"]', "shell"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}", "$(whoami)"]', "shell"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}", "a|b"]', "shell"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}", "`id`"]', "shell"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}", "a>b"]', "shell"),
    ('run = ["x", "--host", "0.0.0.0", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host=0.0.0.0", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "::", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "localhost", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "192.168.1.5", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "mypc", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "127.0.0.1", "--host", "0.0.0.0", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host=127.0.0.1", "--host", "0.0.0.0", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["gunicorn", "-b", "0.0.0.0:{port}", "--bind", "127.0.0.1:{port}"]', "127.0.0.1"),
    ('run = ["gunicorn", "--bind=0.0.0.0:{port}"]', "127.0.0.1"),
    ('run = ["x", "runserver", "0.0.0.0:{port}"]', "127.0.0.1"),
    ('run = ["x", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "127.0.0.1", "--uds", "/tmp/x", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "127.0.0.1", "--fd", "3", "--port", "{port}"]', "127.0.0.1"),
    # 127.0.0.1 somewhere else in the command says nothing
    ('run = ["python", "manage.py", "runserver", "0:{port}", "--note=127.0.0.1"]', "127.0.0.1"),
    ('run = ["flask", "run", "-h", "0", "-p", "{port}", "--x=127.0.0.1"]', "127.0.0.1"),
    ('run = ["python", "-m", "http.server", "{port}", "--bi", "0", "--x=127.0.0.1"]', "127.0.0.1"),
    ('run = ["gunicorn", "-b0:{port}", "--x=127.0.0.1"]', "127.0.0.1"),
    ('run = ["flask", "run", "-h", "mypc", "-p", "{port}", "--x=127.0.0.1"]', "127.0.0.1"),
    ('run = ["x", "-H", "0:0:0:0:0:0:0:0", "{port}", "127.0.0.1"]', "127.0.0.1"),
    ('run = ["x", "--host", "127.0.0.1", "-h", "0", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--ho", "0.0.0.0", "--host", "127.0.0.1", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--hostname", "mypc", "runserver", "mypc:{port}", "--host", "127.0.0.1"]', "127.0.0.1"),
    ('run = ["python.exe", "-c", "x", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["Python.EXE", "-m", "pip", "install", "x", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    ('run = ["python3.exe", "-c", "x", "--host", "127.0.0.1", "--port", "{port}"]', "python"),
    (GOOD + '\nsetup = [["python.exe", "-m", "pip", "install", "evil"]]', "python"),
    ('run = ["x", "--host", "127.0.0.1"]', "{port}"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "8000"]', "{port}"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}", "--name", "{user}"]', "{port}"),
    (GOOD + '\nsetup = "python -m x"', "setup"),
    (GOOD + '\nsetup = ["python", "-m", "x"]', "setup"),
    (GOOD + '\nsetup = [["python", "{port}"]]', "setup"),
    (GOOD + '\nshell = true', "takes"),
    (GOOD + '\n[preview.environment]\nA = 1', "text"),
    (GOOD + '\n[preview.environment]\nPATH = "x"', "environment"),
    (GOOD + '\n[preview.environment]\nUV_INDEX_URL = "x"', "environment"),
    (GOOD + '\n[preview.environment]\nPYTHONPATH = "x"', "environment"),
    (GOOD + '\n[preview.environment]\nUSERPROFILE = "x"', "environment"),
    (GOOD + '\n[preview.environment]\nLD_PRELOAD = "x"', "environment"),
    (GOOD + '\n[preview.environment]\nlower = "x"', "environment"),
    (GOOD + '\n[preview.environment]\nHTTPS_PROXY = "http://evil:1"', "environment"),
    (GOOD + '\n[preview.environment]\nPIP_INDEX_URL = "http://x/"', "environment"),
    (GOOD + '\n[preview.environment]\nSSL_CERT_FILE = "x"', "environment"),
    (GOOD + '\n[preview.environment]\nNODE_OPTIONS = "--require ./x.js"', "environment"),
    (GOOD + '\n[preview.environment]\nGIT_SSH_COMMAND = "x"', "environment"),
    (GOOD + '\n[preview.environment]\nGUNICORN_CMD_ARGS = "-b 0.0.0.0:80"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nGUNICORN_CMD_ARGS = "--bind=0.0.0.0:80"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nGUNICORN_CMD_ARGS = "-b 0:80"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nFLASK_RUN_HOST = "0.0.0.0"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nFLASK_RUN_HOST = "mypc"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nUVICORN_HOST = "0"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nHOST = "0"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nBIND = "mypc"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nGUNICORN_CMD_ARGS = "--bind=0"', "127.0.0.1"),
    (GOOD + '\n[preview.environment]\nGUNICORN_CMD_ARGS = "--bind mypc:8000"', "127.0.0.1"),
])
def test_a_declaration_that_could_escape_is_not_valid(text, reason):
    found = settings.preview({"text": f"[preview]\n{text}\n"})
    assert "invalid" in found and reason in found["invalid"], found


def test_the_shape_in_the_documentation_is_valid():
    text = '''
    [preview]
    setup = [["python", "-m", "app.demo.generate"]]
    run = ["uvicorn", "app.main:app", "--no-proxy-headers", "--host", "127.0.0.1", "--port", "{port}"]

    [preview.environment]
    APP_ENVIRONMENT = "development"
    '''
    assert settings.preview({"text": textwrap.dedent(text)}) == {
        "setup": [["python", "-m", "app.demo.generate"]],
        "run": ["uvicorn", "app.main:app", "--no-proxy-headers", "--host", "127.0.0.1", "--port", "{port}"],
        "environment": {"APP_ENVIRONMENT": "development"}}


@pytest.mark.parametrize("run", [
    '["gunicorn", "--bind", "127.0.0.1:{port}"]', '["gunicorn", "--bind=127.0.0.1:{port}"]',
    '["x", "--host=127.0.0.1", "--port={port}"]', '["python", "-m", "app.server", "--host", "127.0.0.1", "--port", "{port}"]',
    '["python", "app/main.py", "--host", "127.0.0.1", "--port", "{port}"]',
    '["flask", "--app", "app", "run", "--host", "127.0.0.1", "--port", "{port}"]',
    '["gunicorn", "-b", "127.0.0.1:{port}", "a:b"]', '["python", "manage.py", "runserver", "127.0.0.1:{port}"]',
    '["uvicorn", "a:b", "--host", "127.0.0.1", "--port", "{port}", "--root-path=/v1.2.3.4", "--workers", "0"]',
])
def test_other_ways_of_saying_this_computer_only_are_valid(run):
    assert "invalid" not in settings.preview({"text": f"[preview]\nrun = {run}\n"})


def test_ordinary_environment_values_are_valid():
    found = settings.preview({"text": f'[preview]\n{GOOD}\n[preview.environment]\nAPP_ENVIRONMENT = "development"\n'
                                      'FLASK_RUN_HOST = "127.0.0.1"\nGUNICORN_CMD_ARGS = "--workers 2"\n'
                                      'WEB_CONCURRENCY = "2"\nGREETING = "version 1.2 of the demo"\n'
                                      'DATABASE_URL = "postgresql://u@10.0.0.5/db"\nREDIS_URL = "redis://localhost:6379"\n'
                                      'SMTP_HOST = "smtp.example.test"\nAPP_VERSION = "1.2.3.4"\n'
                                      'API_ADDRESS = "https://api.example.test"\nAPP_TITLE = "Sales - b view"\n'})
    assert "invalid" not in found


@pytest.mark.parametrize("text", ['[test]\nbranch = "x"\n', "not toml ["])
def test_no_preview_section_is_no_declaration(text):
    assert settings.preview({"text": text}) is None or "invalid" in settings.preview({"text": text})
    assert settings.preview(None) is None


def test_the_settings_say_whether_a_preview_can_be_offered(signed_in, workspaces, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids))
    assert tools._specialist_settings(name)["preview"]["available"] is False
    monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"app_preview": True}))
    assert tools._specialist_settings(name)["preview"]["available"] is True


# --- what it runs -----------------------------------------------------------------------------------------------

def test_a_blocked_audit_refuses_and_nothing_runs(signed_in, workspaces, turned_on, browser, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids))
    blocked = {"verdict": "blocked", "files": ["uv.lock"], "packages": 1, "not_pinned": [], "without_hashes": [],
               "blocked": [{"ecosystem": "pypi", "package": "evil", "version": "1", "files": ["uv.lock"],
                            "reasons": ["known vulnerabilities: GHSA-xxxx"]}]}
    monkeypatch.setattr(deps, "audit", lambda folder: blocked)
    answer = show(name)
    assert answer["status"] == "audit_refused" and "evil" in answer["user_message"] and "GHSA" not in answer["user_message"]
    assert not pids.exists() and browser == [] and folders() == []


def test_an_audit_that_cannot_run_refuses(signed_in, workspaces, turned_on, browser, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids))

    def down(folder):
        raise support.Unreachable()

    monkeypatch.setattr(deps, "audit", down)
    assert show(name)["status"] == "audit_unavailable" and not pids.exists() and browser == []


def test_it_audits_the_copy_that_would_run(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, ws = project(signed_in, declaration(pids))
    read = []

    def audit(folder):
        read.append(sorted(p.name for p in Path(folder).iterdir()))
        return {"verdict": "blocked", "files": [], "packages": 0, "blocked": [], "not_pinned": ["x"]}

    monkeypatch.setattr(deps, "audit", audit)
    (ws / "only-in-the-folder.txt").write_bytes(b"x")
    show(name)
    assert "app.py" in read[0] and "only-in-the-folder.txt" not in read[0]


def test_without_a_lockfile_it_refuses(signed_in, workspaces, turned_on, browser, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids), lock=False)
    monkeypatch.setattr(deps, "audit", lambda folder: {"verdict": "allowed", "files": [], "packages": 0, "blocked": [],
                                                       "not_pinned": []})
    answer = show(name)
    assert answer["status"] == "no_lockfile" and not pids.exists() and browser == []


def test_nothing_saved_is_a_mistake_in_the_call(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids))
    monkeypatch.setattr(gitops, "saved_head", lambda workspace: (_ for _ in ()).throw(PermissionError("nothing saved")))
    assert "error" in tools.app_preview(name)


def test_a_turned_on_setting_must_be_exactly_true(signed_in, workspaces, browser, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids))
    for value in ("false", "yes", 1):
        monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"app_preview": value}))
        assert tools.app_preview(name)["status"] == "not_turned_on"
        assert tools._specialist_settings(name)["preview"]["available"] is False


def table(*lines: str) -> list[str]:
    return ["Active connections", "  Proto  Local Address  Foreign Address  State  PID", *lines]


@pytest.mark.parametrize("lines, tree, port, beyond", [
    (["  TCP  127.0.0.1:8000  0.0.0.0:0  LISTENING  10"], {10}, 8000, False),
    (["  TCP  [::1]:8000  [::]:0  LISTENING  10"], {10}, 8000, False),
    (["  TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  10"], {10}, 8000, True),
    (["  TCP  [::]:8000  [::]:0  LISTENING  10"], {10}, 8000, True),
    (["  TCP  0.0.0.0:9000  0.0.0.0:0  LISTENING  10"], {10}, 8000, True),  # another port of the tree
    (["  TCP  0.0.0.0:9000  0.0.0.0:0  LISTENING  11"], {10}, 8000, False),  # someone else's
    (["  TCP  0.0.0.0:8000  0.0.0.0:0  EN ESCUCHA  10"], {10}, 8000, True),  # a state of two words
    (["  TCP  192.168.1.5:8000  1.2.3.4:443  ESTABLISHED  10"], {10}, 8000, False),
])
def test_the_listening_table_of_windows_is_read_in_any_language(lines, tree, port, beyond):
    assert preview._windows_beyond(table(*lines), port, tree) is beyond


LINUX_TABLE = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
               "   0: {address}:1F90 00000000:0000 {state} 00000000:00000000 00:00000000 00000000  1000        0 1\n")


@pytest.mark.parametrize("address, state, beyond", [
    ("0100007F", "0A", False), ("00000000", "0A", True), ("0101007F", "0A", True), ("0501A8C0", "0A", True),
    ("00000000", "01", False), ("00000000000000000000000001000000", "0A", False),
    ("0000000000000000FFFF00000100007F", "0A", False), ("00000000000000000000000000000000", "0A", True),
])
def test_the_listening_table_of_linux_is_read_not_guessed(address, state, beyond):
    """A host name that resolves to 127.0.1.1 used to be skipped."""
    assert preview._linux_beyond([LINUX_TABLE.format(address=address, state=state)], 0x1F90) is beyond


def test_a_decoy_host_option_stays_for_the_listening_table():
    """A word the connector cannot know the meaning of is left to what the system says is listening."""
    assert "invalid" not in settings.preview({"text": f'[preview]\nrun = ["jupyter", "lab", "--ip", "0", "--host", '
                                                      '"127.0.0.1", "--port", "{port}"]\n'})


@pytest.mark.parametrize("program", ["pip", "pip3", "pip3.13", "PIP3.13.EXE", "uv", "uvx.exe"])
def test_what_changes_the_installation_is_never_a_console_script(tmp_path, program):
    dist = tmp_path / "environment" / "Lib" / "site-packages" / "pip-25.dist-info"
    dist.mkdir(parents=True)
    (dist / "entry_points.txt").write_text("[console_scripts]\npip = a\npip3 = a\npip3.13 = a\nuv = a\nuvx = a\n")
    current = preview._Preview("no-installers", "0" * 40)
    try:
        current.environment_folder = tmp_path / "environment"
        with pytest.raises(support.NeedsIT, match="console script"):
            preview._check_programs(current, {"setup": [], "run": [program]})
    finally:
        current.close()


def test_uvicorn_is_not_mistaken_for_uv(tmp_path):
    dist = tmp_path / "environment" / "Lib" / "site-packages" / "uvicorn-1.dist-info"
    dist.mkdir(parents=True)
    (dist / "entry_points.txt").write_text("[console_scripts]\nuvicorn = a\n")
    current = preview._Preview("uvicorn-is-fine", "0" * 40)
    try:
        current.environment_folder = tmp_path / "environment"
        preview._check_programs(current, {"setup": [], "run": ["uvicorn"]})
    finally:
        current.close()


def test_a_task_in_the_cloud_is_refused_by_the_guard(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    for tool in ("app_preview", "app_preview_stop"):
        found = guard.decide({"tool_name": f"mcp__plugin_eunomai-business_eunomai-business__{tool}", "tool_input": {}})
        assert "in the cloud" in found


def test_the_guard_covers_both_tools():
    import re
    template = Path(__file__).parents[2] / "plugin" / "hooks" / "hooks.json.template"
    matcher = json.loads(template.read_text().replace("{{PLUGIN}}", "eunomai-business"))["hooks"]["PreToolUse"][0]["matcher"]
    assert re.search(matcher, "mcp__plugin_eunomai-business_eunomai-business__app_preview")
    assert re.search(matcher, "mcp__eunomai-business__app_preview_stop")


# --- the real thing ------------------------------------------------------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_it_shows_the_saved_version_in_the_browser_and_stops(signed_in, workspaces, turned_on, browser, pids):
    name, _ = project(signed_in, declaration(pids))
    answer = show(name)
    assert answer["status"] == "ready" and answer["url"].startswith("http://127.0.0.1:")
    assert browser == [answer["url"]] and answer["user_message"] and answer["minutes"] == 60
    assert httpx.get(answer["url"]).text.strip() == "saved"
    numbers = json.loads(pids.read_text())
    assert all(alive(number) for number in numbers)
    folder = folders()[0]
    assert folder.exists() and not folder.is_relative_to(workspaces)
    stopped = tools.app_preview_stop(name)
    assert stopped["status"] == "stopped" and stopped["user_message"]
    assert gone(*numbers), "a process survived the stop"
    assert not folder.exists()
    with pytest.raises(httpx.TransportError):
        httpx.get(answer["url"], timeout=1)
    assert tools.app_preview_stop(name)["status"] == "not_running"


@pytest.mark.preview
@needs_uv
def test_unsaved_changes_do_not_run(signed_in, workspaces, turned_on, pids):
    name, ws = project(signed_in, declaration(pids))
    (ws / "message.txt").write_bytes(b"unsaved\n")
    (ws / "app.py").write_bytes(b"raise SystemExit('the file the sandbox just wrote ran')\n")
    answer = show(name)
    assert answer["status"] == "ready" and answer["unsaved_changes"] is True
    assert httpx.get(answer["url"]).text.strip() == "saved"


@pytest.mark.preview
@needs_uv
def test_the_environment_has_no_secret(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids))
    for variable in ("MY_SECRET_TOKEN", "GITHUB_TOKEN", "DATABASE_URL", "AWS_SECRET_ACCESS_KEY", "UV_INDEX_URL",
                     "PIP_INDEX_URL", "PYTHONPATH", "PYTHONHOME", "HTTPS_PROXY"):
        monkeypatch.setenv(variable, "http://user:secret-value@example.invalid/")
    monkeypatch.setenv("EUNOMAI_SUPPORT_EMAIL", "secret-value@example.invalid")
    answer = show(name)
    assert answer["status"] == "ready", answer
    seen = httpx.get(answer["url"] + "env").json()
    assert "secret-value" not in json.dumps(seen)
    assert not [key for key in seen if key.startswith("EUNOMAI_") or "TOKEN" in key or "SECRET" in key]
    assert seen["APP_ENVIRONMENT"] == "development"
    assert Path(seen["UV_PROJECT_ENVIRONMENT"]).is_relative_to(preview._keep(name))
    profile = str(Path.home())
    assert profile not in (seen.get("USERPROFILE"), seen.get("HOME"), seen.get("APPDATA"), seen.get("LOCALAPPDATA"))
    allowed = {"APP_ENVIRONMENT", "PIDS_FILE", "APP_MODE", "UV_PROJECT_ENVIRONMENT", "UV_CACHE_DIR",
               "UV_PYTHON_INSTALL_DIR", "PATH", "PATHEXT", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP",
               "TMP", "TMPDIR", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "NO_COLOR", "LANG", "LC_ALL",
               "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "TZ",
               "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",  # where a browser the computer has is found
               # uv's own, on what it runs; Python's own on Windows; every one a name no organization's secret has
               "UV", "UV_RUN_RECURSION_DEPTH", "VIRTUAL_ENV", "__CF_USER_TEXT_ENCODING", "PWD", "LC_CTYPE", "SHLVL"}
    assert set(seen) <= allowed, set(seen) - allowed


def evil_package(root: Path, marker: Path) -> Path:
    """A local package no lockfile of the project's names, whose build leaves a mark. Nothing leaves this computer."""
    package = root / "evilpkg"
    (package / "evilpkg").mkdir(parents=True)
    (package / "evilpkg" / "__init__.py").write_text("VALUE = 'unaudited package imported'\n", encoding="utf-8")
    (package / "pyproject.toml").write_text('[project]\nname = "evilpkg"\nversion = "1.0"\n[build-system]\nrequires = []\n'
                                            'build-backend = "b"\nbackend-path = ["."]\n', encoding="utf-8", newline="\n")
    (package / "b.py").write_text(textwrap.dedent(f"""\
        import pathlib, zipfile
        pathlib.Path({marker.as_posix()!r}).write_text("code ran at installation")
        META = "Metadata-Version: 2.1\\nName: evilpkg\\nVersion: 1.0\\n"
        WHEEL = "Wheel-Version: 1.0\\nGenerator: x\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n"
        def get_requires_for_build_wheel(c=None): return []
        def prepare_metadata_for_build_wheel(d, c=None):
            p = pathlib.Path(d) / "evilpkg-1.0.dist-info"; p.mkdir()
            (p / "METADATA").write_text(META); (p / "WHEEL").write_text(WHEEL)
            return p.name
        def build_wheel(d, c=None, m=None):
            n = "evilpkg-1.0-py3-none-any.whl"
            with zipfile.ZipFile(pathlib.Path(d) / n, "w") as z:
                z.write("evilpkg/__init__.py")
                z.writestr("evilpkg-1.0.dist-info/METADATA", META)
                z.writestr("evilpkg-1.0.dist-info/WHEEL", WHEEL)
                z.writestr("evilpkg-1.0.dist-info/RECORD", "")
            return n
        """), encoding="utf-8", newline="\n")
    return package


def script_with_its_own_lockfile(folder: Path, package: Path, marker: Path) -> None:
    """How a saved version would do it: inline metadata, and `uv lock --script` beside the script."""
    (folder / "app.py").write_text(
        f'# /// script\n# requires-python = ">=3.12"\n# dependencies = ["evilpkg @ {package.as_uri()}"]\n# ///\n'
        + APP.decode().replace("import http.server,", "import evilpkg, http.server,"), encoding="utf-8", newline="\n")
    subprocess.run(["uv", "lock", "--script", "app.py", "--no-config"], cwd=folder, check=True, capture_output=True)
    assert (folder / "app.py.lock").exists()
    marker.unlink(missing_ok=True)


@pytest.mark.preview
@needs_uv
def test_a_script_with_its_own_lockfile_is_refused_end_to_end(signed_in, workspaces, turned_on, browser, pids, tmp_path):
    marker = tmp_path / "BUILD_BACKEND_RAN"
    name, ws = project(signed_in, declaration(pids))
    script_with_its_own_lockfile(ws, evil_package(tmp_path, marker), marker)
    gitops.save(name, "Inline metadata and a lockfile beside the script")
    answer = show(name)
    assert answer["status"] == "audit_refused" and browser == [] and not pids.exists() and not marker.exists()


@pytest.mark.preview
@needs_uv
def test_even_past_the_audit_the_unaudited_package_does_not_run(signed_in, workspaces, turned_on, browser, pids,
                                                                tmp_path, monkeypatch):
    """Two more layers: `python app.py` ignores a script's metadata, and uv may not build anything."""
    marker = tmp_path / "BUILD_BACKEND_RAN"
    name, ws = project(signed_in, declaration(pids))
    script_with_its_own_lockfile(ws, evil_package(tmp_path, marker), marker)
    gitops.save(name, "Inline metadata and a lockfile beside the script")
    monkeypatch.setattr(deps, "audit", lambda folder: {"verdict": "allowed", "files": [], "packages": 0, "blocked": [],
                                                       "not_pinned": []})
    answer = show(name)
    assert answer["status"] == "needs_it" and "evilpkg" in answer["it_report"], answer
    assert browser == [] and not marker.exists()


@pytest.mark.preview
@needs_uv
def test_uv_refuses_to_build_what_a_script_asks_for(tmp_path):
    """The script form itself, had it been declared: `--no-sync` does not cover it, `--no-build` does."""
    marker = tmp_path / "BUILD_BACKEND_RAN"
    app = tmp_path / "app"
    app.mkdir()
    (app / "pyproject.toml").write_bytes(PYPROJECT)
    (app / "uv.lock").write_bytes(LOCK)
    script_with_its_own_lockfile(app, evil_package(tmp_path, marker), marker)
    run = subprocess.run(["uv", *preview._RUN, "app.py", "--host", "127.0.0.1", "--port", "1"], cwd=app,
                         capture_output=True, text=True, timeout=120,
                         env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(tmp_path / "env"),
                              "UV_CACHE_DIR": str(tmp_path / "cache"), "PIDS_FILE": str(tmp_path / "p")})
    assert run.returncode != 0 and not marker.exists(), run.stderr


@pytest.mark.preview
@needs_uv
@pytest.mark.parametrize("program", ["sh", "cmd", "powershell", "mshta", "schtasks", "pip", "pythonw", "activate", "uv"])
def test_a_program_that_is_no_packages_console_script_does_not_run(signed_in, workspaces, turned_on, browser, pids,
                                                                   program):
    name, _ = project(signed_in, declaration(pids, f'["{program}", "/c", "x"]'))
    answer = show(name)
    assert answer["status"] == "needs_it" and "console script" in answer["it_report"], answer
    assert not pids.exists() and browser == [] and folders() == []
    run = f'["{program}", "--host", "127.0.0.1", "--port", "{{port}}"]'
    other, _ = project(signed_in, declaration(pids, run=run))
    assert show(other)["status"] == "needs_it" and not pids.exists()


@pytest.mark.preview
@needs_uv
def test_the_console_script_of_a_package_in_the_lock_is_allowed(tmp_path):
    environment = tmp_path / "environment" / "Lib" / "site-packages" / "uvicorn-0.54.dist-info"
    environment.mkdir(parents=True)
    (environment / "entry_points.txt").write_text("[console_scripts]\nuvicorn = uvicorn.main:main\n\n[other]\nx = y\n")
    assert preview._console_scripts(tmp_path / "environment") == {"uvicorn"}


@pytest.mark.preview
@needs_uv
def test_the_run_path_holds_no_system_folder(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids))
    answer = show(name)
    seen = httpx.get(answer["url"] + "env").json()
    assert answer["status"] == "ready"
    assert "system32" not in seen["PATH"].lower() and seen["PATH"].count(os.pathsep) <= 1
    if sys.platform != "win32":
        assert "/usr/bin" not in seen["PATH"]


@pytest.mark.preview
@needs_uv
def test_setup_steps_run_before_the_application(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids, '["python", "generate.py"]'))
    answer = show(name)
    assert httpx.get(answer["url"]).text == "generated"


@pytest.mark.preview
@needs_uv
def test_a_setup_step_that_fails_is_told_plainly_and_kept_for_it(signed_in, workspaces, turned_on, browser, pids):
    name, _ = project(signed_in, declaration(pids, '["python", "fail.py"]'))
    answer = show(name)
    assert answer["status"] == "needs_it" and "setup broke" in answer["it_report"]
    assert "setup broke" not in answer["user_message"] and "fail.py" not in answer["user_message"]
    assert browser == [] and not pids.exists() and folders() == []


@pytest.mark.preview
@needs_uv
def test_an_application_that_does_not_start_is_told_plainly(signed_in, workspaces, turned_on, browser, pids):
    name, _ = project(signed_in, declaration(pids, mode="exit"))
    answer = show(name)
    assert answer["status"] == "needs_it" and "could not start" in answer["it_report"] and browser == []
    assert "could not start" not in answer["user_message"]
    assert gone(*json.loads(pids.read_text()))


@pytest.mark.preview
@needs_uv
@pytest.mark.parametrize("mode", ["everywhere", pytest.param("second", marks=pytest.mark.skipif(
    sys.platform != "win32", reason="elsewhere the table is read for the application's port"))])
def test_an_application_that_answers_beyond_this_computer_is_stopped(signed_in, workspaces, turned_on, browser, pids,
                                                                     mode):
    name, _ = project(signed_in, declaration(pids, mode=mode))
    answer = show(name)
    assert answer["status"] == "needs_it" and "beyond this computer" in answer["it_report"] and browser == []
    assert gone(*json.loads(pids.read_text())) and folders() == []


@pytest.mark.preview
@needs_uv
def test_a_step_that_fails_between_two_calls_is_still_told(signed_in, workspaces, turned_on, pids, monkeypatch):
    """The tool answers `starting` while it works; the failure must reach the next call, not start it all again."""
    monkeypatch.setattr(preview, "_ANSWER_WAIT", 0.0)
    name, _ = project(signed_in, declaration(pids, '["python", "fail.py"]'))
    assert tools.app_preview(name)["status"] == "starting"
    deadline = time.time() + 30
    while preview._key(name) in preview._previews and time.time() < deadline:
        time.sleep(0.05)
    answer = show(name)
    assert answer["status"] == "needs_it" and "setup broke" in answer["it_report"]
    assert preview._key(name) not in preview._unread


@pytest.mark.preview
@needs_uv
def test_a_preview_followed_call_by_call_ends_ready(signed_in, workspaces, turned_on, browser, pids, monkeypatch):
    monkeypatch.setattr(preview, "_ANSWER_WAIT", 0.0)
    name, _ = project(signed_in, declaration(pids))
    answer = show(name)
    assert answer["status"] == "ready" and len(browser) == 1


@pytest.mark.preview
@needs_uv
def test_at_the_time_limit_it_stops_by_itself(signed_in, workspaces, turned_on, pids, monkeypatch):
    monkeypatch.setattr(preview, "TIME_LIMIT", 6)
    name, _ = project(signed_in, declaration(pids))
    assert show(name)["status"] == "ready"
    numbers, folder = json.loads(pids.read_text()), folders()[0]
    assert gone(*numbers, wait=20), "a process survived the time limit"
    deadline = time.time() + 15
    while (preview._key(name) in preview._previews or folder.exists()) and time.time() < deadline:
        time.sleep(0.1)  # the watcher removes the folder after the processes end
    assert not folder.exists()
    assert tools.app_preview_stop(name)["status"] == "not_running"


@pytest.mark.preview
@needs_uv
def test_the_time_limit_is_sixty_minutes():
    assert preview.TIME_LIMIT == 60 * 60


@pytest.mark.preview
@needs_uv
def test_one_preview_per_workspace_a_new_one_replaces_the_old(signed_in, workspaces, turned_on, pids):
    name, ws = project(signed_in, declaration(pids))
    first = show(name)
    numbers, folder = json.loads(pids.read_text()), folders()[0]
    pids.unlink()
    (ws / "message.txt").write_bytes(b"second\n")
    gitops.save(name, "A new message")
    second = show(name)
    assert httpx.get(second["url"]).text.strip() == "second"
    assert gone(*numbers) and not folder.exists() and len(folders()) == 1


@pytest.mark.preview
@needs_uv
def test_asking_again_for_the_same_version_reopens_it_without_starting_another(signed_in, workspaces, turned_on,
                                                                               browser, pids):
    name, _ = project(signed_in, declaration(pids))
    first = show(name)
    numbers = json.loads(pids.read_text())
    again = tools.app_preview(name)
    assert again["url"] == first["url"] and json.loads(pids.read_text()) == numbers
    assert browser == [first["url"], first["url"]]


@pytest.mark.preview
@needs_uv
def test_an_application_that_dies_leaves_nothing_behind(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids))
    assert show(name)["status"] == "ready"
    numbers, folder = json.loads(pids.read_text()), folders()[0]
    pids.unlink()
    os.kill(numbers[0], signal.SIGKILL if sys.platform != "win32" else signal.SIGTERM)
    assert gone(numbers[0]) and wait_gone(folder, 20), "the watcher did not notice"
    state = preview._state_file(name)
    deadline = time.time() + 10
    while state.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert not state.exists() and folders() == []
    answer = show(name)
    assert answer["status"] == "ready" and answer["ended_before"] == "application" and not answer["already_running"]
    assert "stopped by itself" in answer["user_message"] and httpx.get(answer["url"]).text.strip() == "saved"


@pytest.mark.preview
@needs_uv
def test_an_application_that_died_is_nothing_to_stop(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids))
    assert show(name)["status"] == "ready"
    number, folder = json.loads(pids.read_text())[0], folders()[0]
    os.kill(number, signal.SIGKILL if sys.platform != "win32" else signal.SIGTERM)
    assert wait_gone(folder, 20)
    deadline = time.time() + 10
    while preview._state_file(name).exists() and time.time() < deadline:
        time.sleep(0.05)
    assert tools.app_preview_stop(name)["status"] == "not_running"


HARNESS = textwrap.dedent('''\
    import json, sys, time
    from pathlib import Path

    from eunomai_business import preview

    preview.webbrowser.open = lambda url: True
    source, name, pids = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    run = ["python", "app.py", "--host", "127.0.0.1", "--port", "{port}"]
    current = preview._Preview(name, "0" * 40)
    preview._previews[preview._key(name)] = current
    preview.shutil.copytree(source, current.app, dirs_exist_ok=True)
    preview._bring_up(current, {"setup": [["python", "leave.py"]], "run": run,
                                "environment": {"PIDS_FILE": pids, "LEFT_FILE": pids + ".left"}})
    state = json.loads(preview._state_file(name).read_text())
    print(json.dumps({"folder": str(current.folder), "url": current.url, "watcher": state["watcher"]}), flush=True)
    sys.stdin.read()
    ''')


def connector_with_a_preview(tmp_path, name: str) -> tuple[subprocess.Popen, dict, list[int]]:
    """A connector of its own, in a process of its own: what Claude Desktop starts and later closes."""
    source = tmp_path / "source"
    source.mkdir()
    for file, content in {"pyproject.toml": PYPROJECT, "uv.lock": LOCK, "app.py": APP, "message.txt": b"x",
                          "leave.py": LEAVE}.items():
        (source / file).write_bytes(content)
    harness = tmp_path / "harness.py"
    harness.write_text(HARNESS, encoding="utf-8")
    pids = tmp_path / "harness-pids.json"
    process = subprocess.Popen([sys.executable, str(harness), str(source), name, str(pids)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
    line = process.stdout.readline()
    assert line, "the connector did not bring the preview up"
    left = int(Path(str(pids) + ".left").read_text())
    return process, json.loads(line), [*json.loads(pids.read_text()), left]


def wait_gone(folder: Path, wait: float = 30.0) -> bool:
    deadline = time.time() + wait
    while folder.exists() and time.time() < deadline:
        time.sleep(0.1)
    return not folder.exists()


def end_preview(name: str) -> None:
    assert preview._end(preview._state_file(name))


def kill_watcher(number: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(number)], capture_output=True)
    else:
        os.kill(number, 9)


@pytest.mark.preview
@needs_uv
@pytest.mark.parametrize("how", ["closed", "killed"])
def test_a_connector_that_ends_leaves_the_preview_running(tmp_path, how):
    """Closed: its input ends, as when a host closes it. Killed: nothing of it runs any more. In Cowork, every turn."""
    process, started, numbers = connector_with_a_preview(tmp_path, f"exit-{how}")
    if how == "closed":
        process.stdin.close()
    else:
        process.kill()
    process.wait(timeout=30)
    time.sleep(1.5)
    assert all(alive(number) for number in numbers) and httpx.get(started["url"]).status_code == 200
    preview._sweep()  # its connector is gone, and it is healthy
    assert Path(started["folder"]).exists() and alive(started["watcher"])
    end_preview(f"exit-{how}")
    assert gone(*numbers, wait=20) and not Path(started["folder"]).exists()


@pytest.mark.preview
@needs_uv
@pytest.mark.skipif(sys.platform != "win32", reason="a job object")
def test_with_the_watcher_gone_the_job_ends_everything(tmp_path):
    """Only the watcher holds the job, so that no process outlives what looks after it."""
    process, started, numbers = connector_with_a_preview(tmp_path, "watcher-only")
    try:
        kill_watcher(started["watcher"])
        assert gone(*numbers, wait=20), "a process outlived the watcher"
        preview._sweep()
        assert not Path(started["folder"]).exists() and not preview._state_file("watcher-only").exists()
    finally:
        process.kill()
        process.wait(timeout=30)


@pytest.mark.skipif(sys.platform != "win32", reason="a job object")
def test_the_job_has_no_name_for_anything_in_it_to_open():
    """A process that opened the job by name kept KILL_ON_CLOSE from firing. Nothing names it."""
    assert "CreateJobObjectW(None, None)" in Path(watcher.__file__).read_text(encoding="utf-8")


@pytest.mark.preview
@needs_uv
def test_another_connector_on_the_same_workspace_can_end_it(tmp_path):
    process, started, numbers = connector_with_a_preview(tmp_path, "shared")
    try:
        end_preview("shared")
        assert gone(*numbers, wait=20), "the other connector's preview survived"
        assert not Path(started["folder"]).exists()
    finally:
        process.kill()
        process.wait(timeout=30)


@pytest.mark.preview
@needs_uv
def test_with_the_watcher_dead_a_stop_ends_what_is_left_and_says_what_is_true(tmp_path):
    process, started, numbers = connector_with_a_preview(tmp_path, "watcher-gone")
    try:
        kill_watcher(started["watcher"])
        state = preview._state_file("watcher-gone")
        deadline = time.time() + 10
        while preview._watching(state) and time.time() < deadline:
            time.sleep(0.05)
        answer = preview.stop("watcher-gone")
        assert gone(*numbers, wait=20), "something outlived the watcher and the stop"
        assert answer["status"] == ("not_running" if sys.platform == "win32" else "stopped"), answer
        assert not Path(started["folder"]).exists() and not state.exists()
    finally:
        process.kill()
        process.wait(timeout=30)


@pytest.mark.preview
@needs_uv
def test_a_preparation_ends_with_the_connector_that_asked_for_it(tmp_path):
    """Nobody would ever hear of it, and the next call starts again."""
    current = preview._Preview("cut-short", "0" * 40)
    state = preview._state_file("cut-short")
    assert preview._read_state(state)["phase"] == "preparing" and preview._watching(state)
    current.pipe.stdin.close()
    deadline = time.time() + 20
    while preview._watching(state) and time.time() < deadline:
        time.sleep(0.05)
    assert not preview._watching(state) and not current.folder.exists() and not state.exists()
    current.closed = True


def test_a_number_that_came_back_as_another_process_is_not_a_watcher(tmp_path):
    """The state names this very test as the watcher, alive and well; no lock is held, so nothing watches."""
    left = tmp_path / f"{preview._PREFIX}reused"
    left.mkdir()
    state = preview._state_file("reused")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"workspace": "reused", "folder": str(left), "watcher": os.getpid(), "token": "t",
                                 "groups": []}))
    state.with_suffix(".alive").touch()
    assert not preview._watching(state)
    preview._sweep()
    assert not left.exists() and not state.exists() and not state.with_suffix(".alive").exists()


def test_a_preview_nothing_could_find_again_ends():
    """Someone removes the connector's folder: no tool could reach it, and it would run out its hour unseen."""
    current = preview._Preview("lost", "0" * 40)
    state = preview._state_file("lost")
    state.unlink()
    deadline = time.time() + 20
    while preview._watching(state) and time.time() < deadline:
        time.sleep(0.05)
    assert not preview._watching(state) and not current.folder.exists()
    current.close()


def test_a_live_watcher_is_left_alone_whoever_its_connector_was():
    current = preview._Preview("healthy", "0" * 40)
    try:
        preview._sweep()
        assert current.folder.exists() and preview._watching(preview._state_file("healthy"))
    finally:
        current.close()


def test_a_folder_nothing_speaks_of_goes_once_it_is_old(monkeypatch):
    young = Path(preview.tempfile.mkdtemp(prefix=preview._PREFIX))
    old = Path(preview.tempfile.mkdtemp(prefix=preview._PREFIX))
    try:
        os.utime(old, (time.time() - preview._STALE - 60,) * 2)
        preview._sweep()
        assert young.exists() and not old.exists()
    finally:
        shutil.rmtree(young, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)


def test_nothing_ends_a_preview_at_a_connectors_exit():
    source = Path(preview.__file__).read_text(encoding="utf-8")
    assert "atexit" not in source and "stop_all" not in source


@pytest.mark.preview
@needs_uv
def test_a_time_limit_that_passed_is_told_and_it_starts_again(signed_in, workspaces, turned_on, pids, monkeypatch):
    monkeypatch.setattr(preview, "TIME_LIMIT", 4)
    name, _ = project(signed_in, declaration(pids))
    assert show(name)["status"] == "ready"
    numbers = json.loads(pids.read_text())
    assert gone(*numbers, wait=20)
    deadline = time.time() + 10
    while preview._state_file(name).exists() and time.time() < deadline:
        time.sleep(0.05)
    monkeypatch.setattr(preview, "TIME_LIMIT", 60)
    pids.unlink()
    answer = show(name)
    assert answer["status"] == "ready" and answer["ended_before"] == "time_limit", answer


@pytest.mark.preview
@needs_uv
def test_a_stop_file_left_behind_does_not_end_the_next_preview(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids))
    stop_file = preview._state_file(name).with_suffix(".stop")
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.touch()
    answer = show(name)
    assert answer["status"] == "ready"
    time.sleep(1)
    assert httpx.get(answer["url"]).text.strip() == "saved"


@pytest.mark.preview
@needs_uv
def test_grafts_that_hide_a_forged_commit_do_not_run(signed_in, workspaces, turned_on, browser, pids):
    from dulwich.object_store import commit_tree_changes
    from dulwich.objects import Blob
    from dulwich.repo import Repo

    name, ws = project(signed_in, declaration(pids))
    with Repo(str(ws)) as repo:
        blob = Blob.from_string(b"planted\n")
        repo.object_store.add_object(blob)
        tree = commit_tree_changes(repo.object_store, repo[repo[repo.head()].tree], [(b"run.bat", 0o100644, blob.id)])
        commit = repo[repo.head()]
        parent = repo.head()
        commit.tree, commit.parents = getattr(tree, "id", tree), [parent]
        repo.object_store.add_object(commit)
        repo.refs[b"refs/heads/draft/work"] = commit.id
        forged = commit.id.decode()
    main = signed_in.repos[name].refs[b"refs/heads/main"].decode()
    (ws / ".git" / "info").mkdir(exist_ok=True)
    (ws / ".git" / "info" / "grafts").write_text(f"{main} {parent.decode()} {forged}\n{forged} {parent.decode()}\n")
    answer = show(name)
    assert answer["status"] == "needs_it" and browser == [] and not pids.exists()


@pytest.mark.preview
@needs_uv
def test_a_child_a_setup_step_left_stops_with_the_preview(signed_in, workspaces, turned_on, tmp_path, pids):
    """Each step had a process group of its own, and only the last was remembered."""
    left = tmp_path / "left.txt"
    text = declaration(pids, '["python", "leave.py"]') + f'LEFT_FILE = "{left.as_posix()}"\n'.encode()
    name, ws = project(signed_in, text)
    (ws / "leave.py").write_bytes(LEAVE)
    gitops.save(name, "A step that leaves a child")
    assert show(name)["status"] == "ready"
    child = int(left.read_text())
    assert alive(child)
    tools.app_preview_stop(name)
    assert gone(child), "a child of a setup step survived the stop"


@pytest.mark.preview
@needs_uv
@pytest.mark.skipif(sys.platform == "win32", reason="process groups")
def test_the_groups_of_every_step_still_alive_are_in_the_state(signed_in, workspaces, turned_on, tmp_path, pids):
    text = declaration(pids, '["python", "leave.py"]') + f'LEFT_FILE = "{(tmp_path / "left").as_posix()}"\n'.encode()
    name, ws = project(signed_in, text)
    (ws / "leave.py").write_bytes(LEAVE)
    gitops.save(name, "A step that leaves a child")
    assert show(name)["status"] == "ready"
    assert len(json.loads(preview._state_file(name).read_text())["groups"]) >= 2


@pytest.mark.parametrize("marker, called", [("right", True), ("wrong", False), (None, False)])
def test_a_process_group_is_killed_only_while_the_preview_is_still_there(tmp_path, monkeypatch, marker, called):
    """After a reboot or long after, the number in a state file may be someone else's by now."""
    killed = []
    monkeypatch.setattr(preview, "_end_groups", lambda groups, folder: killed.append(groups))
    folder = tmp_path / f"{preview._PREFIX}x"
    folder.mkdir()
    if marker:
        (folder / "live").write_text(marker)
    state = preview._state_file("group-check")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"folder": str(folder), "owner": 0, "token": "right", "groups": [4242]}))
    preview._clear(state)
    assert (killed == [[4242]]) is called and not state.exists() and not folder.exists()


def test_a_folder_already_gone_kills_nothing(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(preview, "_end_groups", lambda groups, folder: killed.append(groups))
    state = preview._state_file("group-gone")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"folder": str(tmp_path / f"{preview._PREFIX}y"), "owner": 0, "token": "t", "groups": [1]}))
    preview._clear(state)
    assert killed == [] and not state.exists()


@pytest.mark.parametrize("junk", ['{"group": "x", "owner": 0}', "[1]", '"x"', "null", "not json", "", '{"owner": "x"}',
                                  '{"folder": 1, "owner": 0, "groups": "x"}', '{"folder": "x", "owner": 0, "groups": [{}]}'])
def test_junk_in_a_state_file_never_blocks_a_preview(junk):
    state = preview._state_file("junk")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(junk)
    preview._sweep()
    assert not state.exists()
    state.write_text(junk)
    preview._clear(state)
    assert not state.exists()


def test_a_state_file_is_written_whole():
    """Another connector must never read half of one: it is written beside the real one and moved over it."""
    source = Path(watcher.__file__).read_text(encoding="utf-8")
    assert "replace_file(temporary, self.path)" in source
    current = preview._Preview("atomic", "0" * 40)
    try:
        assert json.loads(preview._state_file("atomic").read_text())["token"] == current.token
    finally:
        current.close()
    assert not list(preview._state_file("atomic").parent.glob("*.tmp"))


def test_an_application_that_drips_a_header_does_not_hold_the_check(monkeypatch):
    import socket
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    stop = threading.Event()

    def nothing_at_all():
        connection, _ = server.accept()
        stop.wait(20)
        connection.close()

    threading.Thread(target=nothing_at_all, daemon=True).start()
    began = time.time()
    assert preview._answers(port) is False and time.time() - began < 6
    stop.set()

    def drip():
        connection, _ = server.accept()
        connection.recv(4096)
        for byte in b"HTTP/1.1 200 OK\r\nX-Long: " + b"a" * 100:
            if stop.is_set():
                break
            connection.sendall(bytes([byte]))
            time.sleep(1.5)

    stop.clear()
    threading.Thread(target=drip, daemon=True).start()
    began = time.time()
    assert preview._answers(port) is True and time.time() - began < 6
    stop.set()
    server.close()


@pytest.mark.preview
@needs_uv
def test_the_time_limit_counts_from_when_it_starts_not_from_when_it_is_ready(signed_in, workspaces, turned_on, pids,
                                                                             monkeypatch):
    monkeypatch.setattr(preview, "TIME_LIMIT", 1)
    monkeypatch.setattr(preview, "_answers", lambda port: False)
    name, _ = project(signed_in, declaration(pids))
    began = time.time()
    assert show(name)["status"] == "needs_it" and time.time() - began < 30


@pytest.mark.skipif(sys.platform != "win32", reason="Windows takes both names for one folder")
@pytest.mark.preview
@needs_uv
def test_one_folder_is_one_preview_whatever_the_case_of_its_name(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids))
    first = show(name)
    second = show(name.upper())
    assert first["url"] == second["url"] and second["already_running"] is True and len(folders()) == 1
    assert tools.app_preview_stop(name.upper())["status"] == "stopped" and folders() == []


def test_every_kind_of_state_is_kept_by_the_folder_not_the_spelling(signed_in, workspaces, monkeypatch):
    name, ws = project(signed_in, declaration(Path("x")))
    assert gitops.key(name) == str(ws.resolve())
    if sys.platform == "win32":
        assert gitops.key(name.upper()) == gitops.key(name)


@pytest.mark.preview
@needs_uv
def test_an_old_failure_is_not_told_for_a_version_shown_again(signed_in, workspaces, turned_on, pids, monkeypatch):
    """A, B, A: the first A, stopped when B replaced it, must not answer for the last A."""
    import threading

    name, ws = project(signed_in, declaration(pids))
    a = gitops.saved_head(name)
    release, real = threading.Event(), preview._bring_up

    def slow(current, declared):
        if current.head == a and not release.is_set():
            release.wait(20)
            raise current.failed("run")
        return real(current, declared)

    monkeypatch.setattr(preview, "_bring_up", slow)
    monkeypatch.setattr(preview, "_ANSWER_WAIT", 0.0)
    assert tools.app_preview(name)["status"] == "starting"
    first = next(iter(preview._previews.values()))
    (ws / "message.txt").write_bytes(b"second\n")
    gitops.save(name, "B")
    assert tools.app_preview(name)["status"] == "starting"
    release.set()
    assert first.settled.wait(20)
    assert preview._key(name) not in preview._unread or preview._unread[preview._key(name)] is not first


@pytest.mark.preview
@needs_uv
def test_a_stop_during_the_copy_leaves_no_folder(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, _ = project(signed_in, declaration(pids))
    real = gitops.export_saved

    def export(workspace, target, *args):
        preview.stop(workspace)  # the stop lands here; the copy then writes the folder again
        return real(workspace, target, *args)

    monkeypatch.setattr(gitops, "export_saved", export)
    monkeypatch.setattr(preview, "_ANSWER_WAIT", 0.0)
    tools.app_preview(name)
    current = next(iter(preview._previews.values()), None)
    deadline = time.time() + 20
    while time.time() < deadline and any(p.name.startswith(preview._PREFIX) for p in _temporary()):
        time.sleep(0.1)
    assert not [p for p in _temporary() if p not in BEFORE_ANY_TEST]


def _temporary() -> list[Path]:
    return [p for p in Path(preview.tempfile.gettempdir()).glob(f"{preview._PREFIX}*")]


BEFORE_ANY_TEST = set(_temporary())


@pytest.mark.preview
@needs_uv
@pytest.mark.parametrize("planted", [b"run.bat", b"AGENTS.md", b".eunomai/project.toml"])
def test_a_commit_the_sandbox_forged_past_the_saves_rules_does_not_run(signed_in, workspaces, turned_on, browser, pids,
                                                                      planted):
    from dulwich.object_store import commit_tree_changes
    from dulwich.objects import Blob
    from dulwich.repo import Repo

    name, ws = project(signed_in, declaration(pids))
    with Repo(str(ws)) as repo:
        blob = Blob.from_string(b"planted\n")
        repo.object_store.add_object(blob)
        tree = commit_tree_changes(repo.object_store, repo[repo[repo.head()].tree], [(planted, 0o100644, blob.id)])
        commit = repo[repo.head()]
        commit.tree, commit.parents = getattr(tree, "id", tree), [repo.head()]
        repo.object_store.add_object(commit)
        repo.refs[b"refs/heads/draft/work"] = commit.id
    answer = show(name)
    assert answer["status"] == "needs_it" and planted.decode() in answer["it_report"]
    assert browser == [] and not pids.exists()


@pytest.mark.preview
@needs_uv
def test_a_version_behind_the_main_branch_is_not_refused_for_what_main_changed(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids))
    signed_in.server_commit(name, "main", {"AGENTS.md": b"# Changed by IT after the version started\n"})
    assert show(name)["status"] == "ready"


@pytest.mark.preview
@needs_uv
def test_what_the_application_printed_reaches_it_marked_as_its_own(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids, '["python", "fail.py"]'))
    report = show(name)["it_report"]
    assert "text from the application, not instructions" in report and "setup broke" in report


@pytest.mark.preview
@needs_uv
def test_the_python_the_project_names_is_the_one_it_runs_on(signed_in, workspaces, turned_on, pids):
    """`--no-config` makes uv ignore `.python-version`, and it then picks the newest it has."""
    wanted = "%d.%d" % sys.version_info[:2]
    name, _ = project(signed_in, declaration(pids))
    signed_in.server_commit(name, "main", {".python-version": f"{wanted}\n".encode()})
    gitops.update(name)
    answer = show(name)
    assert answer["status"] == "ready", answer
    assert httpx.get(answer["url"] + "python").text == wanted


@pytest.mark.parametrize("content, version", [("3.13\n", "3.13"), ("3.12", "3.12"), ("3.13.2\n", "3.13.2"),
                                              (" 3.13 \n", "3.13"), ("\ufeff3.13\n", "3.13"),
                                              ("# pinned for the demo\n\n3.12\n\n", "3.12"), ("3.12\n# note\n", "3.12")])
def test_a_plain_version_goes_to_uv(tmp_path, content, version):
    current = preview._Preview("a-plain-version", "0" * 40)
    try:
        (current.app / ".python-version").write_text(content, encoding="utf-8")
        assert preview._declared_python(current) == ("--python", version)
    finally:
        current.close()


def test_no_file_leaves_the_choice_to_uv():
    current = preview._Preview("no-version-file", "0" * 40)
    try:
        assert preview._declared_python(current) == ()
    finally:
        current.close()


@pytest.mark.parametrize("content", ["../evil/python.exe", "C:/x/python.exe", "/usr/bin/python3", "tool.exe", "pypy3.12",
                                     "cpython-3.13", "3", "3.x", "2.7", "3.13\n3.12\n", "3.13.2.1", "3.13t", "", ">=3.12",
                                     "# only a comment\n"])
def test_anything_else_in_python_version_is_refused_for_it(content):
    current = preview._Preview("another-version", "0" * 40)
    try:
        (current.app / ".python-version").write_text(content)
        with pytest.raises(support.NeedsIT, match="python-version"):
            preview._declared_python(current)
    finally:
        current.close()


@pytest.mark.preview
@needs_uv
def test_a_python_version_that_is_a_program_never_starts(signed_in, workspaces, turned_on, browser, pids):
    name, _ = project(signed_in, declaration(pids))
    signed_in.server_commit(name, "main", {".python-version": b"tool.exe\n"})
    gitops.update(name)
    answer = show(name)
    assert answer["status"] == "needs_it" and "python-version" in answer["it_report"]
    assert "IT" in answer["user_message"] and not pids.exists() and browser == [] and folders() == []


def test_the_base_applications_own_declaration_passes(tmp_path):
    """As IT wrote it, on a real project: a check that refuses this is the one that is wrong."""
    text = textwrap.dedent('''\
        [development]
        code = true
        technologies = ["Python", "FastAPI"]

        [preview]
        setup = [["python", "-m", "app.demo.generate"]]
        run = ["uvicorn", "app.main:app", "--no-proxy-headers", "--host", "127.0.0.1", "--port", "{port}"]

        [preview.environment]
        APP_ENVIRONMENT = "development"
        APP_DATABASE_URL = "sqlite:///.data/preview.db"
        APP_FAKE_IDENTITY = "true"
        APP_FAKE_GROUPS = '["demo-admins"]'
        APP_ROLE_GROUPS = '{"admin":["demo-admins"]}'
        ''')
    found = settings.preview({"text": text})
    assert "invalid" not in found, found
    assert found["run"][0] == "uvicorn" and found["environment"]["APP_FAKE_IDENTITY"] == "true"


def test_what_a_dead_connector_left_is_swept(tmp_path):
    left = tmp_path / f"{preview._PREFIX}old"
    (left / "app").mkdir(parents=True)
    state = preview._state_file("old-workspace")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"workspace": "old-workspace", "folder": str(left), "owner": 2 ** 22 + 1, "token": "t",
                                 "groups": []}))
    preview._sweep()
    assert not left.exists() and not state.exists()


def test_a_state_file_can_never_name_a_folder_that_is_not_a_previews(tmp_path):
    precious = tmp_path / "precious"
    precious.mkdir()
    state = preview._state_file("planted")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"workspace": "planted", "folder": str(precious), "owner": 2 ** 22 + 1, "token": "t",
                                 "groups": []}))
    preview._sweep()
    assert precious.exists() and not state.exists()


@pytest.mark.preview
@needs_uv
def test_a_connector_whose_preview_was_replaced_leaves_the_new_ones_state_alone():
    current = preview._Preview("taken-over", "0" * 40)
    state = preview._state_file("taken-over")
    theirs = {"workspace": "taken-over", "folder": "elsewhere", "token": "theirs", "groups": []}
    state.write_text(json.dumps(theirs))  # as another connector's watcher does when it has the workspace
    current.close()
    deadline = time.time() + 20
    while preview._watching(state) and time.time() < deadline:
        time.sleep(0.05)
    assert json.loads(state.read_text()) == theirs
    state.unlink()


def test_no_command_opens_a_window_on_the_persons_computer():
    source = (Path(preview.__file__)).read_text(encoding="utf-8")
    assert source.count("subprocess.run(") == source.count("**_HIDDEN")


def test_its_state_lives_in_the_connectors_own_folder():
    assert preview._state_file("x").is_relative_to(data_dir())


def test_this_run_has_a_temporary_folder_of_its_own():
    """Another run on this computer counts the previews in its own, and never sees these."""
    own = Path(preview.tempfile.gettempdir())
    assert own.name == "temp" and own.parent.name.startswith("eunomai-tests-")
    assert os.environ["TEMP"] == os.environ["TMP"] == os.environ["TMPDIR"] == str(own)


def test_the_home_a_preview_gives_is_shaped_as_a_profile():
    """Edge, started by the watcher, does not start under a profile whose folders are all the same one."""
    current = preview._Preview("shaped-home", "0" * 40)
    try:
        environment = current.environment("uv")
        home = Path(environment["USERPROFILE"])
        assert Path(environment["APPDATA"]) == home / "AppData" / "Roaming" and Path(environment["APPDATA"]).is_dir()
        assert Path(environment["LOCALAPPDATA"]) == home / "AppData" / "Local" and Path(environment["LOCALAPPDATA"]).is_dir()
        assert home.is_relative_to(current.folder)
    finally:
        current.close()


def test_an_export_can_leave_the_folders_state_for_later(signed_in, workspaces, tmp_path):
    name, _ = project(signed_in, declaration(Path("x")))
    assert set(gitops.export_saved(name, tmp_path / "copy", gitops.project_files(name)["tip"], None, False)) == {"head"}


def test_where_programs_are_installed_comes_from_windows_when_the_host_left_it_out(monkeypatch):
    """On 2026-11-04 Cowork's host started the connector without PROGRAMFILES(X86), where Edge was installed."""
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setenv("PROGRAMFILES", "C:\\Program Files")
    asked = []
    monkeypatch.setattr(preview, "_known_folder", lambda folder_id: asked.append(folder_id) or "C:\\Programs x86")
    found = preview._program_folders()
    assert found["PROGRAMFILES(X86)"] == "C:\\Programs x86"
    assert "PROGRAMFILES" not in found, "what the host gave is kept as it is"
    assert preview._PROGRAM_FOLDERS["PROGRAMFILES"] not in asked


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own known folders")
def test_windows_names_its_program_folders():
    folder = preview._known_folder(preview._PROGRAM_FOLDERS["PROGRAMFILES(X86)"])
    assert folder and Path(folder).is_dir()


def test_elsewhere_than_windows_no_folder_is_asked_for(monkeypatch):
    monkeypatch.setattr(preview.sys, "platform", "linux")
    assert preview._known_folder(preview._PROGRAM_FOLDERS["PROGRAMFILES"]) == ""

