"""What a preview's own code can do to what looks after it.

Application code runs as the person, so it can read and rewrite the state file: nothing in that file is believed
unless it passes one reader, and what the connector does with it stays small. These tests also cover the rest of the
same review: what is said about a preview must be true of it.
"""

import ctypes
import json
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from conftest import alive
from test_preview import browser, declaration, folders, nothing_left_behind, pids, project, show, turned_on, wait_gone  # noqa: F401

from eunomai_business import data_dir, gitops, preview, server as tools, support, watcher

needs_uv = pytest.mark.skipif(not (os.environ.get("UV") or preview.shutil.which("uv")), reason="needs uv")
WINDOWS = sys.platform == "win32"

# Closes its listener on request and goes on living, as a server whose accept loop died does.
DEAF = b"""import http.server, json, os, pathlib, sys, time

arguments = sys.argv[1:]
host, port = arguments[arguments.index("--host") + 1], int(arguments[arguments.index("--port") + 1])
pathlib.Path(os.environ["PIDS_FILE"]).write_text(json.dumps([os.getpid()]))


class Answer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"saved")
        if self.path == "/deaf":
            import threading
            threading.Thread(target=server.shutdown).start()

    def log_message(self, *args):
        pass


server = http.server.HTTPServer((host, port), Answer)
server.serve_forever()
server.server_close()
time.sleep(600)
"""


def ready(signed_in, pids_file: Path, **more) -> tuple[str, Path, dict, list[int]]:
    name, ws = project(signed_in, declaration(pids_file), **more)
    answer = show(name)
    assert answer["status"] == "ready", answer
    return name, ws, answer, json.loads(pids_file.read_text())


def rewrite(name: str, **fields) -> None:
    """As the application can: the state is a file of the person's."""
    state = preview._state_file(name)
    state.write_text(json.dumps({**json.loads(state.read_text()), **fields}))


def phase(name: str) -> str:
    return preview._preview_state(preview._state_file(name)).get("phase", "")


def wait_for(condition, seconds: float = 20.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def gone(*numbers: int, seconds: float = 20.0) -> bool:
    return wait_for(lambda: not any(alive(number) for number in numbers), seconds)


@pytest.fixture(autouse=True)
def no_suspended_watcher_stays():
    """Nothing else would ever end one, whatever a failed test left."""
    yield
    while SUSPENDED:
        number = SUSPENDED.pop()
        try:
            os.kill(number, signal.SIGTERM if WINDOWS else signal.SIGKILL)
        except OSError:
            pass


SUSPENDED: list[int] = []


def suspend(number: int) -> None:
    """A preview's code can do this to the process that looks after it."""
    SUSPENDED.append(number)
    if not WINDOWS:
        os.kill(number, signal.SIGSTOP)
        return
    kernel32, ntdll = ctypes.WinDLL("kernel32"), ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.restype = ctypes.c_void_p
    ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x0800, False, number)  # PROCESS_SUSPEND_RESUME
    assert handle
    assert ntdll.NtSuspendProcess(handle) == 0
    kernel32.CloseHandle(handle)


# --- 1, 2: the state is not believed --------------------------------------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_an_address_rewritten_in_the_state_is_never_opened_or_told(signed_in, workspaces, turned_on, browser, pids):
    """It went to `webbrowser.open`, which on Windows runs a file, as a child of the connector."""
    name, _, first, _ = ready(signed_in, pids)
    planted = "C:\\Users\\me\\run-me.cmd"
    rewrite(name, url=planted, port=planted)
    answer = show(name)
    assert planted not in json.dumps(answer) and planted not in browser
    assert all(url.startswith("http://127.0.0.1:") and url.endswith("/") for url in browser)


@pytest.mark.preview
@needs_uv
@pytest.mark.parametrize("fields", [
    {"port": "x"}, {"port": 80}, {"port": 70000}, {"port": True}, {"port": 1.5}, {"head": 5}, {"head": "not hex"},
    {"deadline": "x"}, {"deadline": -1}, {"began": "x"}, {"began": 9e12}, {"phase": "other"}, {"groups": ["x"]},
    {"groups": [0]}, {"watcher": -1}, {"watcher": "x"}, {"token": 1}, {"token": "short"}, {"keeps_running": "yes"},
    {"folder": "C:/Users"}, {"workspace": "another"}, {"declaration": 1}], ids=str)
def test_a_state_that_does_not_pass_the_reader_ends_that_preview(signed_in, workspaces, turned_on, browser, pids, fields):
    name, _, first, numbers = ready(signed_in, pids)
    pids.unlink()
    rewrite(name, **fields)
    answer = show(name)
    assert answer["status"] == "ready" and answer["already_running"] is False, answer
    assert gone(*numbers), "the preview with a broken state goes on"
    assert httpx.get(answer["url"]).status_code == 200


@pytest.mark.preview
@needs_uv
def test_the_time_left_is_never_more_than_the_limit(signed_in, workspaces, turned_on, pids):
    name, _, _, _ = ready(signed_in, pids)
    rewrite(name, deadline=time.time() + 3540 * 60)
    answer = tools.app_preview(name)
    assert answer["already_running"] is True and answer["minutes"] <= 60, answer
    assert "3540" not in answer["user_message"]


@pytest.mark.preview
@needs_uv
def test_what_it_says_of_a_running_preview_does_not_rest_on_the_state(signed_in, workspaces, turned_on, pids):
    """The saved version in the state can be rewritten: the person is told what is known, no more."""
    name, _, _, _ = ready(signed_in, pids)
    words = tools.app_preview(name)["user_message"]
    assert "started earlier" in words and "last saved" not in words


def test_barriers_say_what_the_state_is_for():
    text = " ".join((Path(preview.__file__).parents[3] / "docs" / "barriers.md").read_text(encoding="utf-8").split())
    assert "The state protects against the sandbox, not against the application" in text


# --- 3: a watcher that does not answer ----------------------------------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_a_suspended_watcher_is_ended_with_everything_it_holds(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, _, _, numbers = ready(signed_in, pids)
    monkeypatch.setattr(preview, "_END_WAIT", 2.0)
    number = preview._read_state(preview._state_file(name))["watcher"]
    suspend(number)
    answer = tools.app_preview_stop(name)
    assert answer["status"] == "stopped", answer
    assert gone(*numbers, number) and folders() == []


@pytest.mark.preview
@needs_uv
def test_a_stop_file_deleted_as_it_appears_does_not_win(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, _, _, numbers = ready(signed_in, pids)
    monkeypatch.setattr(preview, "_END_WAIT", 2.0)
    stop_file, ending = preview._state_file(name).with_suffix(".stop"), threading.Event()

    def delete():
        while not ending.is_set():
            try:
                stop_file.unlink(missing_ok=True)
            except OSError:
                pass

    deleting = threading.Thread(target=delete, daemon=True)
    deleting.start()
    try:
        assert tools.app_preview_stop(name)["status"] == "stopped"
    finally:
        ending.set()
    assert gone(*numbers)


def test_nothing_promises_it_ends_within_the_hour():
    assert "within the hour" not in preview._NOT_STOPPED("x")["user_message"]


def test_a_process_number_alone_is_not_a_watcher():
    """The right number with another start time is another process, and it is left alone."""
    image, created = watcher.identity(os.getpid())
    assert created and image
    assert watcher.end_process(os.getpid(), created + 1, image) is False
    assert watcher.end_process(os.getpid(), created, image + "x") is False


def fresh_watcher(tmp_path, **more) -> watcher.Watcher:
    folder = tmp_path / f"{preview._PREFIX}unit"
    folder.mkdir()
    state = tmp_path / "unit.json"
    state.write_text("{}")
    return watcher.Watcher({"folder": str(folder), "state": str(state), "token": "t", "workspace": "w", "head": "0" * 40,
                            "limit": 60, "log": str(folder / "log"), "declaration": "0" * 16,
                            "keep": str(tmp_path / f"{preview._PREFIX}keep-unit"), **more})


def test_the_limit_holds_if_the_clock_is_put_back(tmp_path):
    current = fresh_watcher(tmp_path)
    current.deadline, current.steady_deadline = time.time() + 1000, time.monotonic() - 1
    assert current.reason_to_end() == "time_limit"


def test_the_limit_holds_if_the_steady_clock_stood_still(tmp_path):
    """Linux stops it while a computer sleeps."""
    current = fresh_watcher(tmp_path)
    current.deadline, current.steady_deadline = time.time() - 1, time.monotonic() + 1000
    assert current.reason_to_end() == "time_limit"


# --- 4: what is claimed, and what stop can know ---------------------------------------------------------------------

def test_the_job_is_not_claimed_to_hold_what_is_built_to_leave():
    root = Path(preview.__file__).parents[3]
    text = " ".join((root / "docs" / "barriers.md").read_text(encoding="utf-8").split())
    assert "nothing outlives the watcher" not in text and "built to stay" in text and "Low integrity" in text
    assert "cannot leave it" not in " ".join(Path(watcher.__file__).read_text(encoding="utf-8").split())


def test_a_stop_that_still_gets_an_answer_does_not_say_it_stopped(tmp_path):
    """What got out of the job, or took a handle of it: its address answers with the watcher gone."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    serving = threading.Event()

    def serve():
        while not serving.is_set():
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            connection.recv(100)
            connection.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
            connection.close()

    threading.Thread(target=serve, daemon=True).start()
    left = tmp_path / f"{preview._PREFIX}escaped"
    left.mkdir()
    state = preview._state_file("escaped")
    state.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    state.write_text(json.dumps({"workspace": "escaped", "folder": str(left), "token": "a" * 32, "head": "0" * 40,
                                 "phase": "ready", "port": listener.getsockname()[1], "began": now, "deadline": now + 60,
                                 "groups": [], "watcher": 4, "created": 1, "image": "x", "keeps_running": True,
                                 "declaration": "0" * 16}))
    try:
        assert preview.stop("escaped")["status"] == "not_stopped"
    finally:
        serving.set()
        listener.close()


def test_a_broken_state_with_no_watcher_cannot_say_nothing_was_running():
    state = preview._state_file("unknown")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('{"port": "rewritten"}')
    answer = preview.stop("unknown")
    assert answer["status"] == "not_stopped" and "stopped" not in answer["user_message"].split()[:2]
    assert not state.exists()


# --- 6, 7, 8: what connectors remember ------------------------------------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_an_application_that_ended_after_a_starting_answer_is_not_told_as_ready(signed_in, workspaces, turned_on, pids,
                                                                                monkeypatch):
    monkeypatch.setattr(preview, "_ANSWER_WAIT", 0.0)
    name, _ = project(signed_in, declaration(pids))
    assert tools.app_preview(name)["status"] == "starting"
    assert wait_for(lambda: preview._key(name) not in preview._previews and phase(name) == "ready")
    number, folder = json.loads(pids.read_text())[0], folders()[0]
    os.kill(number, signal.SIGKILL if not WINDOWS else signal.SIGTERM)
    assert wait_gone(folder, 20) and wait_for(lambda: not preview._state_file(name).exists())
    pids.unlink()
    assert show(name)["ended_before"] == "application"


@pytest.mark.preview
@needs_uv
def test_a_ready_preview_nobody_was_told_of_still_counts_as_running(signed_in, workspaces, turned_on, pids, monkeypatch):
    monkeypatch.setattr(preview, "_ANSWER_WAIT", 0.0)
    name, _ = project(signed_in, declaration(pids))
    assert tools.app_preview(name)["status"] == "starting"
    assert wait_for(lambda: phase(name) == "ready")
    assert tools.app_preview_stop(name)["status"] == "stopped"
    assert gone(*json.loads(pids.read_text()))


@pytest.mark.preview
@needs_uv
def test_a_reader_of_the_state_as_it_becomes_ready_costs_nothing(signed_in, workspaces, turned_on, pids, monkeypatch):
    """On Windows a file open for reading cannot be replaced: ready, and then dead."""
    real = preview._Preview.hand_over

    def with_a_reader(self):
        reader = open(preview._state_file(self.workspace))  # noqa: SIM115
        threading.Timer(1.0, reader.close).start()
        real(self)

    monkeypatch.setattr(preview._Preview, "hand_over", with_a_reader)
    name, _ = project(signed_in, declaration(pids))
    answer = show(name)
    assert answer["status"] == "ready", answer
    time.sleep(1.5)
    assert httpx.get(answer["url"]).status_code == 200 and phase(name) == "ready"


def test_a_refused_hand_over_is_not_taken_for_a_ready_preview():
    current = preview._Preview("no-hand-over", "0" * 40)
    real = current.ask
    try:
        current.ask = lambda request: {"error": "PermissionError"}
        with pytest.raises(support.NeedsIT):
            current.hand_over()
        assert current.handed_over is False
    finally:
        current.ask = real
        current.close()


# --- 9, 10, 11, 12: a running preview that is not what it seems ---------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_a_preview_that_no_longer_listens_is_replaced(signed_in, workspaces, turned_on, pids):
    name, ws = project(signed_in, declaration(pids), app=DEAF)
    first = show(name)
    numbers = json.loads(pids.read_text())
    httpx.get(first["url"] + "deaf")
    assert wait_for(lambda: not preview._answers(int(first["url"].rsplit(":", 1)[1].strip("/"))))
    pids.unlink()
    answer = show(name)
    assert answer["status"] == "ready" and answer["already_running"] is False, answer
    assert gone(*numbers) and answer["ended_before"] == "silent"


@pytest.mark.preview
@needs_uv
def test_a_preview_that_is_ending_is_not_told_as_running(signed_in, workspaces, turned_on, pids):
    name, _, first, numbers = ready(signed_in, pids)
    pids.unlink()
    rewrite(name, phase="ending")
    answer = show(name)
    assert answer["status"] == "ready" and answer["already_running"] is False, answer
    assert gone(*numbers)


def test_the_watcher_says_it_is_ending_before_it_does_anything(tmp_path):
    current = fresh_watcher(tmp_path)
    Path(current.path).write_text(json.dumps({"token": current.token}))
    seen = []
    real = current.tree.kill
    current.tree.kill = lambda: (seen.append(json.loads(Path(current.path).read_text())["phase"]), real())
    current.hold()
    current.end("asked")
    assert seen == ["ending"]


def test_no_step_starts_once_the_tree_was_ended(tmp_path):
    tree = watcher.Tree()
    tree.kill()
    with pytest.raises(PermissionError):
        tree.start([sys.executable, "-c", "pass"], str(tmp_path), dict(os.environ), subprocess_log(tmp_path))


def subprocess_log(tmp_path):
    return open(tmp_path / "log", "ab")  # noqa: SIM115


def test_a_state_file_that_cannot_be_written_goes_to_it_and_not_starting_forever(signed_in, workspaces, turned_on, pids):
    name, _ = project(signed_in, declaration(pids))
    state = preview._state_file(name)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir()
    try:
        answer = tools.app_preview(name)
        assert answer["status"] == "needs_it", answer
    finally:
        state.rmdir()


def test_a_watcher_that_dies_before_it_answers_is_not_another_connectors_preview(monkeypatch):
    real = preview._Preview._start_watcher

    def dies(self):
        process = real(self)
        process.stdin.close()
        return preview.subprocess.Popen([sys.executable, "-c", "pass"], stdin=preview.subprocess.PIPE,
                                        stdout=preview.subprocess.PIPE)

    monkeypatch.setattr(preview._Preview, "_start_watcher", dies)
    with pytest.raises(support.NeedsIT):
        preview._Preview("dies-at-once", "0" * 40)


@pytest.mark.preview
@needs_uv
def test_a_changed_declaration_starts_it_again(signed_in, workspaces, turned_on, pids):
    name, _, first, numbers = ready(signed_in, pids)
    pids.unlink()
    signed_in.server_commit(name, "main", {".eunomai/project.toml": declaration(pids) + b'NEW = "1"\n'})
    answer = show(name)
    assert answer["status"] == "ready" and answer["already_running"] is False, answer
    assert gone(*numbers)


# --- 13: a turn that ends on `starting` ------------------------------------------------------------------------------

def test_a_person_is_told_a_preparation_ends_with_the_turn():
    assert "starts over" in preview._starting("x")["user_message"]
    build = (Path(preview.__file__).parents[3] / "plugin" / "skills" / "specialist-build" / "SKILL.md")
    assert "in the same turn" in " ".join(build.read_text(encoding="utf-8").split())


# --- the plausible list ----------------------------------------------------------------------------------------------

def test_what_a_watcher_holds_is_not_cleared_on_a_stale_look(tmp_path, monkeypatch):
    """Between looking and clearing, a new watcher may have the workspace."""
    left = tmp_path / f"{preview._PREFIX}taken"
    left.mkdir()
    state = preview._state_file("taken")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"workspace": "taken", "folder": str(left), "token": "t", "groups": []}))
    with open(state.with_suffix(".alive"), "a+b") as held:
        assert watcher.lock(held)
        monkeypatch.setattr(preview, "_watching", lambda path: False)
        preview._sweep()
        assert left.exists() and state.exists()
        watcher.unlock(held)
    monkeypatch.undo()
    preview._sweep()
    assert not left.exists() and not state.exists()


def test_every_test_here_leaves_data_behind_it_clean():
    assert not list((data_dir() / "previews").glob("*.json"))
    assert gitops is not None
