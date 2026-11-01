"""The real application on the person's computer, through the connector, when IT turned it on (decision 7).

This runs code an AI wrote and nobody has reviewed yet, on the person's computer, with their rights, outside any
sandbox. Everything here reduces that risk; nothing here removes it, and a program with those rights can undo most
of it (docs/barriers.md says what is left).

Two keys, both needed: `app_preview` in the build and `[preview]` in the project's declaration, read from the main
branch on the server. It runs what was saved, from a copy outside the workspace, only if the audit allows that copy
and it has a `uv.lock`. Every step runs through uv with `--frozen`, never through a shell, in an environment built
from a short list. The application listens on 127.0.0.1 only, and it stops, its whole process tree with it, when asked
to, when the connector ends, and after a time limit. The temporary folder goes with it.
"""

import atexit
import hashlib
import json
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

from . import data_dir, deps, gitops, settings, support
from .support import NeedsIT

TIME_LIMIT = 60 * 60  # seconds a preview runs, once it answers
_ANSWER_WAIT = 40.0  # seconds a tool call waits; after that it answers `starting`, as a client may give up on it
_READY_WAIT = 120.0  # seconds the application has to answer
_STEP_LIMIT = 600.0  # seconds for the installation and for each setup step
_PREFIX = "eunomai-preview-"
_LAST_LINES = 15
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

# It outlives a connector that is killed, and answers another connector that asks for the workspace: when its input
# ends without "done", or a stop file appears, it ends the job or every group, removes the folder, and removes the state
# file if it is still its own. It holds a handle of the job, so that ending it never depends on the job's name.
_WATCHER = """
import json, os, shutil, signal, sys, threading, time
folder, state, stop, token, job = sys.argv[1:6]
groups, finished, abandoned = set(), threading.Event(), threading.Event()


def listen():
    for line in sys.stdin:
        line = line.strip()
        if line == "done":
            finished.set()
            return
        if line.isdigit():
            groups.add(int(line))
    abandoned.set()


threading.Thread(target=listen, daemon=True).start()
while not finished.is_set() and not abandoned.is_set() and not os.path.exists(stop):
    time.sleep(0.2)
if finished.is_set():
    sys.exit(0)
if int(job):
    import ctypes
    ctypes.windll.kernel32.TerminateJobObject(ctypes.c_void_p(int(job)), 1)
for group in groups:
    try:
        os.killpg(group, signal.SIGKILL)
    except OSError:
        pass
for _ in range(240):
    shutil.rmtree(folder, ignore_errors=True)
    if not os.path.exists(folder):
        break
    time.sleep(0.5)
try:
    with open(state, encoding="utf-8") as file:
        mine = json.load(file).get("token") == token
    if mine:
        os.remove(state)
except (OSError, ValueError, AttributeError):
    pass
"""

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                                    wintypes.LPVOID]
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _KILL_ON_CLOSE, _EXTENDED_LIMITS, _ACCOUNTING, _PROCESS_LIST = 0x2000, 9, 1, 3
    _CREATE_SUSPENDED, _NO_WINDOW = 0x00000004, 0x08000000
    _SYNCHRONIZE, _WAIT_TIMEOUT = 0x00100000, 0x102

    class _BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", wintypes.DWORD),
                    ("minimum_set", ctypes.c_size_t), ("maximum_set", ctypes.c_size_t),
                    ("processes", wintypes.DWORD), ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class _Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("reads", "writes", "others", "read", "written", "other")]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", _BasicLimits), ("counters", _Counters), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

    class _Accounting(ctypes.Structure):
        _fields_ = [("user", ctypes.c_int64), ("kernel", ctypes.c_int64), ("period_user", ctypes.c_int64),
                    ("period_kernel", ctypes.c_int64), ("faults", wintypes.DWORD), ("total", wintypes.DWORD),
                    ("active", wintypes.DWORD), ("terminated", wintypes.DWORD)]

    class _ProcessList(ctypes.Structure):
        _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD), ("ids", ctypes.c_size_t * 512)]


def _alive(pid: int) -> bool:
    """Whether a process is still running."""
    if sys.platform == "win32":
        handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            return _kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _end_groups(groups: list[int]) -> None:
    for group in groups if sys.platform != "win32" else ():
        try:
            os.killpg(group, 9)
        except OSError:
            pass


class _Tree:
    """Everything a preview starts, stopped together and unable to outlive the connector. On Windows a job object
    with no name, so nothing in it can open it and keep it alive: processes start suspended, so none has a child before
    it is in the job, cannot leave it, and die when its last handle closes, however the connector ends. Elsewhere a
    process group per step, every one of them kept, which the watcher stops; a program that starts a session of its
    own leaves it, a limit Windows does not have."""

    def __init__(self):
        self.groups, self.handle, self._ended = set(), None, False
        self._lock = threading.Lock()
        if sys.platform == "win32":
            self.handle = _kernel32.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = _ExtendedLimits()
            limits.basic.flags = _KILL_ON_CLOSE
            if not _kernel32.SetInformationJobObject(self.handle, _EXTENDED_LIMITS, ctypes.byref(limits),
                                                     ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())

    def start(self, arguments: list[str], folder: Path, environment: dict, log) -> subprocess.Popen:
        options = {"cwd": folder, "env": environment, "stdin": subprocess.DEVNULL, "stdout": log,
                   "stderr": subprocess.STDOUT, "close_fds": True}
        with self._lock:
            if self._ended:
                raise PermissionError("the preview was stopped")
            if sys.platform != "win32":
                process = subprocess.Popen(arguments, start_new_session=True, **options)
                self.groups = {group for group in self.groups if self._group_lives(group)} | {process.pid}
                return process
            process = subprocess.Popen(arguments, creationflags=_CREATE_SUSPENDED | _NO_WINDOW, **options)
            if not _kernel32.AssignProcessToJobObject(self.handle, int(process._handle)):
                error = ctypes.WinError(ctypes.get_last_error())
                process.kill()
                raise error
            _ntdll.NtResumeProcess(int(process._handle))
            return process

    def running(self) -> int:
        """Processes still in the tree."""
        if sys.platform == "win32":
            if self.handle is None:
                return 0
            info = _Accounting()
            _kernel32.QueryInformationJobObject(self.handle, _ACCOUNTING, ctypes.byref(info), ctypes.sizeof(info), None)
            return info.active
        return sum(self._group_lives(group) for group in self.groups)

    @staticmethod
    def _group_lives(group: int) -> bool:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return True

    def processes(self) -> set[int]:
        """The processes in the tree, where the system can tell."""
        if sys.platform != "win32" or self.handle is None:
            return set()
        found = _ProcessList()
        _kernel32.QueryInformationJobObject(self.handle, _PROCESS_LIST, ctypes.byref(found), ctypes.sizeof(found), None)
        return set(found.ids[:found.listed])

    def kill(self) -> None:
        with self._lock:
            self._ended = True
            if sys.platform == "win32":
                if self.handle is not None:
                    _kernel32.TerminateJobObject(self.handle, 1)
            else:
                _end_groups(sorted(self.groups))

    def close(self) -> None:
        deadline = time.time() + 10
        while self.running() and time.time() < deadline:
            time.sleep(0.05)
        if sys.platform == "win32":
            with self._lock:
                if self.handle is not None:
                    _kernel32.CloseHandle(self.handle)
                    self.handle = None


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


def _clear(state_path: Path) -> None:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        folder, token = Path(str(state["folder"])), str(state.get("token") or "")
        groups = [int(group) for group in state.get("groups") or []]
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        state_path.unlink(missing_ok=True)
        return
    if folder.name.startswith(_PREFIX):  # only ever a preview's own folder
        if _is_live(folder, token):
            _end_groups(groups)
        _remove(folder)
    state_path.unlink(missing_ok=True)


def _clear_left_over(workspace: str) -> bool:
    """A preview of this workspace another connector holds, one per workspace across tasks: its watcher is asked to end
    it. Without a watcher, what the state file says is all there is, and on Windows that is nothing: only its connector
    holds the job then. False when it may still be running."""
    path = _state_file(workspace)
    if _key(workspace) in _previews or not path.exists():
        return True
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        watcher, owner = int(state.get("watcher") or 0), int(state.get("owner") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        watcher, owner = 0, 0
    if watcher and _alive(watcher):
        stop_file = path.with_suffix(".stop")
        stop_file.touch()
        deadline = time.time() + 20
        while path.exists() and time.time() < deadline:
            time.sleep(0.1)
        stop_file.unlink(missing_ok=True)
    if path.exists() and sys.platform == "win32" and owner and _alive(owner):
        return False
    if path.exists():
        _clear(path)
    return True


def _sweep() -> None:
    """What connectors that died left behind, should their watcher have died too."""
    folder = data_dir() / "previews"
    for state_path in folder.glob("*.json") if folder.is_dir() else ():
        try:
            owner = int(json.loads(state_path.read_text(encoding="utf-8")).get("owner") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            owner = 0
        if not owner or not _alive(owner):
            _clear(state_path)


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
    def __init__(self, workspace: str, head: str, main: str | None = None):
        self.workspace, self.key, self.head, self.main = workspace, _key(workspace), head, main
        self.token = secrets.token_hex(16)
        self.folder = Path(tempfile.mkdtemp(prefix=_PREFIX))
        self.app, self.home, self.temp = self.folder / "app", self.folder / "home", self.folder / "temp"
        self.environment_folder, self.log = self.folder / "environment", self.folder / "preview.log"
        for folder in (self.app, self.home, self.temp):
            folder.mkdir()
        (self.folder / "live").write_text(self.token, encoding="utf-8")
        self.tree = _Tree()
        self.process, self.url, self.outcome, self.delivered, self.closed = None, "", None, False, False
        self.uv_cache, self.uv_pythons, self.began, self.python = "", "", time.time(), ()
        self.settled, self.ended = threading.Event(), threading.Event()
        self._closing = threading.Lock()
        self.watcher = self._start_watcher()
        self._remember()

    def _start_watcher(self) -> subprocess.Popen:
        """The real interpreter, not a virtual environment's launcher, which would stand between it and what it holds."""
        state, job, options = _state_file(self.workspace), int(self.tree.handle or 0), {}
        state.parent.mkdir(parents=True, exist_ok=True)
        state.with_suffix(".stop").unlink(missing_ok=True)  # left by a connector that died waiting
        if job:
            os.set_handle_inheritable(job, True)
            options["startupinfo"] = subprocess.STARTUPINFO(lpAttributeList={"handle_list": [job]})
        try:
            return subprocess.Popen(
                [getattr(sys, "_base_executable", sys.executable), "-I", "-S", "-c", _WATCHER, str(self.folder), str(state),
                 str(state.with_suffix(".stop")), self.token, str(job)], stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=tempfile.gettempdir(), text=True,
                env={key: os.environ[key] for key in ("SYSTEMROOT", "PATH") if key in os.environ},
                **options, **(_HIDDEN or {"start_new_session": True}))
        finally:
            if job:
                os.set_handle_inheritable(job, False)

    def _remember(self) -> None:
        state = {"workspace": self.workspace, "folder": str(self.folder), "owner": os.getpid(), "token": self.token,
                 "groups": sorted(self.tree.groups), "watcher": self.watcher.pid}
        path = _state_file(self.workspace)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, path)  # another connector's sweep never reads half of it

    def _tell_watcher(self, line: str) -> None:
        try:
            self.watcher.stdin.write(line + "\n")
            self.watcher.stdin.flush()
        except (OSError, ValueError):
            pass

    def started(self) -> None:
        """A step began: where there are process groups, each has its own, for the watcher and other connectors."""
        for group in self.tree.groups:
            self._tell_watcher(str(group))
        self._remember()

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

    def step(self, uv: str, arguments: list[str], environment: dict, name: str) -> None:
        with open(self.log, "ab") as log:
            process = self.tree.start([uv, *arguments], self.app, environment, log)
        self.started()
        try:
            code = process.wait(timeout=_STEP_LIMIT)
        except subprocess.TimeoutExpired:
            self.tree.kill()
            raise self.failed(name, "a preview step ran out of time") from None
        if code:
            raise self.not_installed() if name == "installing" else self.failed(name)

    def close(self) -> bool:
        """Stop everything and remove the folder. Safe to call from anywhere, any number of times."""
        with self._closing:
            if self.closed:
                return not self.folder.exists()
            self.closed = True
        self.tree.kill()
        self.tree.close()
        removed = _remove(self.folder)
        self._forget()
        self._tell_watcher("done")
        try:
            self.watcher.stdin.close()
            self.watcher.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.ended.set()
        return removed

    def _forget(self) -> None:
        if _previews.get(self.key) is self:
            del _previews[self.key]
        try:  # another connector may have taken the workspace over
            if json.loads(_state_file(self.workspace).read_text(encoding="utf-8")).get("token") == self.token:
                _state_file(self.workspace).unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass


_lock = threading.Lock()
_previews: dict[str, _Preview] = {}
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
        return _windows_beyond(lines, port, current.tree.processes())
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
    current.began = time.time()
    with open(current.log, "ab") as log:
        current.process = current.tree.start([uv, *_RUN, *current.python, *arguments], current.app, environment, log)
    current.started()
    deadline = current.began + min(_READY_WAIT, TIME_LIMIT)
    while not _answers(port):
        if current.process.poll() is not None or current.closed:
            raise current.failed("run: the application ended before it answered")
        if time.time() > deadline:
            raise current.failed("run: the application did not answer in time")
        time.sleep(0.2)
    if _listens_beyond_this_computer(current, port):
        raise current.failed("run", "the application answers beyond this computer")
    current.url = f"http://127.0.0.1:{port}/"
    webbrowser.open(current.url)


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
    minutes = round(TIME_LIMIT / 60)
    return {"workspace": current.workspace, "status": "ready", "url": current.url, "version": current.head[:12],
            "branch": saved["branch"], "unsaved_changes": saved["unsaved_changes"], "minutes": minutes,
            "user_message": f"The application is open in your browser, at {current.url}. It shows what was last saved, "
                            f"only on this computer, and it stops by itself in {minutes} minutes."}


def _work(current: _Preview, declared: dict) -> None:
    current.outcome = support.safe(_prepare, current, declared)
    ready = current.outcome.get("status") == "ready"
    if not ready:
        if not current.closed:  # a preview stopped or replaced has nothing left to tell
            _unread[current.key] = current
        current.close()
    current.settled.set()
    if ready:
        try:  # counted from when it started: being slow to answer earns no extra time
            current.process.wait(timeout=max(0.0, current.began + TIME_LIMIT - time.time()))
        except subprocess.TimeoutExpired:
            pass
        current.close()
    _remove(current.folder, wait=2.0)  # a step still writing when it was stopped


def _answer(current: _Preview) -> dict:
    if not current.settled.is_set():
        return {"workspace": current.workspace, "status": "starting",
                "user_message": "The application is being prepared; the first time can take a couple of minutes."}
    if current.outcome.get("status") == "ready" and current.delivered:
        webbrowser.open(current.url)
    current.delivered = True
    if _unread.get(current.key) is current:
        del _unread[current.key]
    return current.outcome


def _NOT_STOPPED(workspace: str) -> dict:
    return {"workspace": workspace, "status": "not_stopped",
            "user_message": "Another task started the application and it could not be stopped from here. It stops when "
                            "that task ends, and within the hour in any case."}


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
            if not _clear_left_over(workspace):
                return _NOT_STOPPED(workspace)
            _sweep()
            current = _previews[key] = _Preview(workspace, head, files.get("tip"))
            threading.Thread(target=_work, args=(current, declared), daemon=True).start()
    current.settled.wait(_ANSWER_WAIT)
    return _answer(current)


def stop(workspace: str) -> dict:
    """Stop the preview of a workspace, whichever connector holds it."""
    with _lock:
        current = _previews.get(_key(workspace))
        running = current is not None or _state_file(workspace).exists()
        cleared = _clear_left_over(workspace)
    if not cleared:
        return _NOT_STOPPED(workspace)
    if not running:
        return {"workspace": workspace, "status": "not_running",
                "user_message": "The application is not running on your computer."}
    if current is not None:
        current.close()
    return {"workspace": workspace, "status": "stopped",
            "user_message": "The application has stopped on your computer, and its temporary copy is gone."}


def stop_all() -> None:
    for current in list(_previews.values()):
        current.close()


atexit.register(stop_all)
