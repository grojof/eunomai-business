"""Workspaces, versions (branches) and save points (commits), without Git installed (dulwich).

Each workspace is a clone in the workspaces folder the organization sets when it builds the plugin (default
~/eunomai-business-workspaces/<workspace>). The task has access to the workspace's folder, so Claude edits the same
files the connector saves. The git sign-in token goes only to the git server's own origin, as HTTP basic auth
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
import tempfile
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
from dulwich.errors import GitProtocolError, HangupException, NotTreeError
from dulwich.graph import can_fast_forward, find_merge_base
from dulwich.index import validate_path, validate_path_element_default, validate_path_element_ntfs
from dulwich.merge import recursive_merge
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob, Commit, SubmoduleEncountered
from dulwich.repo import ParentsProvider, Repo

from . import auth, data_dir, deps, guard
from .support import NeedsIT, Unreachable, clean

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
# Inert notes editors add to a branch (VS Code's merge base, its pull request link, a description) are accepted.
_SAFE_SECTIONS = {b"remote": {b"url", b"fetch"},
                  b"branch": {b"remote", b"merge", b"description", b"vscode-merge-base", b"github-pr-owner-number"}}
_CONTEXT_LIMIT = 20_000  # characters of the project's context handed to Claude
DECLARATION = ".eunomai/project.toml"  # what IT declares for the project, read from main
# A prototype opens in the user's browser: it must say, itself, that it loads nothing from other sites.
_PROTOTYPE = re.compile(r"(^|/)openspec/changes/.+/prototype/[^/]+\.html?$", re.IGNORECASE)
_CSP = re.compile(r"<meta[^>]+http-equiv=[\"']?content-security-policy[\"']?[^>]*default-src\s+'none'", re.IGNORECASE)
_AUDIT_KEPT_SECONDS = 900  # a send and the proposal after it read the same answer
_GITLINK = 0o160000


def root() -> Path:
    """Workspaces folder: EUNOMAI_WORKSPACES_ROOT with ~ and %VAR% expanded."""
    raw = os.environ.get("EUNOMAI_WORKSPACES_ROOT") or "~/eunomai-business-workspaces"
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not path.is_absolute():
        raise ValueError(f"workspaces folder must be absolute after expansion, got {raw!r}")
    return path


_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)
# Characters Windows does not allow in names, and names it silently trims (a trailing dot or space).
_WINDOWS_BAD = re.compile(r'[<>:"|?*\\\x00-\x1f]|[. ]$')


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


class _CommitsOnly(ParentsProvider):
    """A commit's parents as the commit itself says them. Reading it by name hashes it, so nothing beside it (grafts,
    shallow, a commit graph) can give history another shape. docs/barriers.md lists what `.git` can and cannot change."""

    def get_parents(self, commit_id, commit=None):
        return self.store[commit_id].parents


class _Workspace(Repo):
    """A repository the connector can trust while Claude's sandbox writes into the same folder, `.git` included.

    Hooks never run (dulwich runs post-commit even with no_verify). Content is never filtered. History comes from the
    commits alone: a commit graph is a cache anyone can write, and a Git on the computer may leave a real one there.
    Once validated, the configuration is pinned: dulwich re-reads .git/config on every call, so a filter written
    between the check and the use would otherwise run on this computer."""

    _pinned: ConfigFile | None = None  # Repo.__init__ already reads the configuration

    def __init__(self, path: str):
        super().__init__(path)
        self.hooks.clear()
        self.object_store.get_commit_graph = lambda: None  # not a setting: `core.commitGraph` is in .git/config

    def parents_provider(self) -> ParentsProvider:
        return _CommitsOnly(self.object_store)

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
    for rewrites in ("info/grafts", "shallow"):  # a connector's clones are full: this would rewrite what is checked
        if (controldir / rewrites).exists():
            stop("the repository rewrites its own history", rewrites)
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


def key(workspace: str) -> str:
    """What identifies a workspace: its folder, which on Windows two spellings of a name share."""
    return str(_folder(workspace).resolve())


def _one_at_a_time(operation):
    def wrapped(workspace: str, *args):
        with _exclusive(f"workspace:{key(workspace)}"):
            return operation(workspace, *args)
    wrapped.__name__, wrapped.__doc__ = operation.__name__, operation.__doc__
    return wrapped


# What the connector must remember about each workspace lives in its own per-user folder, not in .git: Claude's
# sandbox can write .git, so nothing a barrier relies on can come from there. Project plugins read it too, to tell
# their workspaces ({resolved folder: {"origin": ..., ...}}, templates/project-plugin): keep that shape.
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


def _note_version(repo: Repo, name: str) -> None:
    with _exclusive("registry"):
        folder = Path(repo.path)
        versions = _registry().get(str(folder.resolve()), {}).get("versions", [])
        _remember(folder, versions=sorted({*versions, name}))


def _forget_version(repo: Repo, name: str) -> None:
    with _exclusive("registry"):
        folder = Path(repo.path)
        versions = _registry().get(str(folder.resolve()), {}).get("versions", [])
        _remember(folder, versions=[version for version in versions if version != name])


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


def _status_of(repo: Repo, **options):
    """porcelain.status, with a link to another folder inside the workspace turned into a stop: dulwich fails on it,
    and the connector never follows it."""
    try:
        return porcelain.status(repo, **options)
    except ValueError as exc:
        if "subpath" not in str(exc):
            raise
        raise NeedsIT("This workspace contains a link to another folder, so the connector stopped to keep your work "
                      "safe.", "a link to another folder inside the workspace",
                      {"Folder": repo.path, "Detail": str(exc)}) from exc


def status(workspace: str) -> dict:
    with _repo(workspace) as repo:
        st = _status_of(repo, untracked_files="all")
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
        _note_version(repo, name)
        return {"workspace": workspace, "branch": name, "from": previous, "head": _head(repo)}


@_one_at_a_time
def save(workspace: str, message: str) -> dict:
    """Save point: stage every change (new, modified, deleted) and commit as the signed-in git user. Never carries
    the project's context, the repository's configuration or a file Windows would run (guard.py): the first two are
    put back as they were, the last stops the save, and the tree actually committed is checked again."""
    if not (message or "").strip():
        raise ValueError("a save point needs a message")
    current = _git_session()
    with _repo(workspace) as repo:
        if _branch(repo) is None or _branch(repo) in _protected(repo):
            raise PermissionError("create a version first: save points never go straight to the main branch")
        parent = _ref(repo, b"HEAD")
        before = status(workspace)
        changed = sorted({*before["untracked"], *before["unstaged"], *sum(before["staged"].values(), [])})
        _check_paths(repo, changed)
        top = Path(repo.path)
        executables = [path for path in changed if guard.kind(path) == "executable" and (top / path).exists()]
        if executables:  # removing one is fine
            raise PermissionError(f"not saved: {', '.join(executables)} would run on the user's computer with a "
                                  "double click; remove them, the work is tried inside the sandbox")
        unsealed = [path for path in changed if _PROTOTYPE.search(path) and (top / path).is_file()
                    and not (top / path).is_symlink()
                    and not _CSP.search((top / path).read_text(encoding="utf-8", errors="replace"))]
        if unsealed:
            raise PermissionError(f"not saved: {', '.join(unsealed)} needs, in its <head>, <meta http-equiv="
                                  "\"Content-Security-Policy\" content=\"default-src 'none'; style-src "
                                  "'unsafe-inline'; script-src 'unsafe-inline'; img-src data:\">, so the prototype "
                                  "loads nothing from other sites")
        restored = _restore(repo, [path for path in changed if guard.kind(path) in ("context", "config")])
        porcelain.add(repo)  # no paths: new and modified files from the repository root
        st = _status_of(repo)
        if not any(st.staged.values()) and not st.unstaged:
            return {"workspace": workspace, "saved": False, "reason": "nothing changed",
                    **({"restored": restored} if restored else {})}
        # all=True also takes modified and deleted tracked files, like `git commit -a`
        sha = porcelain.commit(repo, message=message.strip().encode(), author=_author(current),
                               committer=_author(current), all=True, no_verify=True)
        _check_saved(repo, parent, sha)
        return {"workspace": workspace, "saved": True, "branch": _branch(repo), "commit": sha.decode()[:12],
                "files": [path for path in changed if path not in restored],
                **({"restored": restored} if restored else {}),
                "crlf_in_changed_files": before["crlf_in_changed_files"]}


def _valid(path: str) -> bool:
    """A repository path that stays inside the workspace on any file system: no "..", no drive or absolute path,
    no name Windows forbids or trims (streams, trailing dots or spaces, device names, short names of .git)."""
    raw = path.encode()
    names_ok = all(part and not _WINDOWS_BAD.search(part) and not _WINDOWS_RESERVED.match(part)
                   for part in path.split("/"))
    return bool(path) and not path.startswith("/") and names_ok \
        and validate_path(raw, validate_path_element_default) and validate_path(raw, validate_path_element_ntfs)


def _check_paths(repo: Repo, changed: list[str]) -> None:
    """Every path in the change and in the index must be valid: the sandbox can write the index too."""
    invalid = sorted(p for p in {*changed, *(e.decode("utf-8", "replace") for e in repo.open_index())}
                     if not _valid(p))
    if invalid:
        raise NeedsIT("This workspace has a file name the connector does not accept, so nothing was saved. Your work "
                      "is safe on this computer.", "a path that leaves the workspace or is not valid on Windows",
                      {"Folder": repo.path, "Paths": ", ".join(invalid[:20])})


def _check_saved(repo: Repo, parent: bytes | None, saved: bytes) -> None:
    """The tree actually committed, against the guard: anything that slipped in between the checks and the commit
    (a file written meanwhile) undoes the save point."""
    found = _forbidden_changes(repo, parent, saved)
    if found:
        name = _branch(repo)
        repo.refs[f"refs/heads/{name}".encode()] = parent
        porcelain.reset(repo, "mixed", parent)  # the files stay on disk; only the save point is undone
        raise NeedsIT("A file changed while saving, so nothing was saved. Your work is safe on this computer.",
                      "a protected or executable file reached the save point", {"Folder": repo.path,
                                                                               "Paths": ", ".join(sorted(found))})


def _restore(repo: Repo, paths: list[str]) -> list[str]:
    """Put files only IT changes back as the last save point has them (removed if it did not have them), and take
    the others out of the index, so a save never carries them. Matched without regard to case, as Windows does."""
    if not paths:
        return []
    head = _ref(repo, b"HEAD")
    kept = {}
    if head:
        for entry in iter_tree_contents(repo.object_store, repo[head].tree):
            path = entry.path.decode("utf-8", "replace")
            if guard.kind(path) in ("context", "config"):
                kept[path.lower()] = (path, entry.sha)
    index = repo.open_index()
    top = Path(repo.path)
    for path in paths:
        original = kept.get(path.lower())
        target = original[0] if original else path
        _check_no_links(repo, target)
        file = top / target
        if file.is_symlink():
            file.unlink()  # a link is removed as a link, never followed
        if original:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(repo[original[1]].data)
        else:
            file.unlink(missing_ok=True)
        if path.encode() in index and (not original or path != target):
            del index[path.encode()]
    index.write()
    return paths


def _check_no_links(repo: Repo, path: str) -> None:
    """The sandbox can plant links: a folder on the way that leads elsewhere would make this host process write or
    delete outside the workspace."""
    top = Path(repo.path)
    parts = Path(path).parts
    folders = [top.joinpath(*parts[:n]) for n in range(1, len(parts))]
    outside = not (top / path).resolve().is_relative_to(top.resolve())
    if outside or any(f.is_symlink() or f.is_junction() for f in folders):
        raise NeedsIT("This workspace has a link to another folder where only IT's files belong, so nothing was "
                      "saved. Your work is safe on this computer.", "a link on the path of a protected file",
                      {"Folder": repo.path, "Path": path})


def _send_commit(repo: Repo, origin: str, current: dict, commit: bytes, target: bytes, force: bool, out):
    """Send one commit to one reference. By its id, not by a local reference: the sandbox can move those between the
    check and the send, so what goes is what was checked."""
    client, path = get_transport_and_path(origin, **_remote(current))

    def update_refs(refs: dict) -> dict:
        if not force and target in refs:
            porcelain.check_diverged(repo, refs[target], commit)
        return {target: commit}

    return _network(lambda: client.send_pack(path.encode(), update_refs, repo.generate_pack_data, progress=out.write))


def _check_changes(repo: Repo, workspace: str, commit: bytes, main: str) -> None:
    """What a version changed since it left the main branch, against the rules of a save: the sandbox can write .git,
    so a commit forged past version_save never leaves the computer nor runs on it."""
    bases = find_merge_base(repo, [main.encode(), commit])
    if not bases:
        raise NeedsIT("This version no longer shares its history with the project, which was rewritten on the server, "
                      "so it went no further. Your work is safe on this computer; IT can bring it across.",
                      "no common history with the main branch", _facts(repo, workspace))
    found = _forbidden_changes(repo, bases[0], commit)
    if found:
        raise NeedsIT("This version has a file only IT changes, so it went no further. Your work is safe on this "
                      "computer.", "a protected or executable file in a saved version",
                      _facts(repo, workspace, Paths=", ".join(sorted(found)[:20])))


def _check_version(repo: Repo, workspace: str, name: str, origin: str, current: dict) -> None:
    """Only what this connector made as a version is sent: HEAD is in .git, and a branch of the server's is not the
    sandbox's to choose. A workspace from before it kept them, or a version it lost track of, is taken as one if the
    server has no such branch yet, or has a proposal from it; anything else goes to IT."""
    if name in _registry().get(str(Path(repo.path).resolve()), {}).get("versions", []):
        return
    client, path = get_transport_and_path(origin, **_remote(current))
    advertised = _network(lambda: client.get_refs(path.encode()))
    if f"refs/heads/{name}".encode() in (getattr(advertised, "refs", None) or {}) \
            and not _proposal_for(origin, current, name):
        raise NeedsIT("This copy of the project is on something that is not one of your versions, so nothing was sent. "
                      "Your work is safe on this computer; IT can look at it.", "a branch the connector did not create",
                      _facts(repo, workspace))
    _note_version(repo, name)


@_one_at_a_time
def push(workspace: str, main: str, expected: str | None = None, version: str | None = None,
         test_branch: str | None = None) -> dict:
    """Send the current version to the server (never the main branch, never forced). `main` is the main branch's commit
    on the server, which what goes is checked against. `expected` and `version` are the commit that was audited and the
    branch it was audited on: that commit goes to that branch, and only if the version still is both. The branch name
    is read once, here: HEAD is in .git, and what follows does not look at it again."""
    current = _git_session()
    with _repo(workspace) as repo:
        name = _branch(repo)
        shared = {branch.casefold() for branch in _protected(repo) | ({test_branch} if test_branch else set())}
        if name is None or name.casefold() in shared:
            raise PermissionError("only versions are sent; the main branch changes through a pull request")
        if (version and name != version) or (expected and repo.head().decode() != expected):
            raise PermissionError("the version changed while it was being checked; send it again")
        origin = _registered_origin(repo, workspace)
        _check_host(origin, current)
        out = io.BytesIO()
        commit = expected.encode() if expected else repo.head()
        _check_changes(repo, workspace, commit, main)
        _check_version(repo, workspace, name, origin, current)
        try:
            result = _send_commit(repo, origin, current, commit, f"refs/heads/{name}".encode(), False, out)
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
        return {"workspace": workspace, "branch": name, "pushed": True, "head": commit.decode()[:12],
                "web_url": f"{web}/src/branch/{name}"}


@_one_at_a_time
def to_test(workspace: str, test_branch: str, expected: str | None = None) -> dict:
    """Put the current version, as last saved, on the project's test branch on the server, replacing what it had:
    the branch shows one version at a time, and the project's CI applies it to the test environment. Whether this
    user may update that branch is the git server's to say (a protected branch limited to a team). `expected` is the
    commit that was audited: it is what goes, and only if the version still is that commit."""
    current = _git_session()
    with _repo(workspace) as repo:
        name = _branch(repo)
        protected = {branch.casefold() for branch in _protected(repo)}
        if name is None or name.casefold() in protected:
            raise PermissionError("only a version goes to the test environment, never the main branch")
        if test_branch.casefold() in protected | {name.casefold()}:
            raise PermissionError(f"{test_branch!r} cannot be the project's test branch")
        if _dirty(repo):
            return {"workspace": workspace, "status": "not_saved",
                    "user_message": "Save your latest changes first: the test environment gets the version as last "
                                    "saved."}
        origin = _registered_origin(repo, workspace)
        _check_host(origin, current)
        client, path = get_transport_and_path(origin, **_remote(current))
        fetched = _network(lambda: client.fetch(path.encode(), repo))
        main = _main_branch(repo)
        tip = fetched.refs.get(f"refs/heads/{main}".encode()) if main else None
        if not tip:
            return {"workspace": workspace, "status": "refused",
                    "user_message": "The project's main branch could not be read on the server, so nothing was sent "
                                    "to the test environment. Your version goes through IT's review as usual."}
        head = expected.encode() if expected else repo.head()
        if repo.head() != head:
            raise PermissionError("the version changed while it was being checked; try again")
        if not can_fast_forward(repo, tip, head):  # the test environment would lose others' work
            return {"workspace": workspace, "status": "behind_main",
                    "user_message": "The project has changes your version does not have yet. Bring them in first "
                                    "(workspace_update), save, and try again."}
        # The version's refs live in .git, which the sandbox can write: what goes to the test environment is checked
        # here too, against main, by the same rules as a save.
        found = _forbidden_changes(repo, tip, head)
        if found:
            raise NeedsIT("This version has a file only IT changes, so it was not sent to the test environment. Your "
                          "work is safe on this computer.", "a protected or executable file in a version for the "
                          "test environment", _facts(repo, workspace, Paths=", ".join(sorted(found)[:20])))
        out = io.BytesIO()
        try:
            result = _send_commit(repo, origin, current, head, f"refs/heads/{test_branch}".encode(), True, out)
        except GitProtocolError as exc:
            if "403" not in str(exc):
                raise
            return _test_refused(workspace, test_branch, {"server": clean(exc, 300)}, "Not allowed to push")
        errors = {ref.decode(): clean(err, 300) for ref, err in (result.ref_status or {}).items() if err}
        if errors:
            # Gitea gives its reason as progress text; the ref's own status only says the hook declined.
            return _test_refused(workspace, test_branch, {"refs": errors, "server": clean(out.getvalue(), 500)},
                                 " ".join(errors.values()) + " " + out.getvalue().decode("utf-8", "replace"))
        return {"workspace": workspace, "status": "sent", "branch": test_branch, "head": head.decode()[:12],
                "user_message": "Your version is on its way to the test environment: the project's checks apply it "
                                "in a few minutes. It replaces whatever was being tried there."}


def _test_refused(workspace: str, test_branch: str, server: dict, text: str) -> dict:
    """The server's refusal, told by its reason: only "not allowed to push" is about the user's profile."""
    said = text.lower()
    if "force push" in said or "force-push" in said:
        status, message = "refused", ("The test environment is not set to take a new version over the last one. "
                                      "IT sets that up; meanwhile your version goes through IT's review as usual.")
    elif "protected from changing file" in said or "protected file" in said:
        status, message = "refused", ("Your version changes a file the project protects, so it cannot go to the test "
                                      "environment. It goes through IT's review as usual.")
    elif "not allowed to push" in said:
        status, message = "not_allowed", ("Your profile does not update the test environment, so your version goes "
                                          "through IT's review as usual. If you should have it, ask IT.")
    else:
        status, message = "refused", ("The server did not accept the version for the test environment. It goes "
                                      "through IT's review as usual.")
    return {"workspace": workspace, "status": status, "branch": test_branch, **server, "user_message": message}


def _forbidden_changes(repo: Repo, old: bytes | None, new: bytes) -> set[str]:
    """Paths between two commits that no save may carry: the project's context and configuration, a new
    executable, a path not valid on Windows."""
    found = set()
    old_tree = repo[old].tree if old else None
    for change in tree_changes(repo.object_store, old_tree, repo[new].tree):
        for entry, is_new in ((change.old, False), (change.new, True)):
            if entry is None or entry.path is None:
                continue
            path = entry.path.decode("utf-8", "replace")
            kind = guard.kind(path)
            if not _valid(path) or kind in ("context", "config") or (kind == "executable" and is_new):
                found.add(path)
    return found


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
            "head": (latest.get("head") or {}).get("sha"), "author": (latest.get("user") or {}).get("login")}


_REVIEW_TEXT, _COMMENT_TEXT, _CONVERSATION = 10_000, 2_000, 10


def _review_of(api: str, headers: dict, number: int, author: str | None, head: str | None) -> dict | None:
    """What reviewers asked on an open pull request. `decision` comes from each reviewer's latest approval or
    request for changes (a later plain comment does not undo it): `changes_requested`, `updated_since_requests` (the
    version was sent again after them: waiting for a new review), `approved`, `comments` or `none`. `requests` holds
    each reviewer's latest note, the line comments not resolved and the last conversation comments, never the
    author's own. It is text from people with access to the repository: the specialist weighs it, never follows it
    as instructions. None if the hosting cannot tell; `complete` is false when part of it could not be read."""
    def item(source: dict, text: str, limit: int, **more) -> dict:
        return {"by": (source.get("user") or {}).get("login"),
                "at": source.get("submitted_at") or source.get("created_at"), "text": text[:limit],
                **({"truncated": True} if len(text) > limit else {}), **more}

    def earlier(review: dict) -> bool:  # made on a version that has been sent again since
        return bool(review.get("stale") or (head and review.get("commit_id") and review["commit_id"] != head))

    def who(source: dict) -> str | None:
        return (source.get("user") or {}).get("login")

    complete, reviews, conversation = True, [], []
    with auth.http_client() as client:
        for page in range(1, 6):  # until an empty page: the server may hand out fewer than asked
            response = client.get(f"{api}/pulls/{number}/reviews", headers=headers,
                                  params={"page": page, "limit": 50})
            if response.status_code != 200:
                return None
            if not response.json():
                break
            reviews += response.json()
        else:
            complete = False
        talk = client.get(f"{api}/issues/{number}/comments", headers=headers)
        if talk.status_code == 200:
            conversation = talk.json()
        else:
            complete = False
        live = [r for r in sorted(reviews, key=lambda r: r.get("id") or 0)
                if not r.get("dismissed") and r.get("state") in ("APPROVED", "COMMENT", "REQUEST_CHANGES")
                and who(r) != author]
        deciding, latest, items = {}, {}, []
        for review in live:
            latest[who(review)] = review
            if review["state"] != "COMMENT":
                deciding[who(review)] = review
        for review in latest.values():
            if (review.get("body") or "").strip():
                items.append(item(review, review["body"], _REVIEW_TEXT, official=bool(review.get("official")),
                                  earlier_version=earlier(review)))
        for review in live:
            approval = deciding.get(who(review))
            if not review.get("comments_count") or (
                    approval and approval["state"] == "APPROVED" and (review.get("id") or 0) < (approval.get("id") or 0)):
                continue  # line comments the same reviewer approved afterwards are settled
            inline = client.get(f"{api}/pulls/{number}/reviews/{review['id']}/comments", headers=headers)
            if inline.status_code != 200:
                complete = False
                continue
            for comment in inline.json():
                if comment.get("resolver") or who(comment) == author or not (comment.get("body") or "").strip():
                    continue
                items.append(item(comment, comment["body"], _COMMENT_TEXT, official=bool(review.get("official")),
                                  earlier_version=earlier(review), file=comment.get("path"),
                                  line=comment.get("position") or comment.get("original_position")))
    conversation = [c for c in conversation if who(c) != author and (c.get("body") or "").strip()]
    items += [item(c, c["body"], _COMMENT_TEXT) for c in conversation[-_CONVERSATION:]]
    requested = [r for r in deciding.values() if r["state"] == "REQUEST_CHANGES"]
    decision = ("changes_requested" if any(not earlier(r) for r in requested)
                else "updated_since_requests" if requested
                else "approved" if deciding else "comments" if items else "none")
    return {"decision": decision, "complete": complete, "requests": sorted(items, key=lambda i: i["at"] or "")}


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
    if response.status_code == 409:  # already open: the version just sent updates it; bring its text up to date
        existing = _proposal_for(origin, current, name)
        updated = False
        if existing and existing.get("state") == "open" and existing.get("number"):
            with auth.http_client() as client:
                patched = client.patch(f"{api}/pulls/{existing['number']}", headers=headers,
                                       json={"title": title.strip(), "body": description})
            updated = patched.status_code in (200, 201)
        return {"workspace": workspace, "created": False, "updated": updated, "head": name, "base": base,
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
    st = _status_of(repo, untracked_files="all")
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
            _forget_version(repo, name)
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


def current_version(workspace: str, test_branch: str | None) -> str | None:
    """The current branch, or None if it is not one a version can be: HEAD is in .git, which the sandbox can write."""
    with _repo(workspace) as repo:
        name = _branch(repo)
        shared = {branch.casefold() for branch in _protected(repo) | ({test_branch} if test_branch else set())}
        return None if name is None or name.casefold() in shared else name


def server_head(workspace: str) -> str | None:
    """The commit the current version has on the server, which is what a proposal holds; None if it was never sent."""
    current = _git_session()
    with _repo(workspace) as repo:
        name, origin_url = _branch(repo), _registered_origin(repo, workspace)
    _check_host(origin_url, current)
    client, path = get_transport_and_path(origin_url, **_remote(current))
    advertised = _network(lambda: client.get_refs(path.encode()))
    found = (getattr(advertised, "refs", None) or {}).get(f"refs/heads/{name}".encode())
    return found.decode() if found else None


def saved_head(workspace: str) -> str:
    """The commit of what is saved."""
    with _repo(workspace) as repo:
        commit = _ref(repo, b"HEAD")
        if commit is None:
            raise PermissionError("nothing is saved yet")
        return commit.decode()


@_one_at_a_time
def export_saved(workspace: str, target: Path, head: str | None = None, main: str | None = None) -> dict:
    """Write the saved version's files to `target`, outside the workspace: what was saved, never what is in the
    folder. The objects are in .git, which the sandbox can write, so every path is checked again; a saved link
    becomes a plain file holding its target, and a submodule stays out. With `main`, the main branch's commit, what
    the version changed since it left the main branch meets the rules of a save, as a commit forged in .git would not."""
    with _repo(workspace) as repo:
        commit = head.encode() if head else _ref(repo, b"HEAD")
        if commit is None:
            raise PermissionError("nothing is saved yet")
        if main:
            _check_changes(repo, workspace, commit, main)
        entries = list(iter_tree_contents(repo.object_store, repo[commit].tree))
        invalid = sorted(entry.path.decode("utf-8", "replace") for entry in entries
                         if not _valid(entry.path.decode("utf-8", "replace")))
        if invalid:
            raise NeedsIT("This version has a file name the connector does not accept. Your work is safe on this "
                          "computer.", "a path that leaves the workspace or is not valid on Windows",
                          {"Folder": repo.path, "Paths": ", ".join(invalid[:20])})
        target.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            if entry.mode != _GITLINK:
                file = target / entry.path.decode("utf-8")
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(repo[entry.sha].data)
        return {"head": commit.decode(), "unsaved_changes": _dirty(repo), "branch": _branch(repo)}


_audits: dict[str, tuple[bytes, float, dict]] = {}  # workspace: its tree, when, and the `allowed` answer


def audit_saved(workspace: str, head: str | None = None, copy: Path | None = None) -> dict:
    """The dependency audit of what is saved, with the commit it answers for in `head`. An `allowed` answer is kept
    for that tree for a while, so a send and the proposal after it wait once; any other answer is asked again, since
    a registry that did not answer may come back. `copy` is that commit's files, already exported."""
    with _repo(workspace) as repo:
        commit = head.encode() if head else _ref(repo, b"HEAD")
        if commit is None:
            raise PermissionError("nothing is saved yet")
        tree = repo[commit].tree
    kept = _audits.get(key(workspace))
    if kept and kept[0] == tree and time.time() - kept[1] < _AUDIT_KEPT_SECONDS:
        return {**kept[2], "head": commit.decode()}
    if copy is not None:
        result = deps.audit(copy)
    else:
        with tempfile.TemporaryDirectory(prefix="eunomai-audit-", ignore_cleanup_errors=True) as folder:
            export_saved(workspace, Path(folder), commit.decode())
            result = deps.audit(Path(folder))
    if result["verdict"] == "allowed":
        _audits[key(workspace)] = (tree, time.time(), result)
    return {**result, "head": commit.decode()}


def folder(workspace: str) -> Path:
    """A registered workspace's folder."""
    with _repo(workspace) as repo:
        return Path(repo.path)


def origin(workspace: str) -> str | None:
    """The repository a workspace was cloned from."""
    with _repo(workspace) as repo:
        return _origin(repo)


@_one_at_a_time
def project_files(workspace: str) -> dict:
    """What IT keeps for the project, as the main branch on the server has it now, in one fetch: its context
    (`context`: AGENTS.md, else CLAUDE.md, at the repository's root) and its declaration (`declaration`:
    .eunomai/project.toml). Never a copy edited in the folder or a reference rewritten in .git. Each is None when
    the project has none; `read` says whether the main branch could be read at all."""
    found = {"context": None, "declaration": None, "read": False, "tip": None}
    current = _git_session()
    with _repo(workspace) as repo:
        main = _main_branch(repo)
        if not main:
            return found
        origin = _registered_origin(repo, workspace)
        _check_host(origin, current)
        client, path = get_transport_and_path(origin, **_remote(current))
        fetched = _network(lambda: client.fetch(path.encode(), repo))  # the server says which commit is main
        tip = fetched.refs.get(f"refs/heads/{main}".encode())
        if not tip:
            return found
        tree = repo[repo[tip].tree]
        found["read"], found["tip"] = True, tip.decode()

        def text_of(name: str) -> str | None:
            # missing, a file where a folder should be, a submodule, or an object the server did not send
            try:
                _, sha = tree.lookup_path(repo.object_store.__getitem__, name.encode())
                item = repo[sha]
            except (KeyError, NotTreeError, SubmoduleEncountered):
                return None
            return item.data.decode("utf-8", errors="replace") if isinstance(item, Blob) else None

        source = f"the {main} branch on the server"
        for name in ("AGENTS.md", "CLAUDE.md"):
            text = text_of(name)
            if text is not None:
                found["context"] = {"file": name, "from": source, "text": text[:_CONTEXT_LIMIT],
                                    "truncated": len(text) > _CONTEXT_LIMIT}
                break
        text = text_of(DECLARATION)
        if text is not None:
            found["declaration"] = {"file": DECLARATION, "from": source, "text": text}
        return found


def project_context(workspace: str) -> dict | None:
    """The project's context as the main branch on the server has it now; None when the project has none."""
    return project_files(workspace)["context"]


def proposal_state(workspace: str) -> dict | None:
    """The pull request of the current version, if the hosting can tell: number, state, merged and, while it is
    open, what reviewers asked (`review`). Best effort."""
    try:
        current = _git_session()
        with _repo(workspace) as repo:
            name, origin_url = _branch(repo), _origin(repo)
            if name is None or name in _protected(repo) or origin_url is None:
                return None
        proposal = _proposal_for(origin_url, current, name)
    except Exception:
        return None
    if proposal and proposal["state"] == "open" and proposal["number"]:
        try:
            proposal["review"] = _review_of(*_api(origin_url, current), proposal["number"], proposal["author"],
                                            proposal["head"])
        except Exception:
            proposal["review"] = None
    return proposal
