"""Shared fixtures: an isolated per-user folder, a hostile machine git configuration, and a fake git server.

The fake server plays OAuth 2.0 (authorize + token), the user endpoint, git smart HTTP (dulwich) and the two
Gitea API calls the connector makes. Nothing leaves this computer.
"""

import atexit
import base64
import json
import os
import shutil
import socket
import sys
import tempfile
import socketserver
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import pytest

# Before the connector is imported: its per-user folder goes to a temporary place, and the machine's git
# configuration (system and user) is made hostile (CRLF checkouts, a filter that would run a command). The connector must ignore it.
_SANDBOX = Path(tempfile.mkdtemp(prefix="eunomai-tests-"))
atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)
# On Windows a run cannot remove its own folder (the fake server keeps its git packs open until the process ends):
# each run removes what earlier runs left, once they are an hour old.
for _old in _SANDBOX.parent.glob("eunomai-tests-*"):
    if _old != _SANDBOX and time.time() - _old.stat().st_mtime > 3600:
        shutil.rmtree(_old, ignore_errors=True)
os.environ["LOCALAPPDATA"] = str(_SANDBOX / "appdata")
os.environ["HOME"] = str(_SANDBOX / "home")
_HOSTILE = _SANDBOX / "hostile-gitconfig"
_HOSTILE.write_text('[core]\n\tautocrlf = true\n[filter "evil"]\n\tclean = exit 1\n', encoding="utf-8")
os.environ["GIT_CONFIG_SYSTEM"] = str(_HOSTILE)
os.environ["GIT_CONFIG_GLOBAL"] = str(_HOSTILE)

if sys.platform != "win32":  # the OS keyring is not available in a test run: keep records in memory
    import keyring
    from keyring.backend import KeyringBackend

    class _Memory(KeyringBackend):
        priority = 1
        records: dict = {}

        def get_password(self, service, user):
            return self.records.get((service, user))

        def set_password(self, service, user, password):
            self.records[(service, user)] = password

        def delete_password(self, service, user):
            if (service, user) not in self.records:  # as the real backends do
                raise keyring.errors.PasswordDeleteError("not found")
            del self.records[(service, user)]

    keyring.set_keyring(_Memory())

from dulwich.object_store import commit_tree_changes  # noqa: E402
from dulwich.objects import Blob, Commit, Tree  # noqa: E402
from dulwich.repo import Repo  # noqa: E402
from dulwich.server import DictBackend  # noqa: E402
from dulwich.web import make_wsgi_chain  # noqa: E402


def alive(pid: int) -> bool:
    """Whether a process is still running. A zombie is not: it only waits for its parent to read how it ended."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # to wait on it
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102  # still running
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")
    return not stat.exists() or stat.read_text().rpartition(")")[2].split()[0] != "Z"


def stop_previews() -> None:
    """Everything previews a test left running: a preview outlives what started it, a test run included."""
    from eunomai_business import data_dir, preview

    for current in list(preview._previews.values()):
        current.close()
    preview._previews.clear()
    preview._unread.clear()
    folder = data_dir() / "previews"
    for state in folder.glob("*.json") if folder.is_dir() else ():
        if preview._watching(state):
            preview._end(state)
        preview._clear(state)
    for note in folder.glob("*.ended") if folder.is_dir() else ():
        note.unlink(missing_ok=True)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeServer:
    """One fake git hosting server for the whole test session; each test registers its own repositories."""

    def __init__(self):
        self.repos: dict[str, Repo] = {}
        self.default_branch: dict[str, str] = {}
        self.tokens: dict[str, float] = {}
        self.token_lifetime = 3600
        self.reject_refresh = False
        self.pulls: list[dict] = []
        self.git_auth: list[tuple[str, bool]] = []
        self.backend = DictBackend({})
        self.git_app = make_wsgi_chain(self.backend)

        class Quiet(WSGIRequestHandler):
            def log_message(self, *args):
                pass

        class Threaded(socketserver.ThreadingMixIn, WSGIServer):  # sign-in and git calls overlap
            daemon_threads = True

        self.httpd = make_server("127.0.0.1", 0, self.app, server_class=Threaded, handler_class=Quiet)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def new_repo(self, name: str, default_branch: str = "main") -> Repo:
        (_SANDBOX / "server").mkdir(exist_ok=True)
        repo = Repo.init_bare(str(_SANDBOX / "server" / f"{name}.git"), mkdir=True)
        repo.refs.set_symbolic_ref(b"HEAD", f"refs/heads/{default_branch}".encode())
        self.repos[name] = repo
        self.default_branch[name] = default_branch
        self.backend.repos[f"/me/{name}.git"] = repo
        return repo

    def initialize(self, name: str, default_branch: str = "main") -> Repo:
        """What IT does: a repository with a first commit (a README) on its main branch."""
        repo = self.new_repo(name, default_branch)
        blob = Blob.from_string(b"# Sandbox\n\nShared notes.\n")
        repo.object_store.add_object(blob)
        tree = commit_tree_changes(repo.object_store, Tree(), [(b"README.md", 0o100644, blob.id)])
        commit = Commit()
        commit.tree, commit.parents = getattr(tree, "id", tree), []
        commit.author = commit.committer = b"IT <it@example.test>"
        commit.commit_time = commit.author_time = int(time.time())
        commit.commit_timezone = commit.author_timezone = 0
        commit.message = b"Initial commit"
        repo.object_store.add_object(commit)
        repo.refs[f"refs/heads/{default_branch}".encode()] = commit.id
        return repo

    def server_commit(self, name: str, branch: str, files: dict | None = None, message: str = "Change on the server",
                      tree_of: bytes | None = None, merge_parent: bytes | None = None) -> bytes:
        """A commit made on the server by someone else: new file contents, or another commit's tree."""
        repo = self.repos[name]
        ref = f"refs/heads/{branch}".encode()
        parent = repo.refs[ref]
        if tree_of is not None:
            tree = repo[tree_of].tree
        else:
            changes = []
            for path, data in (files or {}).items():
                blob = Blob.from_string(data)
                repo.object_store.add_object(blob)
                changes.append((path.encode(), 0o100644, blob.id))
            result = commit_tree_changes(repo.object_store, repo[repo[parent].tree], changes)
            tree = getattr(result, "id", result)
        commit = Commit()
        commit.tree, commit.parents = tree, [parent] + ([merge_parent] if merge_parent else [])
        commit.author = commit.committer = b"Someone Else <someone@example.test>"
        commit.commit_time = commit.author_time = int(time.time())
        commit.commit_timezone = commit.author_timezone = 0
        commit.message = message.encode()
        repo.object_store.add_object(commit)
        repo.refs[ref] = commit.id
        return commit.id

    def accept(self, name: str, version: str, squash: bool = False) -> None:
        """IT merges the version's pull request (merge commit or squash) and deletes the branch."""
        repo = self.repos[name]
        head = repo.refs[f"refs/heads/{version}".encode()]
        main = self.default_branch[name]
        if squash:
            self.server_commit(name, main, message=f"{version} (squashed)", tree_of=head)
        else:
            self.server_commit(name, main, message=f"Merge {version}", tree_of=head, merge_parent=head)
        for pull in self.pulls:
            if pull["repo"] == name and pull["head"]["ref"] == version and pull["state"] == "open":
                pull.update(state="closed", merged=True)
        del repo.refs[f"refs/heads/{version}".encode()]

    def pulls_of(self, name: str) -> list[dict]:
        return [pull for pull in self.pulls if pull["repo"] == name]

    def provider(self, client_id: str = "test-client") -> dict:
        return {"authorize_url": f"{self.url}/login/oauth/authorize",
                "token_url": f"{self.url}/login/oauth/access_token", "client_id": client_id,
                "redirect_uri": f"http://127.0.0.1:{free_port()}/callback", "userinfo_url": f"{self.url}/api/v1/user"}

    def app(self, env, start):
        path, method = env["PATH_INFO"], env["REQUEST_METHOD"]
        header = env.get("HTTP_AUTHORIZATION", "")
        bearer_ok = header.startswith("Bearer ") and self.tokens.get(header[7:], 0) > time.time()

        def reply(code, body, headers=()):
            start(code, [("Content-Type", "application/json"), *headers])
            return [json.dumps(body).encode()]

        if path == "/login/oauth/authorize":
            query = {k: v[0] for k, v in parse_qs(env["QUERY_STRING"]).items()}
            target = query["redirect_uri"] + "?" + urlencode({"code": "code-1", "state": query["state"]})
            start("302 Found", [("Location", target)])
            return [b""]
        if path == "/login/oauth/access_token":
            # read the whole body: unread data makes Windows reset the socket
            form = parse_qs(env["wsgi.input"].read(int(env.get("CONTENT_LENGTH") or 0)).decode())
            if form.get("grant_type") == ["refresh_token"] and self.reject_refresh:
                return reply("400 Bad Request", {"error": "invalid_grant"})
            access = f"token-{len(self.tokens)}"
            self.tokens[access] = time.time() + self.token_lifetime
            return reply("200 OK", {"access_token": access, "refresh_token": "refresh-1",
                                    "expires_in": self.token_lifetime})
        if path == "/api/v1/user":
            if not bearer_ok:
                return reply("401 Unauthorized", {})
            return reply("200 OK", {"login": "tester", "full_name": "Test User", "email": "tester@example.test"})
        if path.startswith("/api/v1/repos/me/"):
            if not bearer_ok:
                return reply("401 Unauthorized", {})
            name = path.split("/")[5]
            if path.endswith("/pulls") and method == "POST":
                body = json.loads(env["wsgi.input"].read(int(env["CONTENT_LENGTH"])))
                if any(p["repo"] == name and p["head"]["ref"] == body["head"] and p["state"] == "open"
                       for p in self.pulls):
                    return reply("409 Conflict", {"message": "pull request already exists"})
                ref = f"refs/heads/{body['head']}".encode()
                head = self.repos[name].refs[ref] if ref in self.repos[name].refs else None
                if head is None:
                    return reply("404 Not Found", {"message": "head not found"})
                number = len(self.pulls) + 1
                self.pulls.append({"repo": name, "number": number, "state": "open", "merged": False,
                                   "head": {"ref": body["head"], "sha": head.decode()}, "base": body["base"],
                                   "title": body["title"], "body": body.get("body", ""), "reviews": [],
                                   "comments": [], "user": {"login": "tester"}})
                return reply("201 Created", {"number": number, "html_url": f"{self.url}/me/{name}/pulls/{number}"})
            if "/pulls/" in path and method == "PATCH":
                body = json.loads(env["wsgi.input"].read(int(env["CONTENT_LENGTH"])))
                pull = next(p for p in self.pulls if p["repo"] == name and p["number"] == int(path.split("/")[-1]))
                pull.update({k: body[k] for k in ("title", "body") if k in body})
                return reply("201 Created", {"number": pull["number"]})
            if path.endswith("/pulls"):
                return reply("200 OK", [{k: v for k, v in p.items() if k not in ("repo", "reviews", "comments")}
                                        for p in self.pulls if p["repo"] == name])
            if "/pulls/" in path and "/reviews" in path:  # .../pulls/{n}/reviews and .../reviews/{id}/comments
                parts = path.split("/")
                pull = next(p for p in self.pulls if p["repo"] == name and p["number"] == int(parts[7]))
                if parts[-1] == "comments":
                    review = next(r for r in pull["reviews"] if r["id"] == int(parts[9]))
                    if review.get("inline_status"):
                        return reply(review["inline_status"], {})
                    return reply("200 OK", review.get("inline", []))
                page = int(parse_qs(env["QUERY_STRING"]).get("page", ["1"])[0])  # all on page 1, as Gitea pages
                return reply("200 OK", [{k: v for k, v in r.items() if k not in ("inline", "inline_status")}
                                        for r in pull["reviews"]] if page == 1 else [])
            if "/issues/" in path and path.endswith("/comments"):
                pull = next(p for p in self.pulls if p["repo"] == name and p["number"] == int(path.split("/")[7]))
                return reply("200 OK", pull["comments"])
            return reply("200 OK", {"default_branch": self.default_branch[name]})
        if path.startswith("/me/") and ".git" in path:
            user, password = "", ""
            if header.startswith("Basic "):
                user, _, password = base64.b64decode(header[6:]).decode().partition(":")
            valid = self.tokens.get(password, 0) > time.time()
            self.git_auth.append((user, valid))
            if not valid:
                start("401 Unauthorized", [("WWW-Authenticate", 'Basic realm="git"')])
                return [b""]
            return self.git_app(env, start)
        return reply("404 Not Found", {})


@pytest.fixture(scope="session")
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def workspaces(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "workspaces"
    monkeypatch.setenv("EUNOMAI_WORKSPACES_ROOT", str(root))
    return root


@pytest.fixture
def signed_in(server, monkeypatch):
    """Configure the fake server as the "git" provider and sign in, as the browser would."""
    import httpx

    from eunomai_business import auth

    monkeypatch.setenv("EUNOMAI_PROVIDERS", json.dumps({"git": server.provider()}))
    auth.sign_out("git")
    started = auth.start("git", open_browser=False)
    httpx.get(started["url"], follow_redirects=True)  # plays the browser
    for _ in range(50):
        if auth.status("git")["status"] != "waiting":
            break
        time.sleep(0.1)
    assert auth.status("git")["status"] == "signed_in", auth.status("git")
    return server
