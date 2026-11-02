"""A preview a person keeps open while the specialist changes it: the same address, their data kept, and a change
that takes seconds because nothing that stayed the same is installed again."""

import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from conftest import alive
from test_preview import LOCK, PYPROJECT, browser, folders, nothing_left_behind, pids, show, turned_on  # noqa: F401

from eunomai_business import gitops, preview, server as tools, settings

needs_uv = pytest.mark.skipif(not (os.environ.get("UV") or preview.shutil.which("uv")), reason="needs uv")
real = [pytest.mark.preview, needs_uv]
WINDOWS = sys.platform == "win32"

# Notes every start in the kept folder, says what it shows, and can be told to leave something setup refuses.
LIVE = b'''import http.server, json, os, pathlib, sys

arguments = sys.argv[1:]
host, port = arguments[arguments.index("--host") + 1], int(arguments[arguments.index("--port") + 1])
data = pathlib.Path(os.environ["DATA_DIR"])
with open(data / "runs.txt", "a") as runs:
    runs.write(pathlib.Path("message.txt").read_text().strip() + "\\n")
pathlib.Path(os.environ["PIDS_FILE"]).write_text(json.dumps([os.getpid()]))


class Answer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/poison":
            (data / "poison").write_text("x")
        text = (data / "runs.txt").read_text() if self.path == "/runs" else pathlib.Path("message.txt").read_text()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(text.encode())

    def log_message(self, *args):
        pass


http.server.HTTPServer((host, port), Answer).serve_forever()
'''
# What a migration does to the kept data: it refuses what it cannot read.
MIGRATE = b'''import pathlib, sys
data = pathlib.Path(sys.argv[1])
sys.exit(5 if (data / "poison").exists() else 0)
'''


def live_declaration(pids_file: Path) -> bytes:
    return (b'[development]\ncode = true\n\n[preview]\nsetup = [["python", "migrate.py", "{data}"]]\n'
            b'run = ["python", "app.py", "--host", "127.0.0.1", "--port", "{port}"]\n\n[preview.environment]\n'
            b'DATA_DIR = "{data}"\nPIDS_FILE = "' + pids_file.as_posix().encode() + b'"\n')


def live_project(server, pids_file: Path) -> tuple[str, Path]:
    name = f"live-{uuid.uuid4().hex[:8]}"
    server.initialize(name)
    server.server_commit(name, "main", {"pyproject.toml": PYPROJECT, "uv.lock": LOCK, "app.py": LIVE,
                                        "migrate.py": MIGRATE, "message.txt": b"first\n",
                                        ".eunomai/project.toml": live_declaration(pids_file)})
    ws = Path(gitops.clone(f"{server.url}/me/{name}.git")["path"])
    gitops.branch(name, "draft/work")
    return name, ws


def change(name: str, ws: Path, file: str, content: bytes) -> None:
    (ws / file).write_bytes(content)
    gitops.save(name, f"Change {file}")


def wait_for(condition, seconds: float = 20.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


@pytest.fixture
def steps(monkeypatch) -> list[str]:
    """The name of every step a preview runs."""
    seen, real_step = [], preview._Preview.step

    def step(self, uv, arguments, environment, name):
        seen.append(name)
        return real_step(self, uv, arguments, environment, name)

    monkeypatch.setattr(preview._Preview, "step", step)
    return seen


# --- the declaration --------------------------------------------------------------------------------------------------

def declared(text: str) -> dict:
    return settings.preview({"text": text})


RUN = 'run = ["python", "app.py", "--host", "127.0.0.1", "--port", "{port}"]'


@pytest.mark.parametrize("text", [
    f'[preview]\n{RUN}\n[preview.environment]\nDATABASE_URL = "sqlite:///{{data}}/app.db"\n',
    f'[preview]\nsetup = [["python", "-m", "app.migrate", "--folder", "{{data}}"]]\n{RUN}\n',
    '[preview]\nrun = ["python", "app.py", "--host", "127.0.0.1", "--port", "{port}", "--data", "{data}"]\n'])
def test_the_data_folder_is_a_placeholder_like_the_port(text):
    assert "invalid" not in declared(text), declared(text)


@pytest.mark.parametrize("text", [
    f'[preview]\n{RUN}\n[preview.environment]\nDATABASE_URL = "{{Data}}/app.db"\n',
    f'[preview]\n{RUN}\n[preview.environment]\nDATABASE_URL = "{{data }}"\n',
    f'[preview]\n{RUN}\n[preview.environment]\nHOME_DIR = "{{home}}"\n',
    f'[preview]\n{RUN}\n[preview.environment]\nWHERE = "{{port}}"\n',
    f'[preview]\nsetup = [["python", "-m", "app.migrate", "{{port}}"]]\n{RUN}\n',
    f'[preview]\nsetup = [["python", "{{data}}/run.py"]]\n{RUN}\n',
    '[preview]\nrun = ["python", "{data}/app.py", "--host", "127.0.0.1", "--port", "{port}"]\n'])
def test_nothing_else_in_braces_and_never_a_program_from_the_data(text):
    assert "invalid" in declared(text), text


# --- a new version, the same address and the same data --------------------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_a_new_version_keeps_the_address_and_the_data_and_installs_nothing(signed_in, workspaces, turned_on, browser,
                                                                           pids, steps):
    name, ws = live_project(signed_in, pids)
    first = show(name)
    assert first["status"] == "ready", first
    assert httpx.get(first["url"] + "runs").text == "first\n" and "installing" in steps
    steps.clear()
    change(name, ws, "message.txt", b"second\n")
    second = show(name)
    assert second["status"] == "ready" and second["url"] == first["url"] and second["reload"] is True, second
    assert "Reload the page" in second["user_message"] and second["url"] in second["user_message"]
    assert browser == [first["url"]]
    assert httpx.get(second["url"]).text == "second\n"
    assert httpx.get(second["url"] + "runs").text == "first\nsecond\n"
    assert "installing" not in steps and steps, steps


@pytest.mark.preview
@needs_uv
def test_the_hour_counts_from_the_latest_version(signed_in, workspaces, turned_on, pids):
    name, ws = live_project(signed_in, pids)
    show(name)
    began = preview._preview_state(preview._state_file(name))["began"]
    time.sleep(1.1)
    change(name, ws, "message.txt", b"second\n")
    answer = show(name)
    state = preview._preview_state(preview._state_file(name))
    assert state["began"] > began and state["deadline"] == pytest.approx(state["began"] + preview.TIME_LIMIT, abs=1)
    assert "from this version" in answer["user_message"]


@pytest.mark.preview
@needs_uv
def test_a_taken_address_moves_and_says_so(signed_in, workspaces, turned_on, browser, pids, monkeypatch):
    name, ws = live_project(signed_in, pids)
    first = show(name)
    monkeypatch.setattr(preview, "_port_free", lambda port: False)
    change(name, ws, "message.txt", b"second\n")
    second = show(name)
    assert second["url"] != first["url"] and second["reload"] is False and second["address_changed"] is True
    assert "new address" in second["user_message"] and browser == [first["url"], second["url"]]
    assert "port" not in second["user_message"].lower()


@pytest.mark.preview
@needs_uv
def test_a_changed_lock_installs_anew_from_nothing(signed_in, workspaces, turned_on, pids, steps):
    name, ws = live_project(signed_in, pids)
    show(name)
    planted = preview._keep(name) / "environment" / "planted.txt"
    planted.write_text("left by the application")
    steps.clear()
    change(name, ws, "uv.lock", LOCK + b"\n")
    assert show(name)["status"] == "ready"
    assert "installing" in steps and not planted.exists()


def test_the_environment_kept_is_judged_by_lock_declaration_and_python(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_bytes(LOCK)
    first = preview._environment_fingerprint(lock, ("--python", "3.13"), "0" * 16)
    assert first == preview._environment_fingerprint(lock, ("--python", "3.13"), "0" * 16)
    assert first != preview._environment_fingerprint(lock, ("--python", "3.12"), "0" * 16)
    assert first != preview._environment_fingerprint(lock, ("--python", "3.13"), "1" * 16)
    lock.write_bytes(LOCK + b"\n")
    assert first != preview._environment_fingerprint(lock, ("--python", "3.13"), "0" * 16)


@pytest.mark.preview
@needs_uv
def test_data_setup_cannot_read_is_reset_once_and_the_person_is_told(signed_in, workspaces, turned_on, pids):
    name, ws = live_project(signed_in, pids)
    first = show(name)
    httpx.get(first["url"] + "poison")
    change(name, ws, "message.txt", b"second\n")
    second = show(name)
    assert second["status"] == "ready" and second["data_reset"] is True, second
    assert "data was reset" in second["user_message"]
    assert httpx.get(second["url"] + "runs").text == "second\n"


@pytest.mark.preview
@needs_uv
def test_a_fresh_start_on_request(signed_in, workspaces, turned_on, pids):
    name, _ = live_project(signed_in, pids)
    show(name)
    answer = tools.app_preview(name, fresh=True)
    for _ in range(150):
        if answer["status"] != "starting":
            break
        time.sleep(0.2)
        answer = tools.app_preview(name)
    assert answer["status"] == "ready" and answer["already_running"] is False, answer
    assert httpx.get(answer["url"] + "runs").text == "first\n" and "fresh" in answer["user_message"]


# --- where the kept folder goes ---------------------------------------------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_a_stop_removes_the_data(signed_in, workspaces, turned_on, pids):
    name, _ = live_project(signed_in, pids)
    show(name)
    assert preview._keep(name).is_dir()
    assert tools.app_preview_stop(name)["status"] == "stopped"
    assert not preview._keep(name).exists() and folders() == []


@pytest.mark.preview
@needs_uv
def test_the_time_limit_removes_the_data(signed_in, workspaces, turned_on, pids, monkeypatch):
    monkeypatch.setattr(preview, "TIME_LIMIT", 4)
    name, _ = live_project(signed_in, pids)
    show(name)
    assert wait_for(lambda: not preview._keep(name).exists(), 30)


@pytest.mark.preview
@needs_uv
def test_an_application_that_ended_by_itself_keeps_the_data_for_the_next(signed_in, workspaces, turned_on, pids):
    name, _ = live_project(signed_in, pids)
    show(name)
    os.kill(json.loads(pids.read_text())[0], signal.SIGKILL if not WINDOWS else signal.SIGTERM)
    assert wait_for(lambda: not preview._state_file(name).exists())
    pids.unlink()
    answer = show(name)
    assert answer["ended_before"] == "application" and httpx.get(answer["url"] + "runs").text == "first\nfirst\n"


@pytest.mark.preview
@needs_uv
def test_a_first_preview_that_shows_nothing_keeps_nothing(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, _ = live_project(signed_in, pids)
    monkeypatch.setattr(preview, "_bring_up", lambda current, declared: (_ for _ in ()).throw(current.failed("run")))
    assert show(name)["status"] == "needs_it"
    assert not preview._keep(name).exists()


def test_a_kept_folder_nothing_speaks_of_goes_once_it_is_old():
    left = preview._keep("long-gone")
    (left / "data").mkdir(parents=True, exist_ok=True)
    os.utime(left, (time.time() - preview._STALE - 60,) * 2)
    preview._sweep()
    assert not left.exists()


def test_the_data_folder_is_the_connectors_and_absolute():
    data = preview._keep("where") / "data"
    assert data.is_absolute() and data.parent.name.startswith(preview._PREFIX)
    assert data.is_relative_to(Path(preview.tempfile.gettempdir()))


# --- the audit a preview keeps --------------------------------------------------------------------------------------

ALLOWED = {"verdict": "allowed", "files": ["uv.lock"], "packages": 0, "blocked": [], "not_pinned": [],
           "without_hashes": []}


@pytest.fixture
def audits(monkeypatch) -> list:
    """Every audit that really runs, with the in-process memory of one emptied before each, as a new turn has."""
    calls = []

    def audit(folder):
        calls.append(folder)
        return dict(ALLOWED)

    monkeypatch.setattr(preview.deps, "audit", audit)
    real = gitops.audit_saved

    def fresh(*args, **kwargs):
        gitops._audits.clear()
        return real(*args, **kwargs)

    monkeypatch.setattr(gitops, "audit_saved", fresh)
    return calls


@pytest.mark.preview
@needs_uv
def test_a_change_to_the_code_reuses_the_allowed_audit(signed_in, workspaces, turned_on, pids, audits):
    name, ws = live_project(signed_in, pids)
    show(name)
    assert len(audits) == 1
    change(name, ws, "app.py", LIVE + b"# a change to the code\n")
    assert show(name)["status"] == "ready" and len(audits) == 1


@pytest.mark.preview
@needs_uv
def test_a_send_never_takes_the_kept_audit(signed_in, workspaces, turned_on, pids, audits):
    name, ws = live_project(signed_in, pids)
    show(name)
    change(name, ws, "app.py", LIVE + b"# a change to the code\n")
    show(name)
    assert len(audits) == 1
    assert tools.version_send(name)["pushed"]
    assert len(audits) == 2
    tools.version_propose(name, "A change", "It changes the message.")
    assert len(audits) == 3


@pytest.mark.preview
@needs_uv
@pytest.mark.parametrize("what", ["lock", "exceptions", "an hour", "a new file", "the rules"])
def test_anything_the_audit_depends_on_audits_again(signed_in, workspaces, turned_on, pids, audits, monkeypatch, what):
    name, ws = live_project(signed_in, pids)
    show(name)
    if what == "lock":
        change(name, ws, "uv.lock", LOCK + b"\n")
    elif what == "exceptions":
        monkeypatch.setenv("EUNOMAI_SPECIALIST", json.dumps({"app_preview": True, "dependency_exceptions": [
            {"package": "pypi:x", "reason": "r"}]}))
        change(name, ws, "app.py", LIVE + b"# a change to the code\n")
    elif what == "an hour":
        kept = preview._audit_cache_file(name)
        entry = json.loads(kept.read_text())
        kept.write_text(json.dumps({**entry, "at": entry["at"] - 3601}))
        change(name, ws, "app.py", LIVE + b"# a change to the code\n")
    elif what == "a new file":
        change(name, ws, "requirements.txt", b"# nothing\n")
    else:
        monkeypatch.setattr(preview, "_RULES", "another")
        change(name, ws, "app.py", LIVE + b"# a change to the code\n")
    assert show(name)["status"] in ("ready", "audit_refused", "needs_it") and len(audits) == 2


def test_only_an_allowed_answer_is_kept(signed_in, workspaces, pids, tmp_path):
    folder = tmp_path / "copy"
    folder.mkdir()
    (folder / "uv.lock").write_bytes(LOCK)
    key = preview._audit_key(folder)
    preview._keep_audit("refused-here", key, {**ALLOWED, "verdict": "blocked"})
    assert preview._kept_audit("refused-here", key) is None
    preview._keep_audit("allowed-here", key, ALLOWED)
    assert preview._kept_audit("allowed-here", key)["verdict"] == "allowed"
    assert preview._kept_audit("allowed-here", "another key") is None


def test_barriers_say_why_a_kept_audit_is_for_previews_only():
    text = " ".join((Path(preview.__file__).parents[3] / "docs" / "barriers.md").read_text(encoding="utf-8").split())
    assert "never trust it" in text and "a forged entry gives it nothing it lacks" in text
