"""Shared fixtures: an isolated per-user folder, a hostile machine git configuration, and a fake git server.

The fake server plays OAuth 2.0 (authorize + token), the user endpoint, git smart HTTP (dulwich) and the two
Gitea API calls the connector makes. Nothing leaves this computer.
"""

import base64
import json
import os
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
            self.records.pop((service, user))

    keyring.set_keyring(_Memory())

from dulwich.repo import Repo  # noqa: E402
from dulwich.server import DictBackend  # noqa: E402
from dulwich.web import make_wsgi_chain  # noqa: E402


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
            env["wsgi.input"].read(int(env.get("CONTENT_LENGTH") or 0))  # unread data makes Windows reset the socket
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
                if any(p["head"] == body["head"] for p in self.pulls):
                    return reply("409 Conflict", {"message": "pull request already exists"})
                if f"refs/heads/{body['head']}".encode() not in self.repos[name].refs:
                    return reply("404 Not Found", {"message": "head not found"})
                self.pulls.append(body)
                return reply("201 Created", {"number": len(self.pulls),
                                             "html_url": f"{self.url}/me/{name}/pulls/{len(self.pulls)}"})
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
