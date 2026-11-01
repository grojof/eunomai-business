"""The real application on the person's computer, through the connector, when IT turned it on (decision 7).

This runs code an AI wrote and nobody has reviewed yet, on the person's computer, with their rights, outside any
sandbox. Everything here reduces that risk; nothing here removes it, and a program with those rights can undo most
of it (docs/barriers.md says what is left).

Two keys, both needed: `app_preview` in the build and `[preview]` in the project's declaration, read from the main
branch on the server. It runs what was saved, from a copy outside the workspace, only if the audit allows that copy
and it has a `uv.lock`. Every step runs through uv with `--frozen`, never through a shell, in an environment built
from a short list. The application listens on 127.0.0.1 only, and it stops, its whole process tree with it, when asked
to, when a newer version replaces it, and after a time limit. The temporary folder goes with it.

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
_PYTHON_VERSION = re.compile(r"3\.\d+(\.\d+)?")
_LOOPBACK = {"0100007F", "00000000000000000000000001000000", "0000000000000000FFFF00000100007F"}

# What uv and the operating system need. Everything else stays out: the person's tokens, the connector's settings
# (EUNOMAI_*), uv's and pip's own (a variable can name another index), and whatever else the computer has.
_SYSTEM = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "OS", "NUMBER_OF_PROCESSORS",
           "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
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
    """Files stay locked for a moment after a process ends on Windows."""
    deadline = time.time() + wait
    while True:
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists() or time.time() > deadline:
            return not folder.exists()
        time.sleep(0.1)


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


def _found(workspace: str) -> dict:
    """The preview of a workspace, if its watcher lives."""
    path = _state_file(workspace)
    return _read_state(path) if _watching(path) else {}


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


def _end(path: Path) -> bool:
    """Ask a live watcher to end its preview, from any connector. True only when it did, and its folder is gone."""
    folder = _read_state(path).get("folder")
    path.with_suffix(".stop").touch()
    deadline = time.time() + _END_WAIT
    while _watching(path) and time.time() < deadline:
        time.sleep(0.05)
    if _watching(path):
        return False
    path.with_suffix(".stop").unlink(missing_ok=True)
    if path.exists():  # it could not remove the folder: this connector tries
        _clear(path)
    return not path.exists() and not (folder and Path(folder).exists())


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
            _clear(state_path)
    for note in folder.glob("*.ended") if folder.is_dir() else ():
        if time.time() - note.stat().st_mtime > _STALE:
            note.unlink(missing_ok=True)
    for left in Path(tempfile.gettempdir()).glob(f"{_PREFIX}*"):  # started by a connector that died at that moment
        if str(left) not in named and time.time() - left.stat().st_mtime > _STALE:
            _remove(left, wait=0.0)


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
    def __init__(self, workspace: str, head: str, main: str | None = None, note: str = ""):
        self.workspace, self.key, self.head, self.main, self.note = workspace, _key(workspace), head, main, note
        self.token = secrets.token_hex(16)
        self.folder = Path(tempfile.mkdtemp(prefix=_PREFIX))
        self.app, self.home, self.temp = self.folder / "app", self.folder / "home", self.folder / "temp"
        self.environment_folder, self.log = self.folder / "environment", self.folder / "preview.log"
        for folder in (self.app, self.home, self.temp):
            folder.mkdir()
        (self.folder / "live").write_text(self.token, encoding="utf-8")
        self.url, self.outcome, self.delivered, self.closed, self.handed_over = "", None, False, False, False
        self.uv_cache, self.uv_pythons, self.python, self.keeps_running = "", "", (), False
        self.settled, self.ended = threading.Event(), threading.Event()
        self._closing, self._asking = threading.Lock(), threading.Lock()
        self.pipe = self._start_watcher()
        try:
            answer = self.ask({"folder": str(self.folder), "state": str(_state_file(workspace)), "token": self.token,
                               "workspace": workspace, "head": head, "limit": TIME_LIMIT, "log": str(self.log)})
        except _Gone:
            answer = {}
        if "watching" not in answer:
            self.pipe.stdin.close()
            _remove(self.folder)
            raise _Taken()
        self.keeps_running = answer["keeps_running"]

    def _start_watcher(self) -> subprocess.Popen:
        """Out of any job that lets it go, by the real interpreter, not a virtual environment's launcher. Its first
        process ends at once, so what stays has no parent to be found by; a job that refuses is respected: the preview
        works, ends with the host, and the person is told."""
        state = _state_file(self.workspace)
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
        self.ask({"do": "ready", "url": self.url})
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
                      "HOME": str(self.home), "USERPROFILE": str(self.home), "APPDATA": str(self.home),
                      "LOCALAPPDATA": str(self.home), "TEMP": str(self.temp), "TMP": str(self.temp),
                      "TMPDIR": str(self.temp)})
        if installing:
            built.update({key: os.environ[key] for key in _PROXY if key in os.environ})
        return {**built, **(extra or {})}

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
        path = _state_file(self.workspace)
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
        removed = _remove(self.folder)
        if _previews.get(self.key) is self:
            del _previews[self.key]
        self.ended.set()
        return removed


_lock = threading.Lock()
_previews: dict[str, _Preview] = {}  # the ones this connector is preparing, until the answer has been given
_unread: dict[str, _Preview] = {}  # one that ended without becoming ready, until a call has told why


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


def _console_scripts(environment: Path) -> set[str]:
    """The programs the installed packages declare, which is what the lock installed and nothing else on the computer."""
    found = set()
    for points in environment.rglob("*.dist-info/entry_points.txt"):
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
    current.step(uv, [*_INSTALL, *current.python], current.environment(uv, installing=True), "installing")
    _check_programs(current, declared)
    environment = current.environment(uv, declared["environment"])
    for entry in declared["setup"]:
        current.step(uv, [*_RUN, *current.python, *entry], environment, f"setup: {' '.join(entry)}")
    port = _free_port()
    arguments = [word.replace("{port}", str(port)) for word in declared["run"]]
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
    current.url = f"http://127.0.0.1:{port}/"
    current.hand_over()
    webbrowser.open(current.url)


def _how_long(minutes: int, keeps_running: bool) -> str:
    if keeps_running:
        return (f"It keeps running until you say stop, or for {minutes} more minutes at most, even if you close "
                "Claude.")
    return f"It stops when this task ends, or in {minutes} minutes."


def _prepare(current: _Preview, declared: dict) -> dict:
    """The saved version in the temporary folder, checked, and running. Refusals come back as answers."""
    saved = gitops.export_saved(current.workspace, current.app, current.main, current.head)
    try:
        audit = gitops.audit_saved(current.workspace, current.main, current.head, current.app)
    except support.Unreachable as exc:
        return support.audit_unavailable(
            current.workspace, "The application cannot be shown now: the checks on what it uses could not run. Check "
                               "the network or VPN and try again; your work is safe on this computer.", exc)
    if audit["verdict"] != "allowed":
        return deps.refusal(current.workspace, audit, "This version cannot be shown on your computer")
    if not (current.app / "uv.lock").is_file():
        return {"workspace": current.workspace, "status": "no_lockfile",
                "user_message": "This version cannot be shown on your computer yet: the list of exactly what it uses "
                                "has not been made. Your work is safe on this computer."}
    _bring_up(current, declared)
    minutes = math.ceil(TIME_LIMIT / 60)
    return {"workspace": current.workspace, "status": "ready", "url": current.url, "version": current.head[:12],
            "branch": saved["branch"], "unsaved_changes": saved["unsaved_changes"], "minutes": minutes,
            "keeps_running": current.keeps_running, "already_running": False,
            "user_message": f"The application is open in your browser, at {current.url}. It shows what was last saved, "
                            f"only on this computer. {_how_long(minutes, current.keeps_running)}"}


def _prepared(current: _Preview, declared: dict) -> dict:
    try:
        return _prepare(current, declared)
    except _Gone:
        return {"workspace": current.workspace, "status": "not_running",
                "user_message": "The application was stopped before it was ready."}


def _work(current: _Preview, declared: dict) -> None:
    current.outcome = support.safe(_prepared, current, declared)
    if current.outcome.get("status") != "ready":
        if not current.closed:  # a preview stopped or replaced has nothing left to tell
            _unread[current.key] = current
        current.close()
        _remove(current.folder, wait=2.0)  # a step still writing when it was stopped
    current.settled.set()


_ENDED_BY_ITSELF = {"application": "It had stopped by itself, so it is being started again.",
                    "time_limit": "It had reached its time limit, so it is being started again."}


def _with_note(answer: dict, note: str) -> dict:
    words = _ENDED_BY_ITSELF.get(note)
    if not words or answer.get("status") not in ("ready", "starting"):
        return answer
    return {**answer, "ended_before": note, "user_message": f"{words} {answer['user_message']}"}


def _answer(current: _Preview) -> dict:
    if not current.settled.is_set():
        return _with_note({"workspace": current.workspace, "status": "starting", "user_message":
                           "The application is being prepared; the first time can take a couple of minutes."},
                          current.note)
    current.delivered = True
    if _unread.get(current.key) is current:
        del _unread[current.key]
    if _previews.get(current.key) is current and current.outcome.get("status") == "ready":
        del _previews[current.key]
    return _with_note(current.outcome, current.note)


def _running(workspace: str, state: dict) -> dict:
    """The preview that is there, from any connector: its address and the time it has left, and no second copy."""
    left = float(state.get("deadline") or 0) - time.time()
    minutes, keeps_running = max(1, math.ceil(left / 60)), state.get("keeps_running") is True
    url = str(state.get("url") or "")
    webbrowser.open(url)
    saved = gitops.saved_summary(workspace)
    return {"workspace": workspace, "status": "ready", "url": url, "version": str(state.get("head") or "")[:12],
            "branch": saved["branch"], "unsaved_changes": saved["unsaved_changes"], "minutes": minutes,
            "keeps_running": keeps_running, "already_running": True,
            "user_message": f"The application is already running, at {url}, and is open in your browser. "
                            f"{_how_long(minutes, keeps_running)}"}


def _NOT_STOPPED(workspace: str) -> dict:
    return {"workspace": workspace, "status": "not_stopped",
            "user_message": "The application could not be stopped from here. It stops by itself within the hour."}


def _starting(workspace: str) -> dict:
    return {"workspace": workspace, "status": "starting",
            "user_message": "The application is being prepared; the first time can take a couple of minutes."}


def start(workspace: str) -> dict:
    """See the application on this computer. Call it again while the answer is `starting`."""
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
        if current is not None and current is not ended and (current.head != head or current.closed):
            current.close()
            current = None
        if current is None:
            state = _found(workspace)
            if state and state.get("head") == head:
                return _running(workspace, state) if state.get("phase") == "ready" else _starting(workspace)
            if state and not _end(_state_file(workspace)):  # another saved version, whoever started it
                return _NOT_STOPPED(workspace)
            _sweep()
            try:
                current = _previews[key] = _Preview(workspace, head, files.get("tip"), _take_note(workspace))
            except _Taken:
                return _starting(workspace)
            threading.Thread(target=_work, args=(current, declared), daemon=True).start()
    current.settled.wait(_ANSWER_WAIT)
    return _answer(current)


_NOT_RUNNING = "The application is not running on your computer."
_STOPPED = "The application has stopped on your computer, and its temporary copy is gone."


def stop(workspace: str) -> dict:
    """Stop the preview of a workspace, whichever connector started it. `stopped` only if something was running and
    now is not."""
    path = _state_file(workspace)
    with _lock:
        current, was_preparing = _previews.get(_key(workspace)), False
        if current is not None:
            was_preparing = not current.handed_over
            current.close()
        if _watching(path):
            if not _end(path):
                return _NOT_STOPPED(workspace)
            was_running = True
        else:
            was_running = path.exists() and _clear(path)
    if was_running or was_preparing:
        return {"workspace": workspace, "status": "stopped", "user_message": _STOPPED}
    return {"workspace": workspace, "status": "not_running", "user_message": _NOT_RUNNING}
