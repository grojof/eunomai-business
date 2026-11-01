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
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

from . import data_dir, deps, gitops, settings, support
from .support import NeedsIT

TIME_LIMIT = 60 * 60  # seconds a preview runs, once it answers
_ANSWER_WAIT = 40.0  # seconds a tool call waits; after that it answers `starting`, as a client may give up on it
_READY_WAIT = 120.0  # seconds the application has to answer
_STEP_LIMIT = 600.0  # seconds for the installation and for each setup step
_PREFIX = "eunomai-preview-"
_LAST_LINES = 15

# What uv and the operating system need. Everything else stays out: the person's tokens, the connector's settings
# (EUNOMAI_*), uv's and pip's own (a variable can name another index), and whatever else the computer has.
_SYSTEM = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "OS", "NUMBER_OF_PROCESSORS",
           "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
# Only for installing, never for what the project runs: a proxy's address can hold a password.
_PROXY = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")
_INSTALL = ("sync", "--frozen", "--no-dev", "--no-install-project", "--no-build", "--no-config", "--system-certs",
            "--managed-python")
_RUN = ("run", "--frozen", "--no-sync", "--no-dev", "--no-config", "--managed-python")
_HIDDEN = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console window flashes on the screen

# It outlives a connector that is killed: when its input ends without "done", it stops the group (where there is no
# job object to do it) and removes the folder.
_WATCHER = """
import os, shutil, signal, sys, time
folder, group = sys.argv[1], 0
for line in sys.stdin:
    if line.strip() == "done":
        sys.exit(0)
    group = int(line)
if group:
    try:
        os.killpg(group, signal.SIGKILL)
    except OSError:
        pass
for _ in range(240):
    shutil.rmtree(folder, ignore_errors=True)
    if not os.path.exists(folder):
        break
    time.sleep(0.5)
"""

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    _kernel32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
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
    _CAN_TERMINATE, _CREATE_SUSPENDED, _NO_WINDOW = 0x0008, 0x00000004, 0x08000000
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


def _end_named(job: str, group: int) -> None:
    """Stop a preview by what its state file says: another connector may hold it."""
    if sys.platform == "win32":
        handle = _kernel32.OpenJobObjectW(_CAN_TERMINATE, False, job) if job else None
        if handle:
            _kernel32.TerminateJobObject(handle, 1)
            _kernel32.CloseHandle(handle)
    elif group:
        try:
            os.killpg(group, 9)
        except OSError:
            pass


class _Tree:
    """Everything a preview starts, stopped together and unable to outlive the connector. On Windows a job object:
    processes start suspended, so none has a child before it is in the job, cannot leave it, and die when its last
    handle closes, however the connector ends. Elsewhere a process group, which the watcher stops; a program that
    starts a session of its own leaves it, a limit Windows does not have."""

    def __init__(self, name: str):
        self.name, self.group, self.handle, self._ended = name, 0, None, False
        self._lock = threading.Lock()
        if sys.platform == "win32":
            self.handle = _kernel32.CreateJobObjectW(None, name)
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
                self.group = process.pid
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
        if not self.group:
            return 0
        try:
            os.killpg(self.group, 0)
        except ProcessLookupError:
            return 0
        except PermissionError:
            pass
        return 1

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
            elif self.group:
                try:
                    os.killpg(self.group, 9)
                except OSError:
                    pass

    def close(self) -> None:
        deadline = time.time() + 10
        while self.running() and time.time() < deadline:
            time.sleep(0.05)
        if sys.platform == "win32":
            with self._lock:
                if self.handle is not None:
                    _kernel32.CloseHandle(self.handle)
                    self.handle = None


def _state_file(workspace: str) -> Path:
    """What is needed to stop a preview from another connector, in the connector's own folder, which the sandbox
    cannot reach."""
    return data_dir() / "previews" / (hashlib.sha256(workspace.encode()).hexdigest()[:16] + ".json")


def _remove(folder: Path, wait: float = 10.0) -> bool:
    """Files stay locked for a moment after a process ends on Windows."""
    deadline = time.time() + wait
    while True:
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists() or time.time() > deadline:
            return not folder.exists()
        time.sleep(0.1)


def _clear(state_path: Path) -> None:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state_path.unlink(missing_ok=True)
        return
    _end_named(str(state.get("job") or ""), int(state.get("group") or 0))
    folder = Path(str(state.get("folder") or ""))
    if folder.name.startswith(_PREFIX):  # only ever a preview's own folder
        _remove(folder)
    state_path.unlink(missing_ok=True)


def _clear_left_over(workspace: str) -> None:
    """A preview of this workspace another connector holds: one per workspace, across tasks."""
    if workspace not in _previews and _state_file(workspace).exists():
        _clear(_state_file(workspace))


def _sweep() -> None:
    """What connectors that died left behind, should their watcher have died too."""
    folder = data_dir() / "previews"
    for state_path in folder.glob("*.json") if folder.is_dir() else ():
        try:
            owner = int(json.loads(state_path.read_text(encoding="utf-8")).get("owner") or 0)
        except (OSError, ValueError):
            owner = 0
        if not owner or not _alive(owner):
            _clear(state_path)


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
    def __init__(self, workspace: str, head: str):
        self.workspace, self.head = workspace, head
        self.folder = Path(tempfile.mkdtemp(prefix=_PREFIX))
        self.app, self.home, self.temp = self.folder / "app", self.folder / "home", self.folder / "temp"
        self.environment_folder, self.log = self.folder / "environment", self.folder / "preview.log"
        for folder in (self.app, self.home, self.temp):
            folder.mkdir()
        self.tree = _Tree(f"Local\\{self.folder.name}")
        self.process, self.url, self.outcome, self.delivered, self.closed = None, "", None, False, False
        self.uv_cache, self.uv_pythons = "", ""
        self.settled, self.ended = threading.Event(), threading.Event()
        self._closing = threading.Lock()
        self.watcher = subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", _WATCHER, str(self.folder)], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=tempfile.gettempdir(), text=True,
            env={key: os.environ[key] for key in ("SYSTEMROOT", "PATH") if key in os.environ},
            **(_HIDDEN or {"start_new_session": True}))
        self._remember()

    def _remember(self) -> None:
        state = {"workspace": self.workspace, "folder": str(self.folder), "owner": os.getpid(),
                 "job": self.tree.name, "group": self.tree.group}
        path = _state_file(self.workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")

    def _tell_watcher(self, line: str) -> None:
        try:
            self.watcher.stdin.write(line + "\n")
            self.watcher.stdin.flush()
        except (OSError, ValueError):
            pass

    def environment(self, uv: str, extra: dict | None = None, installing: bool = False) -> dict:
        system = os.environ.get("SYSTEMROOT", "")
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
                                 "Last lines": self.last_lines()})

    def last_lines(self) -> str:
        try:
            with open(self.log, "rb") as log:
                log.seek(0, os.SEEK_END)
                log.seek(max(0, log.tell() - 4000))
                text = log.read().decode("utf-8", "replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-_LAST_LINES:])[-480:]

    def step(self, uv: str, arguments: list[str], environment: dict, name: str) -> None:
        with open(self.log, "ab") as log:
            process = self.tree.start([uv, *arguments], self.app, environment, log)
        self._tell_watcher(str(self.tree.group))
        try:
            code = process.wait(timeout=_STEP_LIMIT)
        except subprocess.TimeoutExpired:
            self.tree.kill()
            raise self.failed(name, "a preview step ran out of time") from None
        if code:
            raise self.failed(name)

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
        if _previews.get(self.workspace) is self:
            del _previews[self.workspace]
        try:  # another connector may have taken the workspace over
            if json.loads(_state_file(self.workspace).read_text(encoding="utf-8")).get("owner") == os.getpid():
                _state_file(self.workspace).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


_lock = threading.Lock()
_previews: dict[str, _Preview] = {}
_unread: dict[str, _Preview] = {}  # one that ended without becoming ready, until a call has told why


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _answers(port: int) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/")
        connection.getresponse()
        return True
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def _listens_beyond_this_computer(current: _Preview, port: int) -> bool:
    """A last look at what the application did with the address it was told to use, once, as it starts. On Windows the
    system says what the tree listens on, on any port: a firewall silently drops a connection to the computer's own
    address, so trying one proves nothing. Elsewhere, that attempt on the application's port is the look."""
    if sys.platform == "win32":
        netstat = f"{os.environ.get('SYSTEMROOT', 'C:/Windows')}/System32/netstat.exe"
        lines = [line for protocol in ("TCP", "TCPv6") for line in subprocess.run(
            [netstat, "-ano", "-p", protocol], capture_output=True, text=True, timeout=30, errors="replace",
            **_HIDDEN).stdout.splitlines()]
        tree = current.tree.processes()
        for line in lines:
            words = line.split()  # the state in the middle is in the computer's language; a listener has no remote port
            if len(words) == 5 and words[0].startswith("TCP") and words[2].endswith(":0") and words[4].isdigit():
                address, _, listening = words[1].rpartition(":")
                if (int(words[4]) in tree or listening == str(port)) and address not in ("127.0.0.1", "[::1]"):
                    return True
        return False
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return False
    for address in addresses:
        if not address.startswith("127."):
            with socket.socket() as probe:
                probe.settimeout(0.5)
                if probe.connect_ex((address, port)) == 0:
                    return True
    return False


def _bring_up(current: _Preview, declared: dict) -> None:
    """Install, run the setup steps and start the application, until it answers. Stops with NeedsIT."""
    uv = _uv()
    current.uv_cache, current.uv_pythons = _uv_folder(uv, "cache", "dir"), _uv_folder(uv, "python", "dir")
    current.step(uv, list(_INSTALL), current.environment(uv, installing=True), "installing")
    environment = current.environment(uv, declared["environment"])
    for entry in declared["setup"]:
        current.step(uv, [*_RUN, *entry], environment, f"setup: {' '.join(entry)}")
    port = _free_port()
    arguments = [word.replace("{port}", str(port)) for word in declared["run"]]
    with open(current.log, "ab") as log:
        current.process = current.tree.start([uv, *_RUN, *arguments], current.app, environment, log)
    current._tell_watcher(str(current.tree.group))
    deadline = time.time() + _READY_WAIT
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
    saved = gitops.export_saved(current.workspace, current.app, current.head)
    try:
        audit = gitops.audit_saved(current.workspace, current.head, current.app)
    except support.Unreachable:
        return {"workspace": current.workspace, "status": "audit_unavailable",
                "user_message": "The application cannot be shown now: the checks on what it uses could not run. Check "
                                "the network or VPN and try again; your work is safe on this computer."}
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
        _unread[current.workspace] = current
        current.close()
    current.settled.set()
    if ready:
        try:
            current.process.wait(timeout=TIME_LIMIT)
        except subprocess.TimeoutExpired:
            pass
        current.close()


def _answer(current: _Preview) -> dict:
    if not current.settled.is_set():
        return {"workspace": current.workspace, "status": "starting",
                "user_message": "The application is being prepared; the first time can take a couple of minutes."}
    if current.outcome.get("status") == "ready" and current.delivered:
        webbrowser.open(current.url)
    current.delivered = True
    if _unread.get(current.workspace) is current:
        del _unread[current.workspace]
    return current.outcome


def start(workspace: str) -> dict:
    """See the application on this computer. Call it again while the answer is `starting`."""
    if not settings.load()["app_preview"]:
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
    with _lock:
        ended = _unread.get(workspace)
        if ended is not None and ended.head != head:  # nobody waits for what an older version did
            del _unread[workspace]
            ended = None
        current = ended or _previews.get(workspace)
        if current is not None and current is not ended and (current.head != head or current.closed):
            current.close()
            current = None
        if current is None:
            _clear_left_over(workspace)
            _sweep()
            current = _previews[workspace] = _Preview(workspace, head)
            threading.Thread(target=_work, args=(current, declared), daemon=True).start()
    current.settled.wait(_ANSWER_WAIT)
    return _answer(current)


def stop(workspace: str) -> dict:
    """Stop the preview of a workspace, whichever connector holds it."""
    with _lock:
        current = _previews.get(workspace)
        running = current is not None or _state_file(workspace).exists()
        _clear_left_over(workspace)
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
