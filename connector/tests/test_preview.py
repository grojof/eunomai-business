"""`app_preview`: the real application on the person's computer, through the connector.

Those marked `preview` start real processes with uv, from a small project with no packages, so nothing but a Python
for uv is downloaded, and only if the computer has none. The process tree and the temporary folder are checked for
real: a preview that survives its stop is the failure these exist for.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import httpx
import pytest

from eunomai_business import data_dir, deps, gitops, guard, preview, server as tools, settings, support

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
            self.send_response(200)
            self.end_headers()
            self.wfile.write(text.encode())

        def log_message(self, *args):
            pass


    http.server.HTTPServer((host, port), Answer).serve_forever()
    ''').encode()
RUN = '["python", "app.py", "--host", "127.0.0.1", "--port", "{port}"]'


def declaration(pids: Path, *setup: str, run: str = RUN, mode: str = "") -> bytes:
    steps = ", ".join(setup)
    return (f'[development]\ncode = true\n\n[preview]\nsetup = [{steps}]\nrun = {run}\n\n[preview.environment]\n'
            f'APP_ENVIRONMENT = "development"\nPIDS_FILE = "{pids.as_posix()}"\nAPP_MODE = "{mode}"\n').encode()


@pytest.fixture(autouse=True)
def nothing_left_behind():
    gitops._audits.clear()
    yield
    preview.stop_all()


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


def project(server, text: bytes | None, lock: bool = True) -> tuple[str, Path]:
    """A project with an application on its main branch, cloned, on a version."""
    name = f"preview-{uuid.uuid4().hex[:8]}"
    server.initialize(name)
    files = {"pyproject.toml": PYPROJECT, "app.py": APP, "message.txt": b"saved\n", "fail.py": b"print('setup broke')\n"
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
        if not any(preview._alive(number) for number in numbers):
            return True
        time.sleep(0.1)
    return False


def folders() -> list[Path]:
    """The temporary folders of previews this process knows of."""
    return [p.folder for p in preview._previews.values()]


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


@pytest.mark.parametrize("text, reason", [
    ('run = "uvicorn app:app --host 127.0.0.1 --port {port}"', "a list"),
    ('run = "python app.py && del *"', "a list"),
    ('run = []', "a list"),
    ('run = ["uvicorn app:app --host 127.0.0.1 --port {port}"]', "program"),
    ('run = ["sh", "-c", "uvicorn --host 127.0.0.1 --port {port}"]', "shell"),
    ('run = ["bash", "-c", "x --host 127.0.0.1 --port {port}"]', "shell"),
    ('run = ["cmd", "/c", "x --host 127.0.0.1 --port {port}"]', "shell"),
    ('run = ["cmd.exe", "/c", "x --host 127.0.0.1 --port {port}"]', "shell"),
    ('run = ["powershell", "-c", "x --host 127.0.0.1 --port {port}"]', "shell"),
    ('run = ["pwsh", "-c", "x --host 127.0.0.1 --port {port}"]', "shell"),
    ('run = ["uv", "pip", "install", "x", "--host", "127.0.0.1", "--port", "{port}"]', "shell"),
    ('run = ["/usr/bin/python", "--host", "127.0.0.1", "--port", "{port}"]', "program"),
    ('run = ["..\\\\evil.exe", "--host", "127.0.0.1", "--port", "{port}"]', "program"),
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
    ('run = ["x", "--host", "127.0.0.1", "--host", "0.0.0.0", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["gunicorn", "-b", "0.0.0.0:{port}", "--bind", "127.0.0.1:{port}"]', "127.0.0.1"),
    ('run = ["gunicorn", "--bind=0.0.0.0:{port}"]', "127.0.0.1"),
    ('run = ["x", "runserver", "0.0.0.0:{port}"]', "127.0.0.1"),
    ('run = ["x", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "127.0.0.1", "--uds", "/tmp/x", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "127.0.0.1", "--fd", "3", "--port", "{port}"]', "127.0.0.1"),
    ('run = ["x", "--host", "127.0.0.1"]', "{port}"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "8000"]', "{port}"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}", "--name", "{user}"]', "{port}"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\nsetup = "python -m x"', "setup"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\nsetup = ["python", "-m", "x"]', "setup"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\nsetup = [["sh", "-c", "x"]]', "shell"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\nsetup = [["python", "{port}"]]', "setup"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\nshell = true', "takes"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\n[preview.environment]\nA = 1', "text"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\n[preview.environment]\nPATH = "x"', "environment"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\n[preview.environment]\nUV_INDEX_URL = "x"', "environment"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\n[preview.environment]\nPYTHONPATH = "x"', "environment"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\n[preview.environment]\nUSERPROFILE = "x"', "environment"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\n[preview.environment]\nLD_PRELOAD = "x"', "environment"),
    ('run = ["x", "--host", "127.0.0.1", "--port", "{port}"]\n[preview.environment]\nlower = "x"', "environment"),
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
    '["gunicorn", "--bind", "127.0.0.1:{port}"]', '["gunicorn", "-b", "127.0.0.1:{port}"]',
    '["x", "runserver", "127.0.0.1:{port}"]', '["x", "--host=127.0.0.1", "--port={port}"]',
])
def test_other_ways_of_saying_this_computer_only_are_valid(run):
    assert "invalid" not in settings.preview({"text": f"[preview]\nrun = {run}\n"})


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


def test_a_task_in_the_cloud_is_refused_by_the_guard(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    for tool in ("app_preview", "app_preview_stop"):
        found = guard.decide({"tool_name": f"mcp__plugin_eunomai-business_eunomai-business__{tool}", "tool_input": {}})
        assert "in the cloud" in found


def test_the_guard_covers_both_tools():
    import re
    template = Path(__file__).parents[2] / "plugin" / "hooks" / "hooks.json.template"
    matcher = json.loads(template.read_text())["hooks"]["PreToolUse"][0]["matcher"]
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
    assert all(preview._alive(number) for number in numbers)
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
    assert Path(seen["UV_PROJECT_ENVIRONMENT"]).is_relative_to(folders()[0])
    profile = str(Path.home())
    assert profile not in (seen.get("USERPROFILE"), seen.get("HOME"), seen.get("APPDATA"), seen.get("LOCALAPPDATA"))
    allowed = {"APP_ENVIRONMENT", "PIDS_FILE", "APP_MODE", "UV_PROJECT_ENVIRONMENT", "UV_CACHE_DIR",
               "UV_PYTHON_INSTALL_DIR", "PATH", "PATHEXT", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP",
               "TMP", "TMPDIR", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "NO_COLOR", "LANG", "LC_ALL",
               "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "TZ",
               # uv's own, on what it runs; Python's own on Windows; every one a name no organization's secret has
               "UV", "UV_RUN_RECURSION_DEPTH", "VIRTUAL_ENV", "__CF_USER_TEXT_ENCODING", "PWD", "LC_CTYPE", "SHLVL"}
    assert set(seen) <= allowed, set(seen) - allowed


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
    sys.platform != "win32", reason="only the system's own table shows another port"))])
def test_an_application_that_answers_beyond_this_computer_is_stopped(signed_in, workspaces, turned_on, browser, pids,
                                                                     mode):
    try:
        addresses = [a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith("127.")]
    except OSError:
        addresses = []
    if not addresses and sys.platform != "win32":
        pytest.skip("this computer has no other address to reach it on")
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
    while name in preview._previews and time.time() < deadline:
        time.sleep(0.05)
    answer = tools.app_preview(name)
    assert answer["status"] == "needs_it" and "setup broke" in answer["it_report"]
    assert name not in preview._unread


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
    monkeypatch.setattr(preview, "TIME_LIMIT", 2)
    name, _ = project(signed_in, declaration(pids))
    assert show(name)["status"] == "ready"
    numbers, folder = json.loads(pids.read_text()), folders()[0]
    assert gone(*numbers, wait=20), "a process survived the time limit"
    deadline = time.time() + 15
    while name in preview._previews and time.time() < deadline:
        time.sleep(0.1)
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
    current = next(iter(preview._previews.values()))
    current.tree.kill()
    assert current.ended.wait(15) and not current.folder.exists() and name not in preview._previews


HARNESS = textwrap.dedent('''\
    import json, sys, time
    from pathlib import Path

    from eunomai_business import preview

    preview.webbrowser.open = lambda url: True
    source, name, pids = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    run = ["python", "app.py", "--host", "127.0.0.1", "--port", "{port}"]
    current = preview._Preview(name, "0" * 40)
    preview._previews[name] = current
    preview.shutil.copytree(source, current.app, dirs_exist_ok=True)
    preview._bring_up(current, {"setup": [], "run": run, "environment": {"PIDS_FILE": pids}})
    print(json.dumps({"folder": str(current.folder), "url": current.url}), flush=True)
    sys.stdin.read()
    ''')


def connector_with_a_preview(tmp_path, name: str) -> tuple[subprocess.Popen, dict, list[int]]:
    """A connector of its own, in a process of its own: what Claude Desktop starts and later closes."""
    source = tmp_path / "source"
    source.mkdir()
    for file, content in {"pyproject.toml": PYPROJECT, "uv.lock": LOCK, "app.py": APP, "message.txt": b"x"}.items():
        (source / file).write_bytes(content)
    harness = tmp_path / "harness.py"
    harness.write_text(HARNESS, encoding="utf-8")
    pids = tmp_path / "harness-pids.json"
    process = subprocess.Popen([sys.executable, str(harness), str(source), name, str(pids)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
    line = process.stdout.readline()
    assert line, "the connector did not bring the preview up"
    return process, json.loads(line), json.loads(pids.read_text())


def wait_gone(folder: Path, wait: float = 30.0) -> bool:
    deadline = time.time() + wait
    while folder.exists() and time.time() < deadline:
        time.sleep(0.1)
    return not folder.exists()


@pytest.mark.preview
@needs_uv
@pytest.mark.parametrize("how", ["closed", "killed"])
def test_it_stops_when_the_connector_exits(tmp_path, how):
    """Closed: its input ends, as when Claude Desktop closes the session. Killed: nothing of it runs any more."""
    process, started, numbers = connector_with_a_preview(tmp_path, f"exit-{how}")
    assert all(preview._alive(number) for number in numbers)
    if how == "closed":
        process.stdin.close()
    else:
        process.kill()
    process.wait(timeout=30)
    assert gone(*numbers, wait=20), "a process outlived the connector"
    assert wait_gone(Path(started["folder"])), "the temporary folder outlived the connector"


@pytest.mark.preview
@needs_uv
def test_another_connector_on_the_same_workspace_replaces_it(tmp_path):
    """Claude Desktop starts one connector per task: two tasks on a workspace must not leave two previews."""
    process, started, numbers = connector_with_a_preview(tmp_path, "shared")
    try:
        preview._clear_left_over("shared")
        assert gone(*numbers, wait=20), "the other connector's preview survived"
        assert wait_gone(Path(started["folder"]))
    finally:
        process.kill()
        process.wait(timeout=30)


def test_what_a_dead_connector_left_is_swept(tmp_path):
    left = tmp_path / f"{preview._PREFIX}old"
    (left / "app").mkdir(parents=True)
    state = preview._state_file("old-workspace")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"workspace": "old-workspace", "folder": str(left), "owner": 2 ** 22 + 1, "job": "",
                                 "group": 0}))
    preview._sweep()
    assert not left.exists() and not state.exists()


def test_a_state_file_can_never_name_a_folder_that_is_not_a_previews(tmp_path):
    precious = tmp_path / "precious"
    precious.mkdir()
    state = preview._state_file("planted")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"workspace": "planted", "folder": str(precious), "owner": 2 ** 22 + 1, "job": "",
                                 "group": 0}))
    preview._sweep()
    assert precious.exists() and not state.exists()


@pytest.mark.preview
@needs_uv
def test_a_connector_whose_preview_was_replaced_leaves_the_new_ones_state_alone(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids))
    assert show(name)["status"] == "ready"
    current = next(iter(preview._previews.values()))
    state = preview._state_file(name)
    theirs = {"workspace": name, "folder": "elsewhere", "owner": os.getpid() + 1, "job": "", "group": 0}
    state.write_text(json.dumps(theirs))  # as another connector does when it takes the workspace over
    current.close()
    assert json.loads(state.read_text()) == theirs
    state.unlink()


def test_no_command_opens_a_window_on_the_persons_computer():
    source = (Path(preview.__file__)).read_text(encoding="utf-8")
    assert source.count("subprocess.run(") == source.count("**_HIDDEN")


def test_its_state_lives_in_the_connectors_own_folder():
    assert preview._state_file("x").is_relative_to(data_dir())
