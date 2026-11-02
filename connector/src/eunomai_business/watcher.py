"""What owns a preview: one detached process, for as long as the preview lasts.

It starts every step of a preview, so nothing of it descends from the connector, which in Cowork lives one turn. It
ends the preview when told to, when the time limit passes, when the application ends by itself, and, until the
preview is ready, when the connector that asked for it is gone. It runs with the standard library alone, by path, on
the real interpreter (`python -I -S watcher.py`), so nothing of the plugin or the project is imported.

Two processes in turn: `launch` starts `watch` and ends, so that `watch` has no living parent for a tree kill to
follow. `launch` is what breaks out of a job a host holds the connector in, when that job allows it.

The connector speaks to it over its standard input and output, one JSON object a line, until the preview is ready.
After that, a connector knows it from the files it leaves beside the state file:

    <name>.json    the state, written whole. The application runs as the person and can rewrite it, so a connector
                   believes nothing in it that does not pass its reader, and it protects against the sandbox only
    <name>.alive   locked for as long as it lives: the system frees a lock when a process dies, however it dies, and
                   a number that came back as another process holds no lock
    <name>.stop    its presence asks it to end
    <name>.ended   why it ended by itself, for the next `app_preview` to tell
"""

import contextlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

WINDOWS = sys.platform == "win32"
BREAKAWAY, NO_WINDOW, DETACHED, NEW_GROUP, SUSPENDED = 0x01000000, 0x08000000, 0x00000008, 0x00000200, 0x00000004
REMOVE_TRIES = 240  # half seconds: files stay locked for a moment after a process ends on Windows
LAST_LINES = 15

if WINDOWS:
    import ctypes
    import msvcrt
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
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4]
    _kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _KILL_ON_CLOSE, _EXTENDED_LIMITS, _ACCOUNTING, _PROCESS_LIST = 0x2000, 9, 1, 3
    _LETS_GO = 0x0800 | 0x1000  # JOB_OBJECT_LIMIT_BREAKAWAY_OK, JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
    _CAN_TERMINATE, _CAN_LOOK = 0x0001, 0x1000

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", wintypes.DWORD),
                    ("minimum_set", ctypes.c_size_t), ("maximum_set", ctypes.c_size_t),
                    ("processes", wintypes.DWORD), ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("reads", "writes", "others", "read", "written", "other")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("counters", Counters), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

    class Accounting(ctypes.Structure):
        _fields_ = [("user", ctypes.c_int64), ("kernel", ctypes.c_int64), ("period_user", ctypes.c_int64),
                    ("period_kernel", ctypes.c_int64), ("faults", wintypes.DWORD), ("total", wintypes.DWORD),
                    ("active", wintypes.DWORD), ("terminated", wintypes.DWORD)]

    class ProcessList(ctypes.Structure):
        _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD), ("ids", ctypes.c_size_t * 512)]
else:
    import fcntl


def lock(file) -> bool:
    """Take the lock of an open file, without waiting."""
    try:
        if WINDOWS:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def unlock(file) -> None:
    try:
        if WINDOWS:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def normalized(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _handle_identity(handle) -> tuple:
    size, name = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
    times = [wintypes.FILETIME() for _ in range(4)]
    if not _kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)) or \
            not _kernel32.GetProcessTimes(handle, *[ctypes.byref(time_) for time_ in times]):
        return ()
    return normalized(name.value), (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def identity(pid: int) -> tuple:
    """What tells a process from one that later got its number: its program and when it started. Empty if unknown."""
    if WINDOWS:
        handle = _kernel32.OpenProcess(_CAN_LOOK, False, pid)
        if not handle:
            return ()
        try:
            return _handle_identity(handle)
        finally:
            _kernel32.CloseHandle(handle)
    try:
        started = open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace").read().rpartition(")")[2].split()[19]
        return normalized(os.readlink(f"/proc/{pid}/exe")), int(started)
    except (OSError, ValueError, IndexError):
        return ()


def end_process(pid: int, created: int, image: str) -> bool:
    """End a process only if it is the one meant. A watcher that no longer answers goes this way, and on Windows the
    job goes with it, as only the watcher holds it."""
    if WINDOWS:
        handle = _kernel32.OpenProcess(_CAN_TERMINATE | _CAN_LOOK, False, pid)
        if not handle:
            return False
        try:
            return _handle_identity(handle) == (image, created) and bool(_kernel32.TerminateProcess(handle, 1))
        finally:
            _kernel32.CloseHandle(handle)
    if identity(pid) != (image, created):
        return False
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return False
    return True


def replace_file(temporary: str, target: str) -> None:
    """On Windows a file someone is reading cannot be replaced, for as long as they read it."""
    try:
        for _ in range(30):
            try:
                os.replace(temporary, target)
                return
            except PermissionError:
                time.sleep(0.1)
        os.replace(temporary, target)
    finally:
        with contextlib.suppress(OSError):
            os.remove(temporary)


class Tree:
    """Everything a preview starts, stopped together. This stops an application that misbehaves, not one built to stay,
    which, running as the person, can leave anything behind. On Windows a job object with no name: processes start
    suspended, so none has a child before it is in the job, and they die when its last handle closes, this process
    being the only holder it gave one to. Elsewhere a process group per step, every one of them kept. Once ended, no
    more steps start."""

    def __init__(self):
        self.groups, self.handle, self.children, self.ended = set(), None, [], False
        self.starting = threading.Lock()
        if WINDOWS:
            self.handle = _kernel32.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = ExtendedLimits()
            limits.basic.flags = _KILL_ON_CLOSE
            if not _kernel32.SetInformationJobObject(self.handle, _EXTENDED_LIMITS, ctypes.byref(limits),
                                                     ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())

    def start(self, arguments: list, folder: str, environment: dict, log) -> subprocess.Popen:
        options = {"cwd": folder, "env": environment, "stdin": subprocess.DEVNULL, "stdout": log,
                   "stderr": subprocess.STDOUT, "close_fds": True}
        with self.starting:
            if self.ended:
                raise PermissionError("the preview was stopped")
            if not WINDOWS:
                process = subprocess.Popen(arguments, start_new_session=True, **options)
                self.groups = {group for group in self.groups if self._lives(group)} | {process.pid}
                self.children.append(process)
                return process
            process = subprocess.Popen(arguments, creationflags=SUSPENDED | NO_WINDOW, **options)
            if not _kernel32.AssignProcessToJobObject(self.handle, int(process._handle)):
                error = ctypes.WinError(ctypes.get_last_error())
                process.kill()
                raise error
            _ntdll.NtResumeProcess(int(process._handle))
            return process

    @staticmethod
    def _lives(group: int) -> bool:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return True

    def running(self) -> int:
        if WINDOWS:
            info = Accounting()
            _kernel32.QueryInformationJobObject(self.handle, _ACCOUNTING, ctypes.byref(info), ctypes.sizeof(info), None)
            return info.active
        for child in self.children:  # one of its own that ended counts as a group until it is collected
            child.poll()
        return sum(self._lives(group) for group in self.groups)

    def processes(self) -> list:
        if not WINDOWS:
            return []
        found = ProcessList()
        _kernel32.QueryInformationJobObject(self.handle, _PROCESS_LIST, ctypes.byref(found), ctypes.sizeof(found), None)
        return list(found.ids[:found.listed])

    def kill(self) -> None:
        with self.starting:
            self.ended = True
            if WINDOWS:
                _kernel32.TerminateJobObject(self.handle, 1)
            for group in self.groups:
                try:
                    os.killpg(group, signal.SIGKILL)
                except OSError:
                    pass


def detached() -> bool:
    """Whether this process got away from whatever could end it with its connector. A job remains possible: the system
    keeps programs in harmless ones that let everything leave and kill nothing, so what counts is what the job does."""
    if not WINDOWS:
        return True
    held = wintypes.BOOL()
    if not _kernel32.IsProcessInJob(_kernel32.GetCurrentProcess(), None, ctypes.byref(held)) or not held.value:
        return True
    limits = ExtendedLimits()
    if not _kernel32.QueryInformationJobObject(None, _EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits), None):
        return False
    return bool(limits.basic.flags & _LETS_GO) and not limits.basic.flags & _KILL_ON_CLOSE


class Watcher:
    def __init__(self, config: dict):
        self.folder, self.path, self.token = config["folder"], config["state"], config["token"]
        self.workspace, self.head, self.limit = config["workspace"], config["head"], config["limit"]
        self.declaration, self.keep = config["declaration"], config["keep"]
        self.tree, self.application, self.log = Tree(), None, config["log"]
        self.phase, self.port, self.began, self.deadline, self.steady_deadline = "preparing", 0, 0.0, 0.0, 0.0
        self.abandoned, self.handed_over, self.ending = threading.Event(), threading.Event(), threading.Event()
        self.asked = queue.Queue()
        self.stop_file, self.alive_file = self._beside(".stop"), self._beside(".alive")
        self.ended_file, self.kept_file = self._beside(".ended"), self._beside(".kept")
        self.alive = None

    def _beside(self, suffix: str) -> str:
        return os.path.splitext(self.path)[0] + suffix

    def hold(self) -> bool:
        """One preview a workspace, across connectors: whoever holds the lock has it."""
        self.alive = open(self.alive_file, "a+b")  # noqa: SIM115
        for _ in range(5):
            if lock(self.alive):
                return True
            time.sleep(0.1)
        return False

    def remember(self) -> None:
        image, created = identity(os.getpid()) or ("", None)
        state = {"workspace": self.workspace, "folder": self.folder, "token": self.token, "head": self.head,
                 "declaration": self.declaration, "phase": self.phase, "port": self.port, "began": self.began,
                 "deadline": self.deadline, "groups": sorted(self.tree.groups), "watcher": os.getpid(),
                 "image": image, "created": created, "keeps_running": detached()}
        temporary = f"{self.path}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(state, file)
        replace_file(temporary, self.path)  # another connector never reads half of it

    def reply(self, answer: dict) -> None:
        try:
            sys.stdout.buffer.write((json.dumps(answer) + "\n").encode())
            sys.stdout.buffer.flush()
        except (OSError, ValueError):
            pass

    def listen(self) -> None:
        """Until it is ready, the connector is what the preview is for: its end ends the preparation."""
        for line in sys.stdin.buffer:
            try:
                self.asked.put(json.loads(line))
            except ValueError:
                continue
        time.sleep(0.5)  # what it said last, as it ended, counts
        if not self.handed_over.is_set():
            self.abandoned.set()

    def serve(self) -> None:
        while not self.handed_over.is_set() and not self.ending.is_set():
            try:
                request = self.asked.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.reply(getattr(self, f"do_{request['do']}")(request))
            except (OSError, ValueError, KeyError) as exc:
                self.reply({"error": f"{type(exc).__name__}: {exc}"[:300]})

    def start(self, request: dict) -> subprocess.Popen:
        with open(request["log"], "ab") as log:
            process = self.tree.start(request["arguments"], request["cwd"], request["env"], log)
        self.remember()
        return process

    def do_step(self, request: dict) -> dict:
        process = self.start(request)
        deadline = time.time() + request["limit"]
        while process.poll() is None:
            if time.time() > deadline:
                self.tree.kill()
                return {"timed_out": True}
            if self.ending.wait(0.05):
                return {"ended": True}
        return {"code": process.returncode}

    def do_run(self, request: dict) -> dict:
        self.application = self.start(request)
        self.began, self.deadline, self.steady_deadline = time.time(), time.time() + self.limit, time.monotonic() + self.limit
        self.remember()
        return {"began": self.began}

    def do_poll(self, request: dict) -> dict:
        return {"ended": self.application.poll() is not None}

    def do_processes(self, request: dict) -> dict:
        return {"ids": self.tree.processes()}

    def do_ready(self, request: dict) -> dict:
        self.phase, self.port = "ready", int(request["port"])
        try:
            self.remember()
        except OSError:
            self.phase = "preparing"
            raise
        self.handed_over.set()
        return {"deadline": self.deadline}

    def reason_to_end(self) -> str:
        if os.path.exists(self.stop_file):
            try:
                with open(self.stop_file, encoding="utf-8") as file:
                    return "replaced" if file.read().strip() == "replace" else "asked"
            except OSError:
                return "asked"
        if not os.path.exists(self.path):  # no connector could ever find it again
            return "lost"
        if self.abandoned.is_set():
            return "abandoned"
        # one clock can be put back, and the other stands still while a computer sleeps
        if self.deadline and (time.time() > self.deadline or time.monotonic() > self.steady_deadline):
            return "time_limit"
        if self.phase == "ready" and self.application.poll() is not None:
            return "application"
        return ""

    def end(self, reason: str) -> None:
        self.ending.set()
        self.phase = "ending"
        with contextlib.suppress(OSError):
            if self.mine():
                self.remember()
        self.tree.kill()
        deadline = time.time() + 10
        while self.tree.running() and time.time() < deadline:
            time.sleep(0.05)
        if reason in ("time_limit", "application"):
            temporary = f"{self.ended_file}.{os.getpid()}.tmp"
            with open(temporary, "w", encoding="utf-8") as file:
                json.dump({"reason": reason, "head": self.head, "at": time.time()}, file)
            with contextlib.suppress(OSError):
                replace_file(temporary, self.ended_file)
        for _ in range(REMOVE_TRIES):
            shutil.rmtree(self.folder, ignore_errors=True)
            if not os.path.exists(self.folder):
                break
            time.sleep(0.5)
        if reason in ("asked", "time_limit", "lost"):  # a new version, a turn cut short or a crash keep the data
            for _ in range(REMOVE_TRIES):
                shutil.rmtree(self.keep, ignore_errors=True)
                if not os.path.exists(self.keep):
                    break
                time.sleep(0.5)
            with contextlib.suppress(OSError):
                os.remove(self.kept_file)
        if not os.path.exists(self.folder):  # or the state stays, for the next connector to finish the job
            self.forget()
        try:
            os.remove(self.stop_file)
        except OSError:
            pass
        if WINDOWS:  # an open file cannot be removed there; elsewhere a lock on a removed file would fool the next one
            self.alive.close()
        try:
            os.remove(self.alive_file)
        except OSError:
            pass
        self.alive.close()

    def mine(self) -> bool:
        try:
            with open(self.path, encoding="utf-8") as file:
                return json.load(file).get("token") == self.token
        except (OSError, ValueError, AttributeError):
            return False

    def forget(self) -> None:
        if self.mine():
            with contextlib.suppress(OSError):
                os.remove(self.path)

    def run(self) -> None:
        threading.Thread(target=self.listen, daemon=True).start()
        threading.Thread(target=self.serve, daemon=True).start()
        while True:
            reason = self.reason_to_end()
            if reason:
                self.end(reason)
                return
            time.sleep(0.2)


def launch(arguments: list) -> None:
    subprocess.Popen([sys.executable, "-I", "-S", __file__, "watch", *arguments], stdin=sys.stdin, stdout=sys.stdout,
                     stderr=subprocess.DEVNULL, cwd=os.environ.get("SYSTEMROOT") or "/",
                     **({"creationflags": DETACHED | NEW_GROUP} if WINDOWS else {"start_new_session": True}))


def watch() -> None:
    for name in ("SIGHUP", "SIGINT"):  # a terminal or a group's end is not a reason to go
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_IGN)
    config = json.loads(sys.stdin.buffer.readline())
    watcher = Watcher(config)
    if not watcher.hold():
        watcher.reply({"taken": True})
        return
    for path in (watcher.stop_file, watcher.ended_file):
        try:
            os.remove(path)
        except OSError:
            pass
    watcher.remember()
    watcher.reply({"watching": os.getpid(), "keeps_running": detached()})
    watcher.run()


if __name__ == "__main__":
    if sys.argv[1] == "launch":
        launch(sys.argv[2:])
    else:
        watch()
