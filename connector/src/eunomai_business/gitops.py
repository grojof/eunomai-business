"""Workspaces, versions (branches) and save points (commits), without Git installed (dulwich).

Each workspace is a clone in the workspaces folder the organization sets when it builds the plugin (default
~/eunomai-business-workspaces/<workspace>). The user selects the workspace's folder in Cowork, so Claude edits the
same files the connector saves. The git sign-in token goes only to the git server's own origin, as HTTP basic auth
(login + OAuth access token); it is never written to .git/config, only to the encrypted sign-in record.
"""

import hashlib
import io
import json
import os
import re
import shutil
import socket
import ssl
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import truststore
import urllib3
from dulwich import porcelain
from dulwich.client import get_transport_and_path
from dulwich.config import ConfigFile, StackedConfig
from dulwich.diff_tree import tree_changes
from dulwich.errors import HangupException
from dulwich.graph import can_fast_forward, find_merge_base
from dulwich.merge import recursive_merge
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Commit
from dulwich.repo import Repo

from . import auth, data_dir
from .support import NeedsIT, Unreachable

# Ignore the computer's own git configuration (system and user): Git for Windows sets core.autocrlf=true there,
# which made checkouts CRLF, and a global filter would run commands. Same behaviour with or without Git
# installed. Only this process is affected.
os.environ.pop("GIT_CONFIG_SYSTEM", None)  # dulwich reads it even with GIT_CONFIG_NOSYSTEM set
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["GIT_CONFIG_GLOBAL"] = str(data_dir() / "no-global-gitconfig")  # never created

PROVIDER = "git"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BRANCH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ALWAYS_PROTECTED = {"main", "master"}
# The folder is also writable from Claude's sandbox, .git included. Only these config entries are accepted, so
# nothing written there (filters, hooksPath, fsmonitor, includes...) can make this host process run a command.
_SAFE_CORE = {b"repositoryformatversion", b"filemode", b"bare", b"logallrefupdates", b"ignorecase",
              b"symlinks", b"precomposeunicode", b"autocrlf"}
_SAFE_SECTIONS = {b"remote": {b"url", b"fetch"}, b"branch": {b"remote", b"merge"}}


def root() -> Path:
    """Workspaces folder: EUNOMAI_WORKSPACES_ROOT with ~ and %VAR% expanded."""
    raw = os.environ.get("EUNOMAI_WORKSPACES_ROOT") or "~/eunomai-business-workspaces"
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not path.is_absolute():
        raise ValueError(f"workspaces folder must be absolute after expansion, got {raw!r}")
    return path


_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)


def _folder(workspace: str) -> Path:
    if not _NAME.match(workspace or "") or _WINDOWS_RESERVED.match(workspace):
        raise ValueError("workspace must be a plain folder name (letters, digits, . _ -), not a reserved name")
    return root() / workspace


class _NoFilters:
    """Content goes in and out exactly as it is: no filter driver, no line-ending conversion, no LFS."""

    def checkin_normalize(self, blob, tree_path):
        return blob

    def checkout_normalize(self, blob, tree_path):
        return blob

    def close(self):
        pass


class _Workspace(Repo):
    """A repository the connector can trust while Claude's sandbox writes into the same folder, `.git` included.

    Hooks never run (dulwich runs post-commit even with no_verify). Content is never filtered. Once validated, the
    configuration is pinned: dulwich re-reads .git/config on every call, so a filter written between the check and
    the use would otherwise run on this computer."""

    _pinned: ConfigFile | None = None  # Repo.__init__ already reads the configuration

    def __init__(self, path: str):
        super().__init__(path)
        self.hooks.clear()

    def pin(self, config: ConfigFile) -> None:
        self._pinned = config

    def get_config(self) -> ConfigFile:
        return self._pinned if self._pinned is not None else super().get_config()

    def get_config_stack(self) -> StackedConfig:
        if self._pinned is None:
            return super().get_config_stack()
        return StackedConfig([self._pinned], writable=self._pinned)

    def get_blob_normalizer(self, config=None) -> _NoFilters:
        return _NoFilters()


def _open(path: str) -> _Workspace:
    return _Workspace(path)


def _repo(workspace: str) -> _Workspace:
    """Open a workspace's repository, validated and pinned. Use it in a `with` block: open pack files lock the
    folder on Windows."""
    folder = _folder(workspace)
    if not (folder / ".git").is_dir():
        raise FileNotFoundError(f"no workspace named {workspace!r} in {root()}; see workspace_list")
    repo = _open(str(folder))
    try:
        config = Repo.get_config(repo)
        _check_config(repo, config)
        repo.pin(config)
    except Exception:
        repo.close()
        raise
    return repo


def _check_config(repo: Repo, config: ConfigFile) -> None:
    def stop(problem: str, detail: str):
        raise NeedsIT("This workspace has a setting the connector does not accept, so it stopped to keep your "
                      "work safe.", problem, {"Folder": repo.path, "Detail": detail})

    controldir = Path(repo.controldir())
    if Path(repo.commondir()).resolve() != controldir.resolve():
        stop("the repository points to another folder (commondir)", repo.commondir())
    if (controldir / "objects" / "info" / "alternates").exists():
        stop("the repository borrows objects from another folder (alternates)", "objects/info/alternates")
    registered = _registry().get(str(Path(repo.path).resolve()), {}).get("origin")
    try:
        configured = config.get((b"remote", b"origin"), b"url").decode()
    except KeyError:
        configured = None
    if registered and configured != registered:
        stop("the repository address in .git/config changed after the clone", f"{configured} != {registered}")
    for section in config.sections():
        allowed = _SAFE_CORE if section == (b"core",) else _SAFE_SECTIONS.get(section[0])
        unexpected = [key for key, _ in config.items(section) if allowed is None or key.lower() not in allowed]
        if unexpected:
            name = b".".join(section).decode(errors="replace")
            stop("unexpected entry in .git/config",
                 f"{name}: {', '.join(k.decode(errors='replace') for k in unexpected)}")


def _git_session() -> dict:
    current = auth.session(PROVIDER)
    if not current:
        raise PermissionError(f"not signed in to {PROVIDER!r}: run sign_in_start({PROVIDER!r}) first")
    return current


def _origin_of(url: str) -> tuple[str, str | None, int]:
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or {"https": 443, "http": 80}.get(parts.scheme, 0)


def _check_host(url: str, current: dict) -> None:
    """The token may only travel to the git server the sign-in belongs to."""
    auth.check_url(url)
    if _origin_of(url) != _origin_of(current["cfg"]["userinfo_url"]):
        server = urlsplit(current["cfg"]["userinfo_url"])
        raise PermissionError(f"{urlsplit(url).netloc} is not the signed-in git server ({server.netloc})")


def _remote(current: dict) -> dict:
    """Arguments for dulwich's HTTP client: OS certificate store, basic auth with the OAuth token."""
    pool = urllib3.PoolManager(ssl_context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=30)
    login = str(current["user"].get(current["cfg"]["login_field"], "oauth"))
    return {"username": login, "password": current["record"]["access_token"], "pool_manager": pool}


def _origin(repo: Repo) -> str | None:
    """The repository the workspace was cloned from, as recorded by the connector (never read from .git)."""
    return _registry().get(str(Path(repo.path).resolve()), {}).get("origin")


def _registered_origin(repo: Repo, workspace: str) -> str:
    origin = _origin(repo)
    if origin is None:
        raise NeedsIT("This workspace was not set up by this version of the connector. Your files are safe; IT can "
                      "set it up again.", "workspace not in the connector's registry", {"Workspace": workspace,
                                                                                        "Folder": repo.path})
    return origin


_held = threading.local()


@contextmanager
def _exclusive(name: str, wait: float = 15.0):
    """One operation at a time per workspace (and on the registry), across threads and connector processes: a
    lock file in the connector's own folder, which Claude's sandbox cannot reach. Re-entrant within a thread."""
    held = getattr(_held, "names", None)
    if held is None:
        held = _held.names = set()
    if name in held:
        yield
        return
    lock = data_dir() / "locks" / (hashlib.sha256(name.encode()).hexdigest()[:16] + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + wait
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 600:  # left behind by a process that died
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise PermissionError("another operation on this workspace is still running; try again shortly")
            time.sleep(0.1)
    held.add(name)
    try:
        yield
    finally:
        held.discard(name)
        lock.unlink(missing_ok=True)


def _one_at_a_time(operation):
    def wrapped(workspace: str, *args):
        with _exclusive(f"workspace:{workspace}"):
            return operation(workspace, *args)
    wrapped.__name__, wrapped.__doc__ = operation.__name__, operation.__doc__
    return wrapped


# What the connector must remember about each workspace lives in its own per-user folder, not in .git: Claude's
# sandbox can write .git, so nothing a barrier relies on can come from there.
def _registry() -> dict:
    try:
        return json.loads((data_dir() / "workspaces.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _remember(folder: Path, **values) -> None:
    with _exclusive("registry"):
        registry = _registry()
        registry.setdefault(str(folder.resolve()), {}).update(values)
        tmp = data_dir() / f"workspaces.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(registry, indent=1), encoding="utf-8")
        os.replace(tmp, data_dir() / "workspaces.json")


def _branch(repo: Repo) -> str | None:
    try:
        return porcelain.active_branch(repo).decode()
    except (KeyError, IndexError):
        return None


def _head(repo: Repo) -> str | None:
    try:
        return repo.head().decode()[:12]
    except KeyError:  # no commit yet
        return None


def _main_branch(repo: Repo) -> str | None:
    """The server's main branch, as it was when the workspace was cloned (None: the repository was empty)."""
    return _registry().get(str(Path(repo.path).resolve()), {}).get("main_branch")


def _protected(repo: Repo) -> set[str]:
    return _ALWAYS_PROTECTED | {name for name in [_main_branch(repo)] if name}


def _text(paths) -> list[str]:
    """Repository paths with '/' on every OS."""
    return sorted((p.decode() if isinstance(p, bytes) else str(p)).replace(os.sep, "/") for p in paths)


def _crlf(folder: Path, paths: list[str]) -> list[str]:
    """Changed files that contain CRLF line endings."""
    found = []
    for path in paths:
        file = folder / path
        if file.is_file():
            with open(file, "rb") as content:  # the first megabyte is enough, and a huge file costs nothing
                if b"\r\n" in content.read(1_000_000):
                    found.append(path)
    return found


def _author(current: dict) -> bytes:
    user = current["user"]
    name = user.get("full_name") or user.get("login") or "unknown"
    email = user.get("email") or f"{user.get('login', 'unknown')}@users.noreply"
    return f"{name} <{email}>".encode()


def _check_branch_name(name: str) -> None:
    parts = (name or "").split("/")
    if len(name or "") > 100 or not all(_BRANCH_PART.match(p) and not p.endswith((".", ".lock")) for p in parts) \
            or ".." in name:
        raise ValueError("version name: parts of letters, digits, . _ - separated by '/', each starting with a "
                         "letter or digit, no '..'")


def clone(repo_url: str, workspace: str = "") -> dict:
    current = _git_session()
    parts = urlsplit(repo_url)
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("repo_url must not contain credentials")
    _check_host(repo_url, current)
    workspace = workspace or Path(parts.path).name.removesuffix(".git")
    folder = _folder(workspace)
    if folder.exists():
        raise FileExistsError(f"{folder} already exists; use it or pick another workspace name")
    folder.parent.mkdir(parents=True, exist_ok=True)
    remote = _remote(current)
    client, path = get_transport_and_path(repo_url, **remote)
    advertised = _network(lambda: client.get_refs(path.encode()))
    refs = getattr(advertised, "refs", None) or {}
    default = (getattr(advertised, "symrefs", None) or {}).get(b"HEAD", b"").removeprefix(b"refs/heads/")
    heads = _text(r.removeprefix(b"refs/heads/") for r in refs if r.startswith(b"refs/heads/"))
    repo = None
    try:
        if heads:
            out = io.BytesIO()
            _network(lambda: porcelain.clone(repo_url, str(folder), checkout=False, errstream=out,
                                             **remote)).close()
        else:  # empty repository (no branch yet): set it up the way `git clone` would
            Repo.init(str(folder), mkdir=True).close()
        repo = _open(str(folder))
        config = Repo.get_config(repo)
        config.set((b"remote", b"origin"), b"url", repo_url.encode())
        config.set((b"remote", b"origin"), b"fetch", b"+refs/heads/*:refs/remotes/origin/*")
        config.set((b"core",), b"autocrlf", b"false")  # a Git on this computer sees the files as they are
        config.write_to_path()
        repo.pin(config)
        main = default.decode() or next((h for h in ("main", "master") if h in heads), heads[0] if heads else None)
        _remember(folder, origin=repo_url, main_branch=main if heads else None)
        if heads:
            porcelain.reset(repo, "hard", repo.head())  # files written without any filter
        else:
            repo.refs.set_symbolic_ref(b"HEAD", b"refs/heads/main")
    except Exception:
        if repo is not None:
            repo.close()
        shutil.rmtree(folder, ignore_errors=True)
        raise
    files = [p for p in folder.rglob("*") if p.is_file() and ".git" not in p.relative_to(folder).parts]
    with repo:
        return {"workspace": workspace, "path": str(folder), "origin": _origin(repo), "branch": _branch(repo),
                "head": _head(repo), "files": len(files), "empty_repository": not heads,
                "remote_branches": heads, "main_branch": _main_branch(repo)}


def workspaces() -> dict:
    found = []
    if root().is_dir():
        for folder in sorted(root().iterdir()):
            if (folder / ".git").is_dir():
                with _open(str(folder)) as repo:
                    found.append({"workspace": folder.name, "path": str(folder), "branch": _branch(repo),
                                  "head": _head(repo), "origin": _origin(repo)})
    return {"root": str(root()), "workspaces": found}


def status(workspace: str) -> dict:
    with _repo(workspace) as repo:
        st = porcelain.status(repo, untracked_files="all")
        staged = {kind: _text(paths) for kind, paths in st.staged.items() if paths}
        changed = _text(st.unstaged) + _text(st.untracked)
        return {"workspace": workspace, "branch": _branch(repo), "head": _head(repo), "staged": staged,
                "unstaged": _text(st.unstaged), "untracked": _text(st.untracked),
                "crlf_in_changed_files": _crlf(Path(repo.path), changed)}


@_one_at_a_time
def branch(workspace: str, name: str) -> dict:
    """Create a version (branch) from the main branch and switch to it; local changes are kept."""
    _check_branch_name(name)
    with _repo(workspace) as repo:
        if name.lower() in {p.lower() for p in _protected(repo)}:  # Windows treats Main and main as one
            raise PermissionError(f"{name!r} is the repository's main branch, not a version")
        ref = f"refs/heads/{name}".encode()
        if ref in repo.refs:
            raise FileExistsError(f"version {name!r} already exists")
        previous = _branch(repo)
        if _main_branch(repo) is None or _head(repo) is None:
            raise PermissionError("the repository has no main branch yet: whoever manages it must initialize it "
                                  "(for example with a README) before versions can be created")
        if previous not in _protected(repo):  # a version never stacks on another, possibly unaccepted, one
            raise PermissionError(f"versions start from the main branch; the workspace is on version {previous!r}: "
                                  "keep working on it, or bring the latest changes once it is accepted")
        repo.refs[ref] = repo.head()
        repo.refs.set_symbolic_ref(b"HEAD", ref)  # same commit, so the working tree stays as it is
        return {"workspace": workspace, "branch": name, "from": previous, "head": _head(repo)}


@_one_at_a_time
def save(workspace: str, message: str) -> dict:
    """Save point: stage every change (new, modified, deleted) and commit as the signed-in git user."""
    if not (message or "").strip():
        raise ValueError("a save point needs a message")
    current = _git_session()
    with _repo(workspace) as repo:
        if _branch(repo) is None or _branch(repo) in _protected(repo):
            raise PermissionError("create a version first: save points never go straight to the main branch")
        before = status(workspace)
        porcelain.add(repo)  # no paths: new and modified files from the repository root
        st = porcelain.status(repo)
        if not any(st.staged.values()) and not st.unstaged:
            return {"workspace": workspace, "saved": False, "reason": "nothing changed"}
        # all=True also takes modified and deleted tracked files, like `git commit -a`
        sha = porcelain.commit(repo, message=message.strip().encode(), author=_author(current),
                               committer=_author(current), all=True, no_verify=True)
        return {"workspace": workspace, "saved": True, "branch": _branch(repo), "commit": sha.decode()[:12],
                "files": sorted({*before["untracked"], *before["unstaged"], *sum(before["staged"].values(), [])}),
                "crlf_in_changed_files": before["crlf_in_changed_files"]}


@_one_at_a_time
def push(workspace: str) -> dict:
    """Send the current version to the server (never the main branch, never forced)."""
    current = _git_session()
    with _repo(workspace) as repo:
        name = _branch(repo)
        if name is None or name in _protected(repo):
            raise PermissionError("only versions are sent; the main branch changes through a pull request")
        origin = _registered_origin(repo, workspace)
        _check_host(origin, current)
        out = io.BytesIO()
        try:
            result = _network(lambda: porcelain.push(repo, origin, f"refs/heads/{name}:refs/heads/{name}".encode(),
                                                     outstream=out, errstream=out, **_remote(current)))
        except porcelain.DivergedBranches as exc:  # never forced: the server keeps what it has
            raise NeedsIT("This version was changed on the server from somewhere else, so it was not sent. Your work "
                          "is safe on this computer; IT can combine both.",
                          "the version on the server has changes this computer does not have",
                          _facts(repo, workspace)) from exc
        errors = {ref.decode(): str(err) for ref, err in (result.ref_status or {}).items() if err}
        if errors:
            raise NeedsIT("The server did not accept this version. Your work is safe on this computer.",
                          "the server rejected the version", _facts(repo, workspace, rejected=errors))
        web = origin.removesuffix(".git")
        return {"workspace": workspace, "branch": name, "pushed": True, "head": _head(repo),
                "web_url": f"{web}/src/branch/{name}"}


# --- the git hosting's API (Gitea for now; the hosting adapter comes later) ----------------------------------

def _api(origin: str, current: dict) -> tuple[str, dict]:
    parts = urlsplit(origin)
    segments = parts.path.strip("/").removesuffix(".git").split("/")
    prefix = "".join(f"/{s}" for s in segments[:-2])  # servers published under a sub-path
    api = f"{parts.scheme}://{parts.netloc}{prefix}/api/v1/repos/{segments[-2]}/{segments[-1]}"
    return api, {"Authorization": f"Bearer {current['record']['access_token']}", "Accept": "application/json"}


def _proposal_for(origin: str, current: dict, version: str) -> dict | None:
    """The latest pull request of a version: number, whether it was merged, and the commit it proposed.
    None when the hosting cannot tell; the caller then relies on the history alone."""
    api, headers = _api(origin, current)
    mine = []
    try:
        with auth.http_client() as client:  # most recently updated first; a version's proposal is recent
            for page in range(1, 6):
                response = client.get(f"{api}/pulls", headers=headers,
                                      params={"state": "all", "sort": "recentupdate", "limit": 50, "page": page})
                if response.status_code != 200:
                    return None
                batch = response.json()
                mine += [p for p in batch if (p.get("head") or {}).get("ref") == version]
                if mine or len(batch) < 50:
                    break
    except Exception:
        return None
    if not mine:
        return None
    latest = max(mine, key=lambda p: p.get("number", 0))
    return {"number": latest.get("number"), "merged": bool(latest.get("merged")), "state": latest.get("state"),
            "head": (latest.get("head") or {}).get("sha")}


def pull_request(workspace: str, title: str, description: str = "") -> dict:
    """Propose the current version for the main branch. Gitea API for now; the hosting adapter comes later."""
    if not (title or "").strip():
        raise ValueError("a pull request needs a title")
    current = _git_session()
    with _repo(workspace) as repo:
        name = _branch(repo)
        if name is None or name in _protected(repo):
            raise PermissionError("a pull request proposes a version: switch to one first")
        origin = _registered_origin(repo, workspace)
    _check_host(origin, current)
    api, headers = _api(origin, current)
    with auth.http_client() as client:
        info = client.get(api, headers=headers)
        info.raise_for_status()
        base = info.json().get("default_branch") or "main"
        response = client.post(f"{api}/pulls", headers=headers,
                               json={"head": name, "base": base, "title": title.strip(), "body": description})
    if response.status_code == 409:
        return {"workspace": workspace, "created": False, "head": name, "base": base,
                "reason": "a pull request for this version is already open"}
    if response.status_code != 201:
        raise RuntimeError(f"git server answered {response.status_code}: {response.text[:300]}")
    pr = response.json()
    return {"workspace": workspace, "created": True, "number": pr.get("number"), "url": pr.get("html_url"),
            "head": name, "base": base}


# --- bringing the latest changes -------------------------------------------------------------------------------

def _ref(repo: Repo, ref: bytes) -> bytes | None:
    return repo.refs[ref] if ref in repo.refs else None


def _dirty(repo: Repo) -> bool:
    st = porcelain.status(repo, untracked_files="all")
    return bool(any(st.staged.values()) or st.unstaged or st.untracked)


def _facts(repo: Repo, workspace: str, **more) -> dict:
    """What IT needs to understand a workspace's state. Never tokens."""
    return {"Workspace": workspace, "Folder": repo.path, "Repository": _origin(repo), "Version": _branch(repo),
            "Head": _head(repo), "Main branch": _main_branch(repo), **more}


def _network(call):
    """Run a server call; an unreachable server is the user's network, not a problem for IT."""
    try:
        return call()
    except (ConnectionError, TimeoutError, socket.gaierror, urllib3.exceptions.HTTPError, HangupException) as exc:
        raise Unreachable() from exc  # not every OSError: a local disk problem is not the network


def _backup(repo: Repo, *branches: str) -> str:
    """Keep where each branch was before anything moves: refs/eunomai/backup/<time>/<branch>."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name in branches:
        ref = f"refs/heads/{name}".encode()
        if ref in repo.refs:
            repo.refs[f"refs/eunomai/backup/{stamp}/{name}".encode()] = repo.refs[ref]
    return f"refs/eunomai/backup/{stamp}"


def _track(repo: Repo, refs: dict) -> None:
    """Mirror the server's branches as refs/remotes/origin/*, dropping branches the server no longer has."""
    heads = {r.removeprefix(b"refs/heads/"): sha for r, sha in refs.items() if r.startswith(b"refs/heads/")}
    for ref in list(repo.refs.keys(base=b"refs/remotes/origin/")):
        if ref != b"HEAD" and ref not in heads:
            del repo.refs[b"refs/remotes/origin/" + ref]
    for name, sha in heads.items():
        repo.refs[b"refs/remotes/origin/" + name] = sha


def _would_overwrite(repo: Repo, target_tree: bytes) -> list[str]:
    """Files on disk that git does not track but the target would write: never overwrite them."""
    tracked = set(repo.open_index())
    folder = Path(repo.path)
    return sorted(entry.path.decode() for entry in iter_tree_contents(repo.object_store, target_tree)
                  if entry.path not in tracked and (folder / entry.path.decode()).exists())


def _changed_on_both_sides(repo: Repo, bases: list, ours: bytes, theirs: bytes) -> list[str]:
    """Files both sides changed since their common ancestor, unless they ended identical. With no single common
    ancestor every file counts as shared: nothing is combined automatically then."""
    if len(bases) != 1:
        return ["(no single common ancestor)"]
    base_tree = repo[bases[0]].tree

    def changed(commit: bytes) -> dict[bytes, bytes | None]:
        """Each changed path and its new content (None: deleted)."""
        found = {}
        for change in tree_changes(repo.object_store, base_tree, repo[commit].tree):
            if change.old is not None and change.old.path is not None:
                found[change.old.path] = None
            if change.new is not None and change.new.path is not None:
                found[change.new.path] = change.new.sha
        return found

    mine, theirs_ = changed(ours), changed(theirs)
    return _text(path for path in mine.keys() & theirs_.keys() if mine[path] != theirs_[path])


def _move(repo: Repo, branch_name: str, target: bytes, workspace: str) -> None:
    """Point a branch at target, make it current and update the files. Only on a clean workspace."""
    blocked = _would_overwrite(repo, repo[target].tree)
    if blocked:
        raise NeedsIT("The latest changes would replace files of yours that are not saved in the project. Nothing "
                      "was changed.", "untracked files in the way", _facts(repo, workspace, files=blocked))
    if _dirty(repo):  # something changed since the automatic save: never overwrite it
        raise NeedsIT("Files changed while the latest changes were being brought, so nothing was "
                      "replaced. Your work is safe; try again.", "workspace changed during an update",
                      _facts(repo, workspace))
    ref = f"refs/heads/{branch_name}".encode()
    repo.refs.set_symbolic_ref(b"HEAD", ref)
    porcelain.reset(repo, "hard", target)
    repo.refs[ref] = target


@_one_at_a_time
def update(workspace: str) -> dict:
    """Bring the latest changes from the server without losing anything (see the update tool for the rules)."""
    current = _git_session()
    notes = []
    with _repo(workspace) as repo:
        name, origin = _branch(repo), _registered_origin(repo, workspace)
        if name is None:
            raise NeedsIT("This workspace is in a state the connector does not handle on its own. Your files were "
                          "not touched.", "workspace without a current branch or without origin",
                          _facts(repo, workspace))
        dirty, on_main = _dirty(repo), name in _protected(repo)
    _check_host(origin, current)
    if dirty:  # 1. keep everything first
        if on_main:
            branch(workspace, f"work/{time.strftime('%Y%m%d-%H%M%S')}")
        save(workspace, "Automatic save before bringing the latest changes")
        notes.append("Your unsaved changes were saved first.")

    with _repo(workspace) as repo:
        name = _branch(repo)
        client, path = get_transport_and_path(origin, **_remote(current))
        fetched = _network(lambda: client.fetch(path.encode(), repo))  # 2. what the server has
        _track(repo, fetched.refs)
        main = _main_branch(repo)
        if main is None:  # the repository was empty at clone time; IT may have initialized it since
            heads = [r.removeprefix(b"refs/heads/").decode() for r in fetched.refs if r.startswith(b"refs/heads/")]
            main = next((h for h in ("main", "master") if h in heads), heads[0] if heads else None)
            if main is None:
                return {"workspace": workspace, "status": "up_to_date",
                        "user_message": "The project is still empty: nothing to bring yet."}
            _remember(Path(repo.path), main_branch=main)
        remote_main = _ref(repo, f"refs/remotes/origin/{main}".encode())
        if remote_main is None:
            raise NeedsIT("The project's main version is missing on the server. Your work is safe.",
                          "main branch not found on the server", _facts(repo, workspace))
        result = {"workspace": workspace}

        if name in _protected(repo) and name != main:
            raise NeedsIT("This copy of the project is on a branch the connector does not handle on its own. Your "
                          "work is safe.", "workspace on a main branch other than the server's", _facts(repo, workspace))
        if name == main:  # 4a. on the main branch: only fast-forward
            local = _ref(repo, f"refs/heads/{name}".encode())
            if local == remote_main:
                return {**result, "status": "up_to_date", "branch": name,
                        "user_message": " ".join(notes + ["Everything is up to date."])}
            if local is not None and not can_fast_forward(repo, local, remote_main):
                raise NeedsIT("This copy of the project differs from the server in a way the connector does not "
                              "resolve on its own. Your work is safe.", "local main branch diverged from the server",
                              _facts(repo, workspace))
            result["backup"] = _backup(repo, name)  # 3. a way back, before anything moves
            _move(repo, name, remote_main, workspace)
            return {**result, "status": "updated", "branch": name, "head": _head(repo),
                    "user_message": " ".join(notes + ["The latest changes of the project are here."])}

        version_head = repo.refs[f"refs/heads/{name}".encode()]
        local_main = _ref(repo, f"refs/heads/{main}".encode())  # fetching does not move it
        if local_main is not None and can_fast_forward(repo, version_head, local_main):
            # nothing saved in the version yet: it is not a proposal, it just moves to the latest main branch
            if version_head == remote_main:
                return {**result, "status": "up_to_date", "branch": name,
                        "user_message": " ".join(notes + ["Everything is up to date."])}
            result["backup"] = _backup(repo, name)
            _move(repo, name, remote_main, workspace)
            return {**result, "status": "updated", "branch": name, "head": _head(repo),
                    "user_message": " ".join(notes + ["The latest changes of the project are here."])}
        on_server = _ref(repo, f"refs/remotes/origin/{name}".encode())
        proposal = _proposal_for(origin, current, name)
        merged = can_fast_forward(repo, version_head, remote_main) or bool(
            proposal and proposal["merged"] and proposal["head"] == version_head.decode())
        if merged:  # 4b. the version is in the main branch: back to it, retire the version
            result["backup"] = _backup(repo, name, main)
            _move(repo, main, remote_main, workspace)
            del repo.refs[f"refs/heads/{name}".encode()]
            return {**result, "status": "updated", "branch": main, "head": _head(repo), "retired_version": name,
                    "user_message": " ".join(notes + ["Your proposal was accepted. You now have the latest version "
                                                      "of the project; start a new version for your next change."])}
        if on_server is not None and on_server != version_head and not can_fast_forward(repo, on_server,
                                                                                          version_head):
            raise NeedsIT("This version was changed on the server from somewhere else. Your work is safe; IT can "
                          "combine both.", "version diverged from its copy on the server",
                          _facts(repo, workspace))
        if proposal and proposal["state"] == "closed" and not proposal["merged"]:
            notes.append("Your last proposal was closed without being accepted; your version is kept.")
        if can_fast_forward(repo, remote_main, version_head):  # the version already has everything
            return {**result, "status": "up_to_date", "branch": name,
                    "user_message": " ".join(notes + ["Everything is up to date."])}

        # 4c. the main branch moved on: combine it into the version, only when no file was changed on both sides.
        # Lines of the same file are never merged automatically: two edits that do not collide as text can still
        # break each other, and that is not a call to make on the user's behalf.
        bases = find_merge_base(repo, [version_head, remote_main])
        shared = _changed_on_both_sides(repo, bases, version_head, remote_main)
        if shared:
            raise NeedsIT("The latest changes of the project touch the same files as your version, so they are not "
                          "combined automatically. Your work is safe; IT can combine them.",
                          "the version and the main branch changed the same files",
                          _facts(repo, workspace, files=shared))
        tree, conflicts = recursive_merge(repo.object_store, bases, repo[version_head], repo[remote_main])
        if conflicts:  # cannot happen when no file changed on both sides; kept as a second safety net
            raise NeedsIT("The latest changes of the project could not be combined with your version. Your work is "
                          "safe; IT can combine them.", "merge conflict between the version and the main branch",
                          _facts(repo, workspace, conflicts=_text(conflicts)))
        repo.object_store.add_object(tree)
        merge = Commit()
        merge.tree, merge.parents = tree.id, [version_head, remote_main]
        merge.author = merge.committer = _author(current)
        merge.commit_time = merge.author_time = int(time.time())
        merge.commit_timezone = merge.author_timezone = -time.timezone
        merge.message = f"Bring in the latest changes from {main}\n".encode()
        repo.object_store.add_object(merge)
        result["backup"] = _backup(repo, name)
        _move(repo, name, merge.id, workspace)
        return {**result, "status": "updated", "branch": name, "head": _head(repo),
                "user_message": " ".join(notes + ["The latest changes of the project were added to your version; "
                                                  "your work is kept."])}


def origin(workspace: str) -> str | None:
    """The repository a workspace was cloned from."""
    with _repo(workspace) as repo:
        return _origin(repo)


def proposal_state(workspace: str) -> dict | None:
    """The pull request of the current version, if the hosting can tell: number, state, merged. Best effort."""
    try:
        current = _git_session()
        with _repo(workspace) as repo:
            name, origin_url = _branch(repo), _origin(repo)
            if name is None or name in _protected(repo) or origin_url is None:
                return None
        return _proposal_for(origin_url, current, name)
    except Exception:
        return None
