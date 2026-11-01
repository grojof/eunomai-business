"""A preview belongs to its watcher: it outlives the connector, which in Cowork lives one turn.

The connector here is a process of its own, started by the plugin's real command and spoken to over its standard
input, as a host does, and it is ended the hard way: a tree kill, a host's job with kill-on-close, or SIGKILL of its
group. Nothing but what the tools answer and what the system shows is looked at.
"""

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
from test_preview import APP, LOCK, PYPROJECT, declaration

from conftest import alive
from eunomai_business import preview

needs_uv = pytest.mark.skipif(not (os.environ.get("UV") or shutil.which("uv")), reason="needs uv")
pytestmark = [pytest.mark.preview, needs_uv]
WINDOWS = sys.platform == "win32"
CONNECTOR = Path(__file__).parents[1]
TEMPLATE = CONNECTOR.parent / "plugin" / ".mcp.json.template"
SHORT = ("-c", "import sys; from eunomai_business import preview, server; preview.TIME_LIMIT = float(sys.argv[1]); "
               "server.main()")

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    from eunomai_business.watcher import ExtendedLimits

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    KILL_ON_CLOSE, BREAKAWAY_OK, EXTENDED_LIMITS, SUSPENDED = 0x2000, 0x800, 9, 0x4


def host_job(allow_breakaway: bool) -> int:
    """What a host may hold its children in. It kills them all when its last handle closes."""
    job = _kernel32.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = KILL_ON_CLOSE | (BREAKAWAY_OK if allow_breakaway else 0)
    assert _kernel32.SetInformationJobObject(job, EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits))
    return job


@pytest.fixture(scope="session")
def connector_environment(tmp_path_factory) -> Path:
    """The plugin's command must not take the tests' own packages out of the project's environment."""
    return tmp_path_factory.mktemp("connector-environment") / "env"


class Connector:
    """The connector, as a host starts it: the plugin's command, and tools called over its standard input."""

    started: list = []

    def __init__(self, environment: dict, job: int = 0, entry: tuple[str, ...] = ()):
        arguments = json.loads(TEMPLATE.read_text(encoding="utf-8"))["mcpServers"]["eunomai-business"]["args"]
        arguments = [str(CONNECTOR) if word == "{{CONNECTOR}}" else word for word in arguments]
        uv = os.environ.get("UV") or shutil.which("uv")
        if entry:  # the same command, with a limit a test can wait for
            arguments = [*arguments[:-1], "python", *entry]
        options = {"creationflags": SUSPENDED} if job else {"start_new_session": True} if not WINDOWS else {}
        self.process = subprocess.Popen([uv, *arguments], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=environment, cwd=tempfile.gettempdir(), **options)
        if job:
            assert _kernel32.AssignProcessToJobObject(job, int(self.process._handle))
            _ntdll.NtResumeProcess(int(self.process._handle))
        Connector.started.append(self)
        self.lines, self.number = queue.Queue(), 0
        threading.Thread(target=self._read, daemon=True).start()
        self._ask("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "test", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)

    def _send(self, message: dict) -> None:
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def _ask(self, method: str, parameters: dict) -> dict:
        self.number += 1
        self._send({"jsonrpc": "2.0", "id": self.number, "method": method, "params": parameters})
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                reply = json.loads(self.lines.get(timeout=1))
            except queue.Empty:
                continue
            if reply.get("id") == self.number:
                return reply["result"]
        raise AssertionError(f"no answer to {method}")

    def tool(self, tool: str, /, **arguments) -> dict:
        result = self._ask("tools/call", {"name": tool, "arguments": arguments})
        return result.get("structuredContent") or json.loads(result["content"][0]["text"])

    def show(self, workspace: str) -> dict:
        for _ in range(150):
            answer = self.tool("app_preview", workspace=workspace)
            if answer.get("status") != "starting":
                return answer
            time.sleep(0.2)
        raise AssertionError("never ready")

    def end(self, how: str, job: int = 0) -> None:
        """However a host may end it, and nothing it could notice in time."""
        if how == "job":
            assert _kernel32.CloseHandle(job)
        elif how == "tree":
            subprocess.run([f"{os.environ['SYSTEMROOT']}/System32/taskkill.exe", "/T", "/F", "/PID",
                            str(self.process.pid)], capture_output=True, check=True)
        elif how == "group":
            os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=20)


@pytest.fixture
def computer(tmp_path, server, connector_environment, monkeypatch) -> dict:
    """One person's folders, shared by every connector of the test, signed in by the first."""
    data = tmp_path / "local"
    data.mkdir()
    environment = {**os.environ, "LOCALAPPDATA": str(data), "EUNOMAI_WORKSPACES_ROOT": str(tmp_path / "workspaces"),
                   "EUNOMAI_PROVIDERS": json.dumps({"git": server.provider()}),
                   "EUNOMAI_SPECIALIST": json.dumps({"app_preview": True}),
                   "UV_PROJECT_ENVIRONMENT": str(connector_environment), "BROWSER": "true", "NO_PROXY": "*",
                   # no browser opens in a test
                   "PYTHONPATH": str(Path(__file__).parent), "PYTHON_KEYRING_BACKEND": "preview_keyring.FileBackend"}
    environment.pop("VIRTUAL_ENV", None)
    monkeypatch.setenv("LOCALAPPDATA", str(data))
    yield {"environment": environment, "data": data}
    for connector in Connector.started:
        connector.process.kill()
    Connector.started.clear()
    folder = data / "eunomai-business" / "previews"
    for state in [*folder.glob("*.json")] if folder.is_dir() else ():  # whatever a failed test left running
        state.with_suffix(".stop").touch()
    deadline = time.time() + 20
    while folder.is_dir() and [*folder.glob("*.json")] and time.time() < deadline:
        time.sleep(0.1)
    shutil.rmtree(folder, ignore_errors=True)  # with no state file, a watcher ends what it holds


def ready_project(server, computer: dict, tmp_path: Path, connector: Connector) -> tuple[str, Path]:
    """Signed in on that connector, with an application on the main branch, cloned, on a saved version."""
    started = connector.tool("sign_in_start", provider="git")
    httpx.get(started["url"], follow_redirects=True, trust_env=False)
    for _ in range(50):
        if connector.tool("sign_in_status", provider="git")["status"] == "signed_in":
            break
        time.sleep(0.1)
    name = f"outlives-{uuid.uuid4().hex[:8]}"
    pids = tmp_path / "pids.json"
    server.initialize(name)
    server.server_commit(name, "main", {"pyproject.toml": PYPROJECT, "uv.lock": LOCK, "app.py": APP,
                                        "message.txt": b"saved\n", ".eunomai/project.toml": declaration(pids)})
    connector.tool("workspace_clone", repo_url=f"{server.url}/me/{name}.git")
    assert connector.tool("version_create", workspace=name, name="draft/work").get("status") != "needs_it"
    return name, pids


def answers(url: str) -> bool:
    try:
        return httpx.get(url, timeout=3, trust_env=False).status_code == 200
    except httpx.HTTPError:
        return False


def still_answers(url: str, seconds: float = 4.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not answers(url):
            return False
        time.sleep(0.25)
    return True


def gone(*numbers: int, wait: float = 20.0) -> bool:
    deadline = time.time() + wait
    while time.time() < deadline:
        if not any(alive(number) for number in numbers):
            return True
        time.sleep(0.1)
    return False


def left(computer: dict) -> list[str]:
    """What a preview leaves on the computer: its state, its markers and its folder."""
    folder = computer["data"] / "eunomai-business" / "previews"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def preview_folders(before: set[Path]) -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob("eunomai-preview-*")) - before


HARD_WAYS = ["tree", "job"] if WINDOWS else ["group"]


@pytest.mark.parametrize("how", HARD_WAYS)
def test_a_preview_outlives_its_connector_and_the_next_one_finds_it(server, computer, tmp_path, how):
    before = preview_folders(set())
    job = host_job(True) if how == "job" else 0
    first = Connector(computer["environment"], job)
    name, pids = ready_project(server, computer, tmp_path, first)
    answer = first.show(name)
    if WINDOWS and os.environ.get("GITHUB_ACTIONS") and answer.get("keeps_running") is False:
        # GitHub's Windows runner holds its processes in a job nothing leaves; the test of such a host covers that case.
        assert first.tool("app_preview_stop", workspace=name)["status"] == "stopped"
        first.end(how, job)
        pytest.skip("this runner's own job refuses breakaway")
    assert answer["status"] == "ready" and answer["keeps_running"] is True, answer
    url, numbers = answer["url"], json.loads(pids.read_text())
    first.end(how, job)
    assert still_answers(url), "the application died with its connector"
    assert all(alive(number) for number in numbers)

    second = Connector(computer["environment"])
    found = second.tool("app_preview", workspace=name)
    assert found["status"] == "ready" and found["url"] == url and found["already_running"] is True, found
    assert 0 < found["minutes"] <= 60 and str(found["minutes"]) in found["user_message"]
    assert json.loads(pids.read_text()) == numbers, "it was started again"

    stopped = second.tool("app_preview_stop", workspace=name)
    assert stopped["status"] == "stopped", stopped
    assert gone(*numbers) and not answers(url)
    assert left(computer) == [] and preview_folders(before) == set()
    assert second.tool("app_preview_stop", workspace=name)["status"] == "not_running"
    second.end("tree" if WINDOWS else "group")


def test_a_new_connector_replaces_it_for_another_saved_version(server, computer, tmp_path):
    before = preview_folders(set())
    first = Connector(computer["environment"])
    name, pids = ready_project(server, computer, tmp_path, first)
    url, numbers = first.show(name)["url"], json.loads(pids.read_text())
    first.end("tree" if WINDOWS else "group")
    second = Connector(computer["environment"])
    (Path(computer["environment"]["EUNOMAI_WORKSPACES_ROOT"]) / name / "message.txt").write_bytes(b"newer\n")
    second.tool("version_save", workspace=name, message="Newer")
    pids.unlink()
    answer = second.show(name)
    assert answer["status"] == "ready" and answer["already_running"] is False and answer["url"] != url, answer
    assert gone(*numbers) and httpx.get(answer["url"], trust_env=False).text == "newer\n"
    assert second.tool("app_preview_stop", workspace=name)["status"] == "stopped"
    assert left(computer) == [] and preview_folders(before) == set()
    second.end("tree" if WINDOWS else "group")


def test_the_time_limit_holds_with_the_connector_already_gone(server, computer, tmp_path):
    before = preview_folders(set())
    first = Connector(computer["environment"], entry=(*SHORT, "12"))
    name, pids = ready_project(server, computer, tmp_path, first)
    answer = first.show(name)
    assert answer["status"] == "ready", answer
    url, numbers = answer["url"], json.loads(pids.read_text())
    first.end("tree" if WINDOWS else "group")
    assert answers(url)
    assert gone(*numbers, wait=40), "the limit did not end it"
    deadline = time.time() + 15
    while [n for n in left(computer) if not n.endswith(".ended")] and time.time() < deadline:
        time.sleep(0.1)
    assert [n for n in left(computer) if not n.endswith(".ended")] == [] and preview_folders(before) == set()
    second = Connector(computer["environment"])
    assert second.tool("app_preview_stop", workspace=name)["status"] == "not_running"
    second.end("tree" if WINDOWS else "group")


@pytest.mark.skipif(not WINDOWS, reason="a job")
def test_a_host_that_refuses_breakaway_is_told_honestly_and_leaves_nothing(server, computer, tmp_path):
    """Nothing is done to get around it: the preview works, ends with the host, and the person was told so."""
    before = preview_folders(set())
    job = host_job(False)
    first = Connector(computer["environment"], job)
    name, pids = ready_project(server, computer, tmp_path, first)
    answer = first.show(name)
    assert answer["status"] == "ready" and answer["keeps_running"] is False, answer
    assert "task ends" in answer["user_message"]
    url, numbers = answer["url"], json.loads(pids.read_text())
    first.end("job", job)
    assert gone(*numbers) and not answers(url)
    second = Connector(computer["environment"])
    assert second.tool("app_preview_stop", workspace=name)["status"] == "not_running"
    assert left(computer) == [] and preview_folders(before) == set()
    second.end("tree")
