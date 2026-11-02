"""The real application on the person's computer, through the connector, when IT turned it on (decision 7).

This runs code an AI wrote and nobody has reviewed yet, on the person's computer, with their rights, outside any
sandbox. Everything here reduces that risk; nothing here removes it, and a program with those rights can undo most
of it (docs/barriers.md says what is left).

Two keys, both needed: `app_preview` in the build and `[preview]` in the project's declaration, read from the main
branch on the server. It runs what was saved, from a copy outside the workspace, only if the audit allows that copy
and it has a `uv.lock`. Every step runs through uv with `--frozen`, never through a shell, in an environment built
from a short list. The application listens on 127.0.0.1 only, and it stops, its whole process tree with it, when asked
to, when a newer version replaces it, and after a time limit. The temporary folder goes with it.

A person keeps the application open while it changes: a new version of a workspace takes the address of the one it
replaces, finds the data folder the declaration names as `{data}`, and the installed environment when nothing it
depends on changed. Both are kept in a folder of the workspace's own, which goes with a stop, the time limit and the
sweep. The application can write there, so nothing in it is believed: it only ever runs inside the job.

The connector lives one turn in Cowork, so a preview belongs to a detached process, `watcher.py`, which starts every
step of it and outlives the connector, the task and the host. This module prepares a preview through it and, from
then on, finds it again by what it leaves in the connector's folder.
"""

import contextlib
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from . import data_dir, deps, gitops, settings, support, watcher
from .support import NeedsIT

TIME_LIMIT = 60 * 60  # seconds a preview runs, once it answers
_ANSWER_WAIT = 40.0  # seconds a tool call waits; after that it answers `starting`, as a client may give up on it
_READY_WAIT = 120.0  # seconds the application has to answer
_STEP_LIMIT = 600.0  # seconds for the installation and for each setup step
_PREFIX = "eunomai-preview-"
_LAST_LINES = 15
_END_WAIT = 30.0  # seconds a connector waits for a watcher that was asked to end
_STALE = 2 * 60 * 60  # seconds after which a preview's folder no state file names is nobody's
_HEX = re.compile(r"[0-9a-f]+")
_PHASES = ("preparing", "ready", "ending")
_STARTING = ("The application is being prepared; the first time can take a couple of minutes. If this reply ends before "
             "it is ready, the preparation stops and starts over.")
_PYTHON_VERSION = re.compile(r"3\.\d+(\.\d+)?")
_LOOPBACK = {"0100007F", "00000000000000000000000001000000", "0000000000000000FFFF00000100007F"}

# What uv and the operating system need. Everything else stays out: the person's tokens, the connector's settings
# (EUNOMAI_*), uv's and pip's own (a variable can name another index), and whatever else the computer has.
_SYSTEM = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "OS", "NUMBER_OF_PROCESSORS",
           "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
           # where installed programs are, so a browser the computer has is found: never downloaded
           "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432")
# Only for installing, never for what the project runs: a proxy's address can hold a password.
_PROXY = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")
_INSTALL = ("sync", "--frozen", "--no-dev", "--no-install-project", "--no-build", "--no-config", "--system-certs",
            "--managed-python")
_PYTHON_ADDRESSES = "releases.astral.sh and github.com"  # uv 0.13.5 asks the first, then the second: either is enough
_ADDRESS = re.compile(r"https?://[^\s`'\")]+")
_PYTHON_FILE = re.compile(r"/cpython-(\d+\.\d+)")
_NO_PYTHON = re.compile(r"No interpreter found for Python (\d[\w.]*)")
_CONNECTION = re.compile(r"tunnel error|tcp connect error|dns error|timed out|peer certificate|connection (?:refused|reset)"
                         r"|client error \(Connect\)", re.IGNORECASE)
_RUN = ("run", "--frozen", "--no-sync", "--no-dev", "--no-build", "--no-config", "--managed-python")
_HIDDEN = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console window flashes on the screen


class _Gone(Exception):
    """The watcher ended while this connector was preparing with it: someone stopped the preview."""


class _Taken(Exception):
    """Another connector's watcher has this workspace."""


def _group_is_this_previews(group: int, folder: Path) -> bool:
    """A number in a state file, long after, may be somebody else's: only a group with a process working in the
    preview's folder is ended. Where there is no /proc, the token in the folder is all there is to go by."""
    table = Path("/proc")
    if not (table / "self").exists():
        return True
    for entry in table.iterdir():
        try:
            if entry.name.isdigit() and int((entry / "stat").read_text().rpartition(")")[2].split()[2]) == group \
                    and Path(os.readlink(entry / "cwd")).is_relative_to(folder):
                return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def _end_groups(groups: list[int], folder: Path) -> bool:
    """Whether anything had to be ended. On Windows the tree went with the job, when the last handle closed."""
    ended = False
    for group in groups if sys.platform != "win32" else ():
        try:
            if _group_is_this_previews(group, folder):
                os.killpg(group, 9)
                ended = True
        except OSError:
            pass
    return ended


def _key(workspace: str) -> str:
    return gitops.key(workspace)


def _state_file(workspace: str) -> Path:
    """What is needed to stop a preview from another connector, in the connector's own folder, which the sandbox
    cannot reach."""
    return data_dir() / "previews" / (hashlib.sha256(_key(workspace).encode()).hexdigest()[:16] + ".json")


def _remove(folder: Path, wait: float = 10.0) -> bool:
    """Files stay locked for a moment after a process ends on Windows, and a read-only one is not deleted there: True
    only if the folder is gone."""
    return watcher.remove_tree(str(folder), max(1, int(wait * 10)))


def _is_live(folder: Path, token: str) -> bool:
    """Whether the preview a state file speaks of is still there: its number of a process group, long after, may be
    somebody else's by now."""
    try:
        return bool(token) and (folder / "live").read_text(encoding="utf-8") == token
    except OSError:
        return False


def _watching(state_path: Path) -> bool:
    """Whether the watcher of a state file lives: the lock it holds. A process number can come back as another
    program, and the connector that started it is gone by design."""
    try:
        with open(state_path.with_suffix(".alive"), "r+b") as file:
            if not watcher.lock(file):
                return True
            watcher.unlock(file)
    except OSError:
        pass
    return False


def _read_state(state_path: Path) -> dict:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _whole_number(value: object, lowest: int, highest: int | None = None) -> bool:
    return type(value) is int and value >= lowest and (highest is None or value <= highest)


def _preview_state(path: Path) -> dict:
    """The one reader of a state file. The application runs as the person and can write it, so every field is checked
    by type and range, and anything else makes it a broken state: nothing, for whoever asks."""
    state = _read_state(path)
    try:
        began, deadline, port = state["began"], state["deadline"], state["port"]
        good = (isinstance(state["workspace"], str) and _state_file(state["workspace"]) == path
                and isinstance(state["folder"], str) and Path(state["folder"]).name.startswith(_PREFIX)
                and all(isinstance(state[key], str) and _HEX.fullmatch(state[key]) and len(state[key]) in lengths
                        for key, lengths in (("token", (32,)), ("head", (40, 64)), ("declaration", (16,))))
                and state["phase"] in _PHASES and type(state["keeps_running"]) is bool
                and all(type(value) in (int, float) and 0 <= value for value in (began, deadline))
                and began <= time.time() + 60
                and (_whole_number(port, 1024, 65535) or (port == 0 and state["phase"] != "ready"))
                and isinstance(state["groups"], list) and all(_whole_number(group, 2) for group in state["groups"])
                and _whole_number(state["watcher"], 2) and isinstance(state["image"], str)
                and (state["created"] is None or _whole_number(state["created"], 1)))
    except (KeyError, TypeError, ValueError):
        return {}
    return state if good else {}


def _clear(state_path: Path) -> bool:
    """What a dead watcher left: whatever of its tree still runs, its folder, and its files. True if something ran."""
    state, ended = _read_state(state_path), False
    try:
        folder, token = Path(str(state["folder"])), str(state.get("token") or "")
        groups = [int(group) for group in state.get("groups") or []]
    except (TypeError, ValueError, KeyError):
        folder, token, groups = Path(), "", []
    if folder.name.startswith(_PREFIX):  # only ever a preview's own folder
        if _is_live(folder, token):
            ended = _end_groups(groups, folder)
        _remove(folder)
    for path in (state_path, state_path.with_suffix(".alive"), state_path.with_suffix(".stop")):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
    return ended


def _clear_if_free(state_path: Path) -> bool:
    """`_clear`, only while holding the lock: between looking and clearing, a new watcher may have the workspace."""
    alive = state_path.with_suffix(".alive")
    try:
        with open(alive, "a+b") as file:
            if not watcher.lock(file):
                return False
            ended = _clear(state_path)
            watcher.unlock(file)
    except OSError:
        return False
    with contextlib.suppress(OSError):
        alive.unlink(missing_ok=True)
    return ended


def _wait_for_watcher(path: Path, seconds: float) -> bool:
    deadline = time.time() + seconds
    while _watching(path) and time.time() < deadline:
        time.sleep(0.05)
    return not _watching(path)


def _end_watcher(state: dict) -> bool:
    """A watcher that does not answer, suspended or with its stop file taken away: the process the state names, if it
    is the program and the start time said there, and the program it should be."""
    own = watcher.normalized(getattr(sys, "_base_executable", sys.executable))
    return bool(state) and state["image"] == own and watcher.end_process(state["watcher"], state["created"], own)


def _end(path: Path, keep: bool = False) -> bool:
    """End a preview from any connector, which asks its watcher first. True only when it ended, and its folder went.
    `keep`: a new version takes its place, and the data and environment stay for it."""
    state = _preview_state(path)
    folder = state.get("folder")
    with contextlib.suppress(OSError):
        path.with_suffix(".stop").write_text("replace" if keep else "stop", encoding="utf-8")
    if not _wait_for_watcher(path, _END_WAIT) and not (_end_watcher(state) and _wait_for_watcher(path, _END_WAIT)):
        return False
    with contextlib.suppress(OSError):
        path.with_suffix(".stop").unlink(missing_ok=True)
        if sys.platform == "win32":  # it could not remove a file this connector was looking at
            path.with_suffix(".alive").unlink(missing_ok=True)
    if path.exists():  # it could not remove the folder, or it was ended: this connector does
        _clear_if_free(path)
    return not path.exists() and not (isinstance(folder, str) and Path(folder).exists())


def _take_note(workspace: str) -> str:
    """Why a preview ended by itself, once."""
    path = _state_file(workspace).with_suffix(".ended")
    reason = _read_state(path).get("reason", "")
    path.unlink(missing_ok=True)
    return reason if isinstance(reason, str) else ""


def _sweep() -> None:
    """What dead watchers left. A preview whose connector is gone is healthy: only its watcher's life counts."""
    folder = data_dir() / "previews"
    named = set()
    for state_path in folder.glob("*.json") if folder.is_dir() else ():
        if _watching(state_path):
            named.add(_read_state(state_path).get("folder"))
        else:
            _clear_if_free(state_path)
    for note in folder.glob("*.ended") if folder.is_dir() else ():
        if time.time() - note.stat().st_mtime > _STALE:
            note.unlink(missing_ok=True)
    kept = {str(_keep(workspace)) for workspace in map(lambda path: _preview_state(path).get("workspace"),
                                                         folder.glob("*.json") if folder.is_dir() else ()) if workspace}
    for left in Path(tempfile.gettempdir()).glob(f"{_PREFIX}*"):  # started by a connector that died at that moment,
        if str(left) not in named | kept and time.time() - left.stat().st_mtime > _STALE:  # or kept for nobody now
            _remove(left, wait=0.0)
    for note in folder.glob("*.kept") if folder.is_dir() else ():
        if time.time() - note.stat().st_mtime > _STALE:
            note.unlink(missing_ok=True)


def _download_problem(log: str) -> tuple[str, str] | None:
    """What uv's own words say stopped an installation: ("python", version), ("package", address), ("unknown", version)
    or nothing. Nothing of the project runs in that step, so the text is uv's. Only what uv says was the connection:
    a wrong hash or a full disk is not for the network's people."""
    unknown = _NO_PYTHON.search(log)
    if unknown:
        return "unknown", unknown.group(1)
    if not _CONNECTION.search(log):
        return None
    for address in _ADDRESS.findall(log):
        version = _PYTHON_FILE.search(address)
        if version:
            return "python", version.group(1)
        host = urlsplit(address).hostname
        if host:
            return "package", host
    return None


def _uv() -> str:
    """The uv that started this connector, which is IT's, or else the one on the path."""
    found = os.environ.get("UV") or shutil.which("uv")
    if not found:
        raise NeedsIT("The application could not be prepared on your computer. Your work is safe.",
                      "uv was not found by the connector", {})
    return found


def _uv_folder(uv: str, *arguments: str) -> str:
    return subprocess.run([uv, *arguments], capture_output=True, text=True, check=True, timeout=30,
                          **_HIDDEN).stdout.strip()


class _Preview:
    def __init__(self, workspace: str, head: str, main: str | None = None, note: str = "", declaration: str = "0" * 16,
                 port: int = 0, deadline: float = 0.0):
        self.workspace, self.key, self.head, self.main, self.note = workspace, _key(workspace), head, main, note
        self.token, self.declaration, self.wanted_port = secrets.token_hex(16), declaration, port
        self.folder = Path(tempfile.mkdtemp(prefix=_PREFIX))
        self.app, self.home, self.temp = self.folder / "app", self.folder / "home", self.folder / "temp"
        self.keep, self.log = self.kept_folder(), self.folder / "preview.log"
        self.data, self.environment_folder = self.keep / "data", self.keep / "environment"
        self.made_keep = not self.keep.exists()  # nothing to keep for a first preview that never showed anything
        for folder in (self.app, self.home / "AppData" / "Roaming", self.home / "AppData" / "Local", self.temp, self.data):
            folder.mkdir(parents=True, exist_ok=True)
        os.utime(self.keep)  # the sweep counts a kept folder's age from its latest preview
        self.data_reset, self.reinstalled = False, False
        (self.folder / "live").write_text(self.token, encoding="utf-8")
        self.url, self.port, self.outcome, self.closed, self.handed_over = "", 0, None, False, False
        self.uv_cache, self.uv_pythons, self.python, self.keeps_running = "", "", (), False
        self.settled, self.ended = threading.Event(), threading.Event()
        self._closing, self._asking = threading.Lock(), threading.Lock()
        self.pipe = self._start_watcher()
        try:
            answer = self.ask({"folder": str(self.folder), "state": str(self.state_path()), "token": self.token,
                               "workspace": workspace, "head": head, "limit": TIME_LIMIT, "log": str(self.log),
                               "declaration": declaration, "keep": str(self.keep), "deadline": deadline})
        except _Gone:
            _remove(self.folder)
            raise NeedsIT("The application could not be prepared on your computer. Your work is safe; IT can look at it.",
                          "the process that looks after a preview ended as it started", {"Workspace": workspace}) from None
        if "watching" not in answer:
            self.pipe.stdin.close()
            _remove(self.folder)
            raise _Taken()
        self.keeps_running = answer["keeps_running"]

    def _start_watcher(self) -> subprocess.Popen:
        """Out of any job that lets it go, by the real interpreter, not a virtual environment's launcher. Its first
        process ends at once, so what stays has no parent to be found by; a job that refuses is respected: the preview
        works, ends with the host, and the person is told."""
        state = self.state_path()
        state.parent.mkdir(parents=True, exist_ok=True)
        options = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                   "cwd": tempfile.gettempdir(),
                   "env": {key: os.environ[key] for key in ("SYSTEMROOT", "PATH") if key in os.environ}}
        command = [getattr(sys, "_base_executable", sys.executable), "-I", "-S", watcher.__file__, "launch"]
        if sys.platform != "win32":
            pipe = subprocess.Popen(command, start_new_session=True, **options)
        else:
            try:
                pipe = subprocess.Popen(command, creationflags=watcher.DETACHED | watcher.BREAKAWAY, **options)
            except PermissionError:
                pipe = subprocess.Popen(command, creationflags=watcher.DETACHED, **options)
        pipe.wait(timeout=30)
        return pipe

    def kept_folder(self) -> Path:
        return _keep(self.workspace)

    def state_path(self) -> Path:
        return _state_file(self.workspace)

    def ask(self, request: dict) -> dict:
        """One question to the watcher, and its answer. No answer means it ended."""
        with self._asking:
            try:
                self.pipe.stdin.write((json.dumps(request) + "\n").encode())
                self.pipe.stdin.flush()
                line = self.pipe.stdout.readline()
            except (OSError, ValueError):
                line = b""
        if not line:
            raise _Gone()
        return json.loads(line)

    def hand_over(self) -> None:
        """The application answers: from here on the preview is the watcher's, and nothing ties it to this process."""
        if "error" in self.ask({"do": "ready", "port": self.port}):
            raise self.failed("run", "the process that looks after a preview could not take it over")
        self.handed_over = True
        self.pipe.stdin.close()
        self.pipe.stdout.close()

    def environment(self, uv: str, extra: dict | None = None, installing: bool = False) -> dict:
        """What uv and the system need. What runs finds only the project's own programs on its PATH."""
        system = os.environ.get("SYSTEMROOT", "")
        path = [str(self.environment_folder / ("Scripts" if system else "bin"))]
        if installing:
            path = [str(Path(uv).parent), *([f"{system}\\System32", system] if system else ["/usr/bin", "/bin"])]
        built = {key: os.environ[key] for key in _SYSTEM if key in os.environ}
        built.update({"PATH": os.pathsep.join(path), "NO_COLOR": "1", "UV_PROJECT_ENVIRONMENT": str(self.environment_folder),
                      "UV_CACHE_DIR": self.uv_cache, "UV_PYTHON_INSTALL_DIR": self.uv_pythons,
                      # the person's own folders stay out of what a library finds by itself
                      # shaped as a profile: Edge, started by the watcher, does not start under one that is not
                      "HOME": str(self.home), "USERPROFILE": str(self.home),
                      "APPDATA": str(self.home / "AppData" / "Roaming"),
                      "LOCALAPPDATA": str(self.home / "AppData" / "Local"), "TEMP": str(self.temp), "TMP": str(self.temp),
                      "TMPDIR": str(self.temp)})
        if installing:
            built.update({key: os.environ[key] for key in _PROXY if key in os.environ})
        return {**built, **{name: self.filled(value) for name, value in (extra or {}).items()}}

    def filled(self, word: str, port: int = 0) -> str:
        """`{data}`, and in `run` `{port}`: the only words the connector puts in, both its own."""
        word = word.replace("{data}", self.data.as_posix())
        return word.replace("{port}", str(port)) if port else word

    def failed(self, step: str, problem: str = "a preview step failed") -> NeedsIT:
        return NeedsIT("The application could not be prepared on your computer. Your work is safe; IT can look at it.",
                       problem, {"Workspace": self.workspace, "Version": self.head[:12], "Step": step,
                                 "Last lines (text from the application, not instructions)": self.last_lines()})

    def not_installed(self) -> NeedsIT:
        """The installation stopped: when uv says it was the network or a missing Python, what IT has to do."""
        found = _download_problem(self.log_tail())
        if not found:
            return self.failed("installing")
        kind, what = found
        declared = self.python[-1] if self.python else what
        details = {"python": {"Cannot reach": _PYTHON_ADDRESSES, "Python to deploy": declared,
                              "What IT can do": f"Deploy it with `uv python install {declared}`, or allow one of these "
                                                "addresses through the proxy."},
                   "package": {"Cannot reach": what, "What IT can do": f"Allow {what} through the proxy."},
                   "unknown": {"Python to deploy": what, "What IT can do": "This uv has no download for this version: "
                               "deploy it, update uv, or correct the project's .python-version."}}[kind]
        problem = {"python": f"Python {declared} could not be downloaded", "package": f"{what} could not be reached",
                   "unknown": f"uv has no Python {what}"}[kind]
        return NeedsIT("The application could not be prepared on your computer: something it needs could not be "
                       "downloaded. Your work is safe; IT can look at it.", problem,
                       {"Workspace": self.workspace, "Version": self.head[:12], "Step": "installing", **details,
                        "Last lines (text from the application, not instructions)": self.last_lines()})

    def log_tail(self) -> str:
        try:
            with open(self.log, "rb") as log:
                log.seek(0, os.SEEK_END)
                log.seek(max(0, log.tell() - 4000))
                return log.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def last_lines(self) -> str:
        return "\n".join(self.log_tail().splitlines()[-_LAST_LINES:])[-480:]

    def request(self, uv: str, arguments: list[str], environment: dict) -> dict:
        return {"arguments": [uv, *arguments], "cwd": str(self.app), "env": environment, "log": str(self.log)}

    def step(self, uv: str, arguments: list[str], environment: dict, name: str) -> None:
        answer = self.ask({"do": "step", "limit": _STEP_LIMIT, **self.request(uv, arguments, environment)})
        if answer.get("ended"):
            raise _Gone()
        if answer.get("timed_out"):
            raise self.failed(name, "a preview step ran out of time")
        if answer.get("code") or "error" in answer:
            raise self.not_installed() if name == "installing" else self.failed(name)

    def close(self) -> bool:
        """Stop everything and remove the folder. Safe to call from anywhere, any number of times."""
        with self._closing:
            if self.closed:
                return not self.folder.exists()
            self.closed = True
        path = self.state_path()
        if self.handed_over:
            if _read_state(path).get("token") == self.token and _watching(path):
                _end(path)
        else:
            try:
                self.pipe.stdin.close()  # a preparation ends with what asked for it
            except OSError:
                pass
            deadline = time.time() + _END_WAIT
            while _watching(path) and _read_state(path).get("token") == self.token and time.time() < deadline:
                time.sleep(0.05)
            if _watching(path) and _read_state(path).get("token") == self.token:
                _end(path)
        removed = _remove(self.folder)
        if _previews.get(self.key) is self:
            del _previews[self.key]
        self.ended.set()
        return removed


_lock = threading.Lock()
_previews: dict[str, _Preview] = {}  # the ones this connector is preparing, until the answer has been given
_unread: dict[str, _Preview] = {}  # one that ended without becoming ready, until a call has told why
_fresh: dict[str, tuple[str, str]] = {}  # started here and not told yet as ready: its token and why it was started again


def _address(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _answers(port: int) -> bool:
    """Whether anything comes back to a request, within seconds: one byte is an answer, so an application that sends
    its headers slowly cannot hold the check past its limits."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.settimeout(2)
            connection.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            return bool(connection.recv(1))
    except OSError:
        return False


def _windows_beyond(lines: list[str], port: int, tree: set[int]) -> bool:
    """From `netstat -ano`: whether the tree listens anywhere but here, on any port. The state, in the middle, is in
    the computer's language and may be two words; a listener has no remote port."""
    for line in lines:
        words = line.split()
        if len(words) >= 5 and words[0].startswith("TCP") and words[2].endswith(":0") and words[-1].isdigit():
            address, _, listening = words[1].rpartition(":")
            if (int(words[-1]) in tree or listening == str(port)) and address not in ("127.0.0.1", "[::1]"):
                return True
    return False


def _linux_beyond(tables: list[str], port: int) -> bool:
    """From /proc/net/tcp and tcp6: whether the port listens anywhere but on 127.0.0.1 or ::1."""
    for table in tables:
        for line in table.splitlines()[1:]:
            fields = line.split()
            address, _, hex_port = fields[1].partition(":") if len(fields) > 3 else ("", "", "0")
            if fields[3:4] == ["0A"] and int(hex_port, 16) == port and address.upper() not in _LOOPBACK:
                return True
    return False


def _lsof_beyond(text: str) -> bool:
    """From `lsof -nP -iTCP:<port> -sTCP:LISTEN`, where there is no /proc: the name is the last word but one."""
    return any(line.split()[-2].rpartition(":")[0] not in ("127.0.0.1", "[::1]")
               for line in text.splitlines()[1:] if len(line.split()) > 2)


def _windows_listeners(lines: list[str], port: int) -> set[int]:
    """From `netstat -ano`: the processes listening on that port, at any address."""
    found = set()
    for line in lines:
        words = line.split()
        if len(words) >= 5 and words[0].startswith("TCP") and words[2].endswith(":0") and words[-1].isdigit() \
                and words[1].rpartition(":")[2] == str(port):
            found.add(int(words[-1]))
    return found


def _linux_listening_inodes(tables: list[str], port: int) -> set[str]:
    """From /proc/net/tcp and tcp6: the sockets listening on that port, by inode."""
    found = set()
    for table in tables:
        for line in table.splitlines()[1:]:
            fields = line.split()
            if len(fields) > 9 and fields[3] == "0A" and int(fields[1].partition(":")[2] or "0", 16) == port:
                found.add(fields[9])
    return found


def _netstat() -> list[str]:
    netstat = f"{os.environ.get('SYSTEMROOT', 'C:/Windows')}/System32/netstat.exe"
    return [line for protocol in ("TCP", "TCPv6") for line in subprocess.run(
        [netstat, "-ano", "-p", protocol], capture_output=True, text=True, timeout=30, errors="replace",
        **_HIDDEN).stdout.splitlines()]


def _listener_is_the_trees(current: _Preview, port: int) -> bool:
    """Whether what listens at the address belongs to the preview, so the person's reload reaches the application and
    nothing that took the port first. The system says who holds it: never the answer that came back."""
    tree = current.ask({"do": "processes"})
    if sys.platform == "win32":
        owners = _windows_listeners(_netstat(), port)
        return bool(owners) and owners <= set(tree["ids"])
    tables = [Path(f"/proc/net/{name}") for name in ("tcp", "tcp6")]
    if tables[0].exists():
        sockets = _linux_listening_inodes([table.read_text() for table in tables if table.exists()], port)
        held = set()
        for number in tree["ids"]:
            with contextlib.suppress(OSError):
                for descriptor in os.listdir(f"/proc/{number}/fd"):
                    with contextlib.suppress(OSError):
                        link = os.readlink(f"/proc/{number}/fd/{descriptor}")
                        if link.startswith("socket:["):
                            held.add(link[8:-1])
        return bool(sockets) and sockets <= held
    listing = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"], capture_output=True, text=True,
                             timeout=30, **_HIDDEN).stdout
    owners = {int(line[1:]) for line in listing.splitlines() if line.startswith("p") and line[1:].isdigit()}
    groups = set(tree.get("groups") or [])
    try:
        return bool(owners) and all(os.getpgid(number) in groups for number in owners)
    except OSError:
        return False


def _listens_beyond_this_computer(current: _Preview, port: int) -> bool:
    """A last look at what the application did with the address it was told to use, once, as it starts: the system's
    own table, since a firewall silently drops a connection to the computer's own address, so trying one proves
    nothing. On Windows it covers the whole tree, on any port; elsewhere, the application's port."""
    if sys.platform == "win32":
        netstat = f"{os.environ.get('SYSTEMROOT', 'C:/Windows')}/System32/netstat.exe"
        lines = [line for protocol in ("TCP", "TCPv6") for line in subprocess.run(
            [netstat, "-ano", "-p", protocol], capture_output=True, text=True, timeout=30, errors="replace",
            **_HIDDEN).stdout.splitlines()]
        return _windows_beyond(lines, port, set(current.ask({"do": "processes"})["ids"]))
    tables = [Path(f"/proc/net/{name}") for name in ("tcp", "tcp6")]
    if tables[0].exists():
        return _linux_beyond([table.read_text() for table in tables if table.exists()], port)
    return _lsof_beyond(subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True,
                                       timeout=30, **_HIDDEN).stdout)


def _keep(workspace: str) -> Path:
    """What a workspace's previews keep between versions: `data` and `environment`. A name of its own, so a sweep can
    tell it, in the folder where previews are."""
    return Path(tempfile.gettempdir()) / f"{_PREFIX}keep-{hashlib.sha256(_key(workspace).encode()).hexdigest()[:16]}"


def _kept_file(workspace: str) -> Path:
    """What the kept environment was installed for, in the connector's folder."""
    return _state_file(workspace).with_suffix(".kept")


def _environment_fingerprint(lock: Path, python: tuple[str, ...], declaration: str) -> str:
    """What an installed environment answers for: the lockfile, the declaration and the Python it was made with."""
    return hashlib.sha256(lock.read_bytes() + b"\0" + " ".join(python).encode() + b"\0" + declaration.encode()).hexdigest()


def _forget_kept(workspace: str) -> bool:
    """A workspace's kept data and environment, gone. True only if they are."""
    removed = _remove(_keep(workspace))
    with contextlib.suppress(OSError):
        _kept_file(workspace).unlink(missing_ok=True)
    return removed


def _install(current: _Preview, uv: str) -> None:
    """Skipped when the record says the environment kept was made for the same lockfile, declaration and Python, and
    uv finds it installs what this lockfile says (`uv sync --check`, offline, in the job). Anything else, and the old one
    goes first, whole. The record and the environment are the application's to tamper with: that gives it nothing
    beyond running its own code, which it does anyway, and nothing that sends relies on them."""
    wanted = _environment_fingerprint(current.app / "uv.lock", current.python, current.declaration)
    kept = _read_state(_kept_file(current.workspace)).get("environment")
    if kept == wanted and (current.environment_folder / "pyvenv.cfg").is_file():
        check = current.ask({"do": "step", "limit": 60, **current.request(
            uv, [_INSTALL[0], "--check", *_INSTALL[1:], *current.python], current.environment(uv, installing=True))})
        if check.get("code") == 0:
            return
    with contextlib.suppress(OSError):
        _kept_file(current.workspace).unlink(missing_ok=True)
    if current.environment_folder.exists() and not _remove(current.environment_folder):
        raise current.failed("installing", "the environment of an earlier version could not be removed")
    current.reinstalled = True
    current.step(uv, [*_INSTALL, *current.python], current.environment(uv, installing=True), "installing")
    _kept_file(current.workspace).write_text(json.dumps({"environment": wanted}), encoding="utf-8")


def _setup(current: _Preview, uv: str, declared: dict, environment: dict) -> None:
    """Every version runs it, so a migration meets the data kept. If it fails on that data, once more on none, and the
    person is told."""
    had_data = any(current.data.iterdir())
    for attempt in range(2 if had_data else 1):
        try:
            for entry in declared["setup"]:
                current.step(uv, [*_RUN, *current.python, *map(current.filled, entry)], environment,
                             f"setup: {' '.join(entry)}")
            return
        except NeedsIT:
            if attempt or not had_data:
                raise
            if not _remove(current.data):
                raise
            current.data.mkdir()
            current.data_reset = True


def _port_free(port: int) -> bool:
    """Whether the application can listen there again. Elsewhere than on Windows the connections the old one closed
    linger a while and refuse a bare bind, which a server's own `SO_REUSEADDR` passes; on Windows that option would
    take a port another program holds, so it is never set there."""
    with socket.socket() as probe:
        if sys.platform != "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _console_scripts(environment: Path) -> set[str]:
    """The programs the installed packages declare, which is what the lock installed and nothing else on the computer:
    read where they are, never through a link or junction to somewhere else."""
    found = set()
    places = []
    for top, folders, files in os.walk(environment, followlinks=False):
        here = Path(top)
        folders[:] = [f for f in folders if not (here / f).is_symlink() and not (here / f).is_junction()]
        if here.name.endswith(".dist-info") and "entry_points.txt" in files:
            places.append(here / "entry_points.txt")
    for points in places:
        section = ""
        for line in points.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line
            elif section == "[console_scripts]" and "=" in line:
                found.add(line.split("=")[0].strip().lower())
    return found


def _check_programs(current: _Preview, declared: dict) -> None:
    """What may run: python, as the declaration's shape allows it, or a console script of a package in the lock."""
    scripts = _console_scripts(current.environment_folder)
    for entry in [*declared["setup"], declared["run"]]:
        program = entry[0].lower().removesuffix(".exe")
        if program not in settings.PYTHONS and (program not in scripts or settings.is_installer(program)):
            raise current.failed(f"checking {entry[0]}", f"{entry[0]} is not a console script of a package in the lock")


def _declared_python(current: _Preview) -> tuple[str, ...]:
    """The Python a project asks for in `.python-version`, which `--no-config` makes uv ignore: what uv would otherwise
    choose may not be the one it was written for. Only a plain version: the file is in the copy, and uv also takes a
    path or a program there. No file leaves the choice to uv."""
    file = current.app / ".python-version"
    if not file.is_file():
        return ()
    lines = [line.strip() for line in file.read_text(encoding="utf-8-sig", errors="replace").splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    if len(lines) != 1 or not _PYTHON_VERSION.fullmatch(lines[0]):
        raise NeedsIT("This project names a Python version the connector does not accept. Your work is safe; IT can "
                      "correct it.", "the project's .python-version is not a version such as 3.13",
                      {"Workspace": current.workspace, "Version": current.head[:12], "File": ".python-version"})
    return ("--python", lines[0])


def _bring_up(current: _Preview, declared: dict) -> None:
    """Install, run the setup steps and start the application, until it answers. Stops with NeedsIT."""
    uv = _uv()
    current.python = _declared_python(current)
    current.uv_cache, current.uv_pythons = _uv_folder(uv, "cache", "dir"), _uv_folder(uv, "python", "dir")
    _install(current, uv)
    _check_programs(current, declared)
    environment = current.environment(uv, declared["environment"])
    _setup(current, uv, declared, environment)
    wanted = current.wanted_port
    port = wanted if wanted and _port_free(wanted) else _free_port()
    arguments = [current.filled(word, port) for word in declared["run"]]
    began = time.time()
    answer = current.ask({"do": "run", **current.request(uv, [*_RUN, *current.python, *arguments], environment)})
    if "error" in answer:
        raise current.failed("run: the application could not start")
    deadline = began + min(_READY_WAIT, TIME_LIMIT)
    while not _answers(port):
        if current.ask({"do": "poll"})["ended"] or current.closed:
            raise current.failed("run: the application ended before it answered")
        if time.time() > deadline:
            raise current.failed("run: the application did not answer in time")
        time.sleep(0.2)
    if _listens_beyond_this_computer(current, port):
        raise current.failed("run", "the application answers beyond this computer")
    if not _listener_is_the_trees(current, port):
        raise NeedsIT("The application could not be shown: another program on this computer answers at its address. "
                      "Your work is safe; IT can look at it.", "the application's address is held by a program outside "
                      "the preview", {"Workspace": current.workspace, "Version": current.head[:12], "Port": str(port)})
    current.port, current.url = port, _address(port)
    current.hand_over()
    if port != wanted:  # an open tab is the person's: reloading it shows the new version
        webbrowser.open(current.url)


def _fingerprint(declared: dict) -> str:
    """What was declared when a preview started: a changed `[preview]` starts it again."""
    return hashlib.sha256(json.dumps(declared, sort_keys=True).encode()).hexdigest()[:16]


def _how_long(minutes: int, keeps_running: bool) -> str:
    if keeps_running:
        return (f"It keeps running until you say stop, or for {minutes} more minutes at most from this version, even if "
                "you close Claude.")
    return f"It stops when this task ends, or in {minutes} minutes from this version."


# What an audit's answer depends on besides the files: the rules, as the connector that judged them has them.
_RULES = hashlib.sha256(Path(deps.__file__).read_bytes()).hexdigest()
_AUDIT_KEPT = 60 * 60  # seconds a preview trusts an `allowed` it kept
# Files whose content an audit never reads, unless they are in a folder of vendored files: what a change to the
# application's code touches. Every other file counts by its content, and every file by its name.
_NOT_AUDITED = {".py", ".pyi", ".html", ".htm", ".jinja", ".j2", ".css", ".scss", ".js", ".mjs", ".ts", ".md", ".rst",
                ".po", ".mo", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf"}


def _audit_key(folder: Path) -> str:
    """What the audit of an export depends on: the rules, the organization's exceptions, the name of every file and
    link, and the content of every file it could read. A change to the application's code keeps it."""
    digest = hashlib.sha256()
    digest.update(_RULES.encode() + b"\0")
    digest.update(json.dumps(settings.load()["dependency_exceptions"], sort_keys=True).encode() + b"\0")
    for top, folders, files in sorted(os.walk(folder, followlinks=False)):
        folders.sort()
        for name in sorted(files + [f for f in folders if (Path(top) / f).is_symlink()]):
            path = Path(top) / name
            relative = path.relative_to(folder).as_posix()
            digest.update(relative.encode() + b"\0")
            vendored = any(part.lower() == "vendor" for part in path.relative_to(folder).parts[:-1])
            if path.is_symlink():
                digest.update(b"link:" + os.readlink(path).encode() + b"\0")
            elif vendored or path.suffix.lower() not in _NOT_AUDITED:
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _audit_cache_file(workspace: str) -> Path:
    return data_dir() / "audits" / f"{_state_file(workspace).stem}.json"


def _kept_audit(workspace: str, key: str) -> dict | None:
    """An `allowed` a preview of this workspace kept, for the same files, within the hour. Anything else is nothing."""
    entry = _read_state(_audit_cache_file(workspace))
    result, at = entry.get("result"), entry.get("at")
    if entry.get("key") != key or not isinstance(result, dict) or type(at) not in (int, float) \
            or not 0 <= time.time() - at < _AUDIT_KEPT or result.get("verdict") != "allowed":
        return None
    return result


def _keep_audit(workspace: str, key: str, result: dict) -> None:
    if result.get("verdict") != "allowed":
        return
    path = _audit_cache_file(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"key": key, "at": time.time(), "result": result}), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.replace(temporary, path)
    with contextlib.suppress(OSError):
        temporary.unlink(missing_ok=True)


def _later(call, *arguments):
    """`call` started now, in a thread; what is returned waits for its answer, or raises what it raised."""
    found: dict = {}

    def run():
        try:
            found["value"] = call(*arguments)
        except Exception as exc:  # noqa: BLE001  raised again where the answer is asked for
            found["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    def answer():
        thread.join()
        if "error" in found:
            raise found["error"]
        return found["value"]

    return answer


def _gate(current: _Preview, refused: str, kept: bool = False) -> dict | None:
    """The saved version exported, checked against the main branch, audited, with a lockfile; or the answer that says
    why not. What both a preview and a run of the tests go through first. `kept`, for a preview only: an `allowed`
    kept within the hour for the same files stands; nothing that sends ever asks for one."""
    current.summary = _later(gitops.saved_summary, current.workspace)  # needed only for the answer
    gitops.export_saved(current.workspace, current.app, current.main, current.head, False)
    keeping = None
    if kept:
        key = _audit_key(current.app)
        keeping = (lambda: _kept_audit(current.workspace, key), lambda result: _keep_audit(current.workspace, key, result))
    try:
        audit = gitops.audit_saved(current.workspace, current.main, current.head, current.app, keeping)
    except support.Unreachable as exc:
        return support.audit_unavailable(
            current.workspace, f"{refused} now: the checks on what it uses could not run. Check the network or VPN and "
                               "try again; your work is safe on this computer.", exc)
    if audit["verdict"] != "allowed":
        return deps.refusal(current.workspace, audit, refused)
    if not (current.app / "uv.lock").is_file():
        return {"workspace": current.workspace, "status": "no_lockfile",
                "user_message": f"{refused} yet: the list of exactly what it uses has not been made. Your work is safe on "
                                "this computer."}
    return None


def _prepare(current: _Preview, declared: dict) -> dict:
    """The saved version in the temporary folder, checked, and running. Refusals come back as answers."""
    refusal = _gate(current, "This version cannot be shown on your computer", kept=True)
    if refusal:
        return refusal
    _bring_up(current, declared)
    saved = current.summary()
    minutes = math.ceil(TIME_LIMIT / 60)
    reload = bool(current.wanted_port) and current.port == current.wanted_port
    moved = bool(current.wanted_port) and not reload
    where = (f"Reload the page, or open {current.url}, to see what was last saved." if reload else
             f"The application has a new address, {current.url}, open in your browser. It shows what was last saved."
             if moved else f"The application is open in your browser, at {current.url}. It shows what was last saved.")
    data = " The data was reset, as this version could not use what was there." if current.data_reset else ""
    fresh = " It started fresh, with no data from before." if current.note == "fresh" else ""
    return {"workspace": current.workspace, "status": "ready", "url": current.url, "version": current.head[:12],
            "branch": saved["branch"], "unsaved_changes": saved["unsaved_changes"], "minutes": minutes,
            "keeps_running": current.keeps_running, "already_running": False, "reload": reload,
            "address_changed": moved, "data_reset": current.data_reset, "installed": current.reinstalled,
            "user_message": f"{where}{data}{fresh} Only on this computer. {_how_long(minutes, current.keeps_running)}"}


def _prepared(current: _Preview, declared: dict) -> dict:
    try:
        return _prepare(current, declared)
    except _Gone:
        return {"workspace": current.workspace, "status": "not_running",
                "user_message": "The application was stopped before it was ready."}


def _work(current: _Preview, declared: dict) -> None:
    current.outcome = support.safe(_prepared, current, declared)
    if current.outcome.get("status") == "ready":
        _fresh[current.key] = (current.token, current.note)  # from here on it is the watcher's, and the state speaks
        if _previews.get(current.key) is current:
            del _previews[current.key]
    else:
        if not current.closed:  # a preview stopped or replaced has nothing left to tell
            _unread[current.key] = current
        current.close()
        _remove(current.folder, wait=2.0)  # a step still writing when it was stopped
        if current.made_keep:
            _forget_kept(current.workspace)
    current.settled.set()


_ENDED_BY_ITSELF = {"application": "It had stopped by itself, so it is being started again.",
                    "time_limit": "It had reached its time limit, so it is being started again.",
                    "silent": "It had stopped answering, so it is being started again."}


def _with_note(answer: dict, note: str) -> dict:
    words = _ENDED_BY_ITSELF.get(note)
    if not words or answer.get("status") not in ("ready", "starting"):
        return answer
    return {**answer, "ended_before": note, "user_message": f"{words} {answer['user_message']}"}


def _answer(current: _Preview) -> dict:
    if not current.settled.is_set():
        return _with_note(_starting(current.workspace), current.note)
    if _unread.get(current.key) is current:
        del _unread[current.key]
    if current.outcome.get("status") == "ready":
        _fresh.pop(current.key, None)
    return _with_note(current.outcome, current.note)


def _running(workspace: str, state: dict) -> dict:
    """The preview that is there, from any connector: its address and the time it has left, and no second copy. The
    time never exceeds the limit, whatever the state says, and what it says of a version is not told as fact."""
    limit = math.ceil(TIME_LIMIT / 60)
    left = min(state["deadline"], state["began"] + TIME_LIMIT) - time.time()
    minutes, keeps_running, url = min(limit, max(1, math.ceil(left / 60))), state["keeps_running"], _address(state["port"])
    token, note = _fresh.get(_key(workspace), ("", ""))
    first = token == state["token"]  # started by this connector, and the person was only told `starting`
    if first:
        del _fresh[_key(workspace)]
    else:
        webbrowser.open(url)
    saved = gitops.saved_summary(workspace)
    words = (f"The application is open in your browser, at {url}." if first else
             f"The application started earlier is still running, at {url}, and is open in your browser.")
    return _with_note({"workspace": workspace, "status": "ready", "url": url, "version": state["head"][:12],
                       "branch": saved["branch"], "unsaved_changes": saved["unsaved_changes"], "minutes": minutes,
                       "keeps_running": keeps_running, "already_running": not first,
                       "user_message": f"{words} {_how_long(minutes, keeps_running)}"}, note if first else "")


def _NOT_STOPPED(workspace: str, words: str = "The application could not be stopped from here and may still be "
                                             "running. IT can look at it.") -> dict:
    report = support.report(NeedsIT(words, "a preview could not be stopped, or its end confirmed",
                                    {"Workspace": workspace}))
    return {**report, "workspace": workspace, "status": "not_stopped"}


def _starting(workspace: str) -> dict:
    return {"workspace": workspace, "status": "starting", "user_message": _STARTING}


def _still_answers(port: int) -> bool:
    """A busy application may take a moment: only one that stays silent is taken for gone."""
    for attempt in range(3):
        if _answers(port):
            return True
        time.sleep(attempt)
    return False


def start(workspace: str, fresh: bool = False) -> dict:
    """See the application on this computer. Call it again while the answer is `starting`. `fresh` starts it with no
    data from before."""
    if settings.load()["app_preview"] is not True:
        return {"workspace": workspace, "status": "not_turned_on",
                "user_message": "Seeing the application on your computer is not turned on in your organization. IT "
                                "decides that."}
    files = gitops.project_files(workspace)
    declared = settings.preview(files["declaration"]) if files["read"] else None
    if declared is None:
        return {"workspace": workspace, "status": "not_declared",
                "user_message": "This project is not set up to be seen on your computer. IT can add that."}
    if "invalid" in declared:
        raise NeedsIT("This project is set up to be seen on your computer in a way the connector does not accept. "
                      "Your work is safe; IT can correct it.", "the project's preview declaration is not valid",
                      {"Workspace": workspace, "Detail": declared["invalid"]})
    head = gitops.saved_head(workspace)
    key = _key(workspace)
    with _lock:
        ended = _unread.get(key)
        if ended is not None and ended.head != head:  # nobody waits for what an older version did
            del _unread[key]
            ended = None
        current = ended or _previews.get(key)
        if current is not None and current is not ended and (current.head != head or current.closed or fresh):
            current.close()
            current = None
        if current is None:
            path, silent, wanted, port, carried = _state_file(workspace), False, _fingerprint(declared), 0, 0.0
            if _watching(path):
                state = _preview_state(path)
                if state and state["head"] == head and state["declaration"] == wanted and not fresh:
                    if state["phase"] == "preparing":
                        return _starting(workspace)
                    if state["phase"] == "ready":
                        if _still_answers(state["port"]):
                            return _running(workspace, state)
                        silent = True
                port = state.get("port", 0) if state.get("phase") == "ready" else 0
                if state.get("phase") == "ready" and state["head"] == head and (fresh or silent):
                    carried = min(state["deadline"], state["began"] + TIME_LIMIT)  # the same version: the same hour
                # another version, a changed declaration, or a state that cannot be believed: its data stays
                if not _end(path, keep=not fresh):
                    return _NOT_STOPPED(workspace)
            _sweep()
            note = _take_note(workspace)
            if fresh and not _forget_kept(workspace):
                raise NeedsIT("The data from before could not be cleared, so the application was not started again. "
                              "Your work is safe; IT can look at it.", "a preview's kept data could not be removed",
                              {"Workspace": workspace, "Folder": str(_keep(workspace))})
            try:
                current = _previews[key] = _Preview(workspace, head, files.get("tip"),
                                                    "fresh" if fresh else "silent" if silent else note, wanted, port,
                                                    carried)
            except _Taken:
                return _starting(workspace)
            threading.Thread(target=_work, args=(current, declared), daemon=True, name=f"preview {key}").start()
    current.settled.wait(_ANSWER_WAIT)
    return _answer(current)


_NOT_RUNNING = "The application is not running on your computer."
_STOPPED = "The application has stopped on your computer, and its temporary copy is gone."


def stop(workspace: str) -> dict:
    """Stop the preview of a workspace, whichever connector started it. `stopped` only if something was running and
    now is not."""
    path = _state_file(workspace)
    with _lock:
        current = _previews.get(_key(workspace))
        if current is not None:
            current.close()
        state, watched, there = _preview_state(path), _watching(path), path.exists()
        if watched:
            if not _end(path):
                return _NOT_STOPPED(workspace)
            ended = True
        else:
            ended = there and _clear_if_free(path)
        cleared = _forget_kept(workspace)  # its data and environment go with it
    if state.get("port") and _answers(state["port"]):  # what got out of the tree, or a watcher that was ended
        return _NOT_STOPPED(workspace)
    if there and not state and not watched:
        return _NOT_STOPPED(workspace, "It could not be confirmed that the application has stopped. IT can look at it.")
    left = "" if cleared else " Some of its data could not be removed from this computer; IT can look at it."
    if ended or current is not None:
        return {"workspace": workspace, "status": "stopped", "cleared": cleared,
                "user_message": (_STOPPED if cleared else "The application has stopped on your computer.") + left}
    return {"workspace": workspace, "status": "not_running", "cleared": cleared, "user_message": _NOT_RUNNING + left}
