"""IT's command that creates a project from a person's request: the request read in each language, and every step
against a fake Gitea, in its order, with the token kept out of everything it prints."""

import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from eunomai_business import project_request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import new_project  # noqa: E402

TOKEN = "token-that-must-never-be-printed-0123456789"
ENV = '# The application\nAPP_ENVIRONMENT="development"\nAPP_NAME="Our applications"\nAPP_LANGUAGES=["en","es"]\n'
TOML = '[preview.environment]\nAPP_ENVIRONMENT = "development"\nAPP_NAME = "Our applications"\n'


def request_text(language: str = "en", name: str = "asset-inventory", requester: str | None = "ana.it") -> str:
    """A request as the connector writes it, from its own words."""
    fields = {"request": name, "name": name, "requester": requester or "", "created": "2026-11-04T10:00:00+0100",
              "language": language, "purpose": "Track the computers.", "users": "IT.", "today": "A spreadsheet.",
              "first_version": "A list.", "out_of_scope": "", "open_questions": ["Which columns?"]}
    return project_request.message(fields)[1]


# --- the request ----------------------------------------------------------------------------------------------

def test_the_fixed_lines_are_the_ones_the_connector_writes():
    for language, lines in new_project.LINES.items():
        for key, line in lines.items():
            assert project_request.WORDS[language][key] == line, (language, key)
    assert new_project.NAME.pattern == project_request._NAME.pattern
    assert new_project.REQUEST.pattern == project_request._REQUEST.pattern
    assert new_project.LOGIN.pattern == project_request._LOGIN.pattern
    assert set(new_project.REPLY) == set(project_request.WORDS)


@pytest.mark.parametrize("language", ["en", "es", "ca"])
def test_a_request_is_read_in_each_language(language):
    read = new_project.read_request(request_text(language))
    assert (read.name, read.request, read.requester, read.language) == ("asset-inventory", "asset-inventory",
                                                                        "ana.it", language)


def test_a_request_pasted_from_a_mail_program_is_read_too():
    pasted = "\r\n".join(f"  {line}  " for line in request_text("es").splitlines())
    assert new_project.read_request("Asunto: …\r\n\r\n" + pasted).name == "asset-inventory"


def test_it_chooses_the_name_and_the_requester_when_it_must():
    read = new_project.read_request(request_text(requester=None), name="it-assets", requester="ana.it")
    assert (read.name, read.requester) == ("it-assets", "ana.it")


@pytest.mark.parametrize(("text", "name", "requester", "said"), [
    ("Hello, please make me an app", "", "", "not a project request"),
    (request_text(requester=None), "", "", "names no valid git user"),
    (request_text(), "Not A Name", "", "not a plain name"),
    (request_text(), "con", "", "not a plain name"),
    (request_text(), "", "a b", "names no valid git user"),
    (request_text().replace("Request: asset-inventory", "Request: ../x"), "", "", "no valid 'Request:' line"),
])
def test_what_cannot_make_a_project_is_refused_with_what_to_do(text, name, requester, said):
    with pytest.raises(new_project.Refused, match=said):
        new_project.read_request(text, name, requester)


# --- a fake Gitea ------------------------------------------------------------------------------------------------

class FakeGitea:
    """Enough of Gitea's API for the tool, and a record of what was asked, in order."""

    def __init__(self, change_files: bool = True):
        self.calls: list[tuple[str, str]] = []
        self.headers: list[str] = []
        self.repos = {"acme/template": {"template": True, "default_branch": "main"}}
        self.files: dict[str, dict[str, str]] = {}
        self.protected: set[str] = set()
        self.collaborators: dict[str, dict[str, str]] = {}
        self.change_files = change_files
        self.fail: str = ""

    def answer(self, method: str, path: str, body: dict | None) -> tuple[int, object]:
        self.calls.append((method, path))
        if self.fail and self.fail in f"{method} {path}":
            return 500, {"message": "it broke"}
        parts = [unquote(part) for part in path.split("?")[0].split("/") if part]
        if parts[:2] != ["api", "v1"] or parts[2] != "repos":
            return 404, None
        repo = f"{parts[3]}/{parts[4]}"
        rest = parts[5:]
        if method == "GET" and not rest:
            return (200, self.repos[repo]) if repo in self.repos else (404, {"message": "not found"})
        if method == "POST" and rest == ["generate"]:
            target = f"{body['owner']}/{body['name']}"
            if target in self.repos:
                return 409, {"message": "exists"}
            self.repos[target] = {"template": False, "default_branch": "main", "has_actions": True}
            self.files[target] = {".env.example": ENV, ".eunomai/project.toml": TOML}
            return 201, {"full_name": target, "default_branch": "main"}
        if rest[:1] == ["contents"]:
            path_in_repo = "/".join(rest[1:])
            files = self.files[repo]
            if method == "GET":
                text = files[path_in_repo]
                return 200, {"content": base64.b64encode(text.encode()).decode(), "sha": f"sha-{len(text)}"}
            if method == "POST" and not path_in_repo:
                if not self.change_files:
                    return 404, None
                for change in body["files"]:
                    files[change["path"]] = base64.b64decode(change["content"]).decode()
                return 201, {"commit": {}}
            if method == "PUT":
                files[path_in_repo] = base64.b64decode(body["content"]).decode()
                return 201, {"commit": {}}
        if method == "POST" and rest == ["branch_protections"]:
            self.protected.add(f"{repo}:{body['rule_name']}")
            return 201, {"rule_name": body["rule_name"], **body}
        if rest[:1] == ["collaborators"]:
            if method == "PUT":
                self.collaborators.setdefault(repo, {})[rest[1]] = body["permission"]
                return 204, None
            if method == "GET" and rest[2:] == ["permission"]:
                return 200, {"permission": self.collaborators.get(repo, {}).get(rest[1], "none")}
        if rest[:1] == ["branches"] and method == "GET":
            return 200, {"name": rest[1], "protected": f"{repo}:{rest[1]}" in self.protected}
        if method == "PATCH" and not rest:
            self.repos[repo].update(body)
            return 200, self.repos[repo]
        return 404, None


@pytest.fixture
def gitea(tmp_path):
    fake = FakeGitea()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def _handle(self):
            fake.headers.append(self.headers.get("Authorization", ""))
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, answer = fake.answer(self.command, self.path, body)
            raw = json.dumps(answer).encode() if answer is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = do_PUT = do_PATCH = _handle

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    header = tmp_path / "header"
    header.write_text(f"Authorization: token {TOKEN}\n", encoding="utf-8")
    config = tmp_path / "new_project.local.json"
    config.write_text(json.dumps({"server": f"http://127.0.0.1:{server.server_port}", "owner": "acme",
                                  "template": "template", "header_file": "header", "actions": False}),
                      encoding="utf-8")
    fake.config = config
    yield fake
    server.shutdown()


def run(fake: FakeGitea, tmp_path: Path, capsys, *extra: str, language: str = "es", requester: str | None = "ana.it"):
    request = tmp_path / "request.txt"
    request.write_text(request_text(language, requester=requester), encoding="utf-8")
    code = new_project.main(["--request", str(request), "--title", "Asset inventory", "--config", str(fake.config),
                             *extra])
    out, err = capsys.readouterr()
    return code, out, err


# --- against the fake Gitea ------------------------------------------------------------------------------------

def test_the_whole_project_is_made_in_its_order_and_the_reply_is_in_the_requests_language(gitea, tmp_path, capsys):
    code, out, err = run(gitea, tmp_path, capsys)
    assert code == 0, err
    target = "acme/asset-inventory"
    assert 'APP_NAME="Asset inventory"' in gitea.files[target][".env.example"]
    assert 'APP_NAME = "Asset inventory"' in gitea.files[target][".eunomai/project.toml"]
    assert 'APP_LANGUAGES=["en","es"]' in gitea.files[target][".env.example"], "nothing else of the file changes"
    assert f"{target}:main" in gitea.protected
    assert gitea.collaborators[target] == {"ana.it": "write"}
    assert gitea.repos[target]["has_actions"] is False
    steps = [f"{method} {path.split('?')[0]}" for method, path in gitea.calls]
    named = steps.index(f"POST /api/v1/repos/{target}/contents")
    assert steps.index("POST /api/v1/repos/acme/template/generate") < named
    assert named < steps.index(f"POST /api/v1/repos/{target}/branch_protections"), "the name goes in before main is shut"
    assert "Tu proyecto ya existe: acme/asset-inventory" in out and "IT ya ha creado el proyecto" in out
    assert all(header == f"token {TOKEN}" for header in gitea.headers)


def test_the_token_is_never_printed(gitea, tmp_path, capsys):
    for extra in ((), ("--dry-run",)):
        gitea.repos.pop("acme/asset-inventory", None)
        _, out, err = run(gitea, tmp_path, capsys, *extra)
        assert TOKEN not in out + err


def test_a_dry_run_checks_and_changes_nothing(gitea, tmp_path, capsys):
    code, out, _ = run(gitea, tmp_path, capsys, "--dry-run")
    assert code == 0 and "Nothing was changed" in out
    assert "acme/asset-inventory" not in gitea.repos
    assert all(method == "GET" for method, _ in gitea.calls)


def test_an_existing_repository_stops_everything_before_any_change(gitea, tmp_path, capsys):
    gitea.repos["acme/asset-inventory"] = {"template": False}
    code, _, err = run(gitea, tmp_path, capsys)
    assert code == 1 and "exists already: nothing was changed" in err
    assert all(method == "GET" for method, _ in gitea.calls)


def test_a_repository_that_is_not_a_template_is_refused(gitea, tmp_path, capsys):
    gitea.repos["acme/template"]["template"] = False
    code, _, err = run(gitea, tmp_path, capsys)
    assert code == 1 and "not marked as a template" in err and "acme/asset-inventory" not in gitea.repos


def test_an_older_gitea_gets_one_commit_per_file(tmp_path, capsys, gitea):
    gitea.change_files = False
    code, _, err = run(gitea, tmp_path, capsys)
    assert code == 0, err
    assert sum(1 for method, path in gitea.calls if method == "PUT" and "/contents/" in path) == 2
    assert 'APP_NAME = "Asset inventory"' in gitea.files["acme/asset-inventory"][".eunomai/project.toml"]


def test_a_failure_after_creating_says_what_was_done_and_deletes_nothing(gitea, tmp_path, capsys):
    gitea.fail = "branch_protections"
    code, _, err = run(gitea, tmp_path, capsys)
    assert code == 1
    assert "created acme/asset-inventory" in err and "committed the application's name" in err
    assert "could not be protected" in err and "stays as it is" in err
    assert "acme/asset-inventory" in gitea.repos
    assert not any(method == "DELETE" for method, _ in gitea.calls)


def test_a_template_without_the_name_line_is_refused_rather_than_guessed(gitea, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "ENV", "APP_ENVIRONMENT=development\n")
    code, _, err = run(gitea, tmp_path, capsys)
    assert code == 1 and "no single APP_NAME line" in err


@pytest.mark.parametrize(("change", "said"), [
    ({"server": "http://git.example.org"}, "must be https"),
    ({"owner": ""}, "owner is required"),
    ({"surprise": 1}, "unknown keys"),
    ({"protection": {"required_approvals": "one"}}, "protection takes"),
])
def test_a_configuration_that_cannot_work_is_refused(gitea, tmp_path, capsys, change, said):
    settings = {**json.loads(gitea.config.read_text(encoding="utf-8")), **change}
    gitea.config.write_text(json.dumps(settings), encoding="utf-8")
    code, _, err = run(gitea, tmp_path, capsys)
    assert code == 1 and said in err and not gitea.calls


def test_the_example_configuration_reads(tmp_path):
    example = (ROOT / "new_project.example.json").read_text(encoding="utf-8")
    (tmp_path / "new_project.local.json").write_text(example, encoding="utf-8")
    config = new_project.read_config(tmp_path / "new_project.local.json")
    assert config.protection == new_project.PROTECTION and config.ca_file is None
    assert urlsplit(config.server).scheme == "https"
