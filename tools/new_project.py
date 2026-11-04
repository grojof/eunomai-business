"""Create a project from a person's request, as IT: one command, always the same steps, nothing to program.

    python tools/new_project.py --request request.txt --title "Asset inventory"
    python tools/new_project.py --request - --title "Asset inventory" --dry-run      # the e-mail pasted on stdin

The request is the e-mail a person sent through the assistant, pasted as it arrived. Its fixed lines give the
proposed name, the request and the requester's git user, in the organization's documentation language. The tool:

1. checks the template exists and is a template, and that no repository has that name;
2. creates the repository from the template (private, with its labels);
3. commits the application's name into `.env.example` and `.eunomai/project.toml`, before anything is protected;
4. protects the main branch: changes only by a reviewed pull request, up to date, no rejected review;
5. gives the requester write access, and turns Actions off when the server has no runner (`actions: false`);
6. checks all of it, and prints the reply for the requester.

The configuration (`new_project.local.json`, git-ignored; `new_project.example.json` shows it) names the server, the
owner, the template and a file holding the `Authorization` header, which is read and never printed. Standard library
only, so IT needs nothing but Python. Gitea only, for now.
"""

import argparse
import base64
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "new_project.local.json"
# As connector/src/eunomai_business/project_request.py checks them; a test keeps both in step.
NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")
REQUEST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,70}[a-z0-9])?\Z")
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,99}\Z")
WINDOWS_RESERVED = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])\Z")
TITLE = re.compile(r"[^\"\\\r\n\x00-\x1f]{1,60}\Z")
# The request's fixed lines, as project_request.WORDS writes them; a test keeps both in step.
LINES = {
    "en": {"name": "Proposed name: {name} (a suggestion: IT decides the name)", "request": "Request: {request}",
           "requester": "Requester's git user: {login}"},
    "es": {"name": "Nombre propuesto: {name} (una sugerencia: el nombre lo decide IT)", "request": "Solicitud: {request}",
           "requester": "Usuario de git de quien lo solicita: {login}"},
    "ca": {"name": "Nom proposat: {name} (un suggeriment: el nom el decideix IT)", "request": "Sol·licitud: {request}",
           "requester": "Usuari de git de qui ho sol·licita: {login}"},
}
REPLY = {
    "en": "Your project exists: {address}. Tell the assistant \"IT has created the project: {address}\", and the work "
          "carries on from your request.",
    "es": "Tu proyecto ya existe: {address}. Dile al asistente «IT ya ha creado el proyecto: {address}», y el trabajo "
          "sigue a partir de tu solicitud.",
    "ca": "El teu projecte ja existeix: {address}. Digues a l'assistent «IT ja ha creat el projecte: {address}», i la "
          "feina continua a partir de la teva sol·licitud.",
}
FILES = {".env.example": re.compile(r'^APP_NAME="[^"\n]*"$', re.M),
         ".eunomai/project.toml": re.compile(r'^APP_NAME = "[^"\n]*"$', re.M)}
PROTECTION = {"enable_push": False, "required_approvals": 1, "block_on_outdated_branch": True,
              "block_on_rejected_reviews": True, "dismiss_stale_approvals": True}
CONFIG_KEYS = {"server", "owner", "template", "header_file", "actions", "protection", "ca_file"}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class Refused(Exception):
    """Something to fix before anything is changed, or a step that failed, said in words IT can act on."""


@dataclass
class Request:
    name: str
    request: str
    requester: str
    language: str


@dataclass
class Config:
    server: str
    owner: str
    template: str
    header_file: Path
    actions: bool = True
    protection: dict = field(default_factory=lambda: dict(PROTECTION))
    ca_file: Path | None = None


def _pattern(line: str) -> re.Pattern:
    """A fixed line as a pattern: the words exact, each placeholder one value with no spaces."""
    parts = re.split(r"\{(\w+)\}", line)
    pattern = "".join(re.escape(part) if index % 2 == 0 else rf"(?P<{part}>\S+)" for index, part in enumerate(parts))
    return re.compile(rf"^\s*{pattern}\s*$", re.M)


def read_request(text: str, name: str = "", requester: str = "") -> Request:
    """The request's name, id and requester, from its fixed lines in whichever language it is written. `name` and
    `requester` are IT's: they replace what the request says."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for language, lines in LINES.items():
        found = {key: _pattern(line).search(text) for key, line in lines.items()}
        if found["name"] or found["request"]:
            break
    else:
        raise Refused("this is not a project request: none of its fixed lines (Proposed name, Request, Requester's "
                      "git user) is there. Paste the whole e-mail as it arrived")
    values = {"name": found["name"]["name"] if found["name"] else "",
              "request": found["request"]["request"] if found["request"] else "",
              "requester": found["requester"]["login"] if found["requester"] else ""}
    chosen = name or values["name"]
    if not chosen or not NAME.match(chosen) or WINDOWS_RESERVED.match(chosen) or chosen.endswith(("-git", "-wiki")):
        raise Refused(f"the repository name {chosen!r} is not a plain name: 1 to 64 lowercase letters, digits and "
                      "hyphens, starting and ending with a letter or digit; give one with --name")
    if not values["request"] or not REQUEST.match(values["request"]):
        raise Refused("the request has no valid 'Request:' line: paste the whole e-mail as it arrived")
    login = requester or values["requester"]
    if not login or not LOGIN.match(login):
        raise Refused("the request names no valid git user for the requester (they were not signed in when it was "
                      "prepared): ask them for it and give it with --requester")
    return Request(chosen, values["request"], login, language)


def read_config(path: Path) -> Config:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"no configuration at {path}: copy new_project.example.json there and fill it in") from None
    except json.JSONDecodeError as error:
        raise Refused(f"{path} is not valid JSON: {error}") from None
    values = {key: value for key, value in raw.items() if not key.startswith("_")}
    unknown = sorted(set(values) - CONFIG_KEYS)
    if unknown:
        raise Refused(f"{path.name}: unknown keys {', '.join(unknown)}; it takes {', '.join(sorted(CONFIG_KEYS))}")
    for key in ("server", "owner", "template", "header_file"):
        if not isinstance(values.get(key), str) or not values[key].strip():
            raise Refused(f"{path.name}: {key} is required")
    server = urllib.parse.urlsplit(values["server"].rstrip("/"))
    if server.scheme != "https" and not (server.scheme == "http" and server.hostname in LOOPBACK):
        raise Refused(f"{path.name}: server must be https://…: the token must never travel in clear")
    protection = {**PROTECTION, **(values.get("protection") or {})}
    if set(protection) != set(PROTECTION) or not isinstance(protection["required_approvals"], int):
        raise Refused(f"{path.name}: protection takes {', '.join(sorted(PROTECTION))}")
    if not isinstance(values.get("actions", True), bool):
        raise Refused(f"{path.name}: actions is true or false")
    base = path.parent
    ca_file = values.get("ca_file") or None
    return Config(server=values["server"].rstrip("/"), owner=values["owner"], template=values["template"],
                  header_file=(base / Path(values["header_file"]).expanduser()).resolve(),
                  actions=values.get("actions", True), protection=protection,
                  ca_file=(base / Path(ca_file).expanduser()).resolve() if ca_file else None)


class Gitea:
    """Calls to Gitea's API. The header file's value goes only into requests, never into an error or a message."""

    def __init__(self, config: Config):
        try:
            line = config.header_file.read_text(encoding="utf-8").strip()
        except OSError:
            raise Refused(f"the header file {config.header_file} cannot be read") from None
        header, separator, value = line.partition(":")
        if not separator or not value.strip() or "\n" in line:
            raise Refused(f"the header file {config.header_file} holds one line: 'Authorization: token …'")
        self.header = (header.strip(), value.strip())
        self.api = f"{config.server}/api/v1"
        self.context = ssl.create_default_context(cafile=str(config.ca_file) if config.ca_file else None)

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"{self.api}{path}", data=data, method=method)
        request.add_header(*self.header)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=60) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                answer = json.loads(raw) if raw.strip() else None
            except json.JSONDecodeError:
                answer = None
            return error.code, answer
        except urllib.error.URLError as error:
            raise Refused(f"the server does not answer at {self.api}: {error.reason}") from None


def _message(answer: object) -> str:
    return str(answer.get("message", "")) if isinstance(answer, dict) else ""


def check(gitea: Gitea, config: Config, request: Request) -> None:
    """What must hold before anything is created. Changes nothing."""
    status, template = gitea.call("GET", f"/repos/{config.owner}/{config.template}")
    if status != 200 or not isinstance(template, dict):
        raise Refused(f"the template {config.owner}/{config.template} cannot be read ({status}): check the "
                      "configuration and the token's access")
    if not template.get("template"):
        raise Refused(f"{config.owner}/{config.template} is not marked as a template in its settings")
    status, _ = gitea.call("GET", f"/repos/{config.owner}/{request.name}")
    if status == 200:
        raise Refused(f"{config.owner}/{request.name} exists already: nothing was changed. Choose another name with "
                      "--name")
    if status != 404:
        raise Refused(f"whether {config.owner}/{request.name} exists cannot be told ({status})")


def named(text: str, path: str, title: str) -> str:
    """The file with the application's name in its one APP_NAME line; refused rather than guessed when there is none."""
    pattern = FILES[path]
    if len(pattern.findall(text)) != 1:
        raise Refused(f"{path} in the template has no single APP_NAME line to set: the template is not what this "
                      "tool expects")
    line = f'APP_NAME="{title}"' if path == ".env.example" else f'APP_NAME = "{title}"'
    return pattern.sub(lambda _: line, text, count=1)


def create(gitea: Gitea, config: Config, request: Request, title: str, done: list[str]) -> str:
    """Every step, each said in `done` once it holds. Gives back the main branch's name."""
    owner, name = config.owner, request.name
    status, made = gitea.call("POST", f"/repos/{owner}/{config.template}/generate", {
        "owner": owner, "name": name, "private": True, "git_content": True, "labels": True,
        "description": f"{title} (request {request.request})"})
    if status != 201 or not isinstance(made, dict):
        raise Refused(f"the repository could not be created ({status}) {_message(made)}".strip())
    done.append(f"created {owner}/{name} from {owner}/{config.template}")
    branch = str(made.get("default_branch") or "main")

    changes = []
    for path in FILES:
        status, current = gitea.call("GET", f"/repos/{owner}/{name}/contents/{urllib.parse.quote(path)}"
                                            f"?ref={urllib.parse.quote(branch)}")
        if status != 200 or not isinstance(current, dict):
            raise Refused(f"{path} cannot be read in the new repository ({status})")
        text = base64.b64decode(current["content"]).decode("utf-8")
        changes.append({"operation": "update", "path": path, "sha": current["sha"],
                        "content": base64.b64encode(named(text, path, title).encode("utf-8")).decode("ascii")})
    message = f"The application's name: {title}"
    status, answer = gitea.call("POST", f"/repos/{owner}/{name}/contents",
                                {"branch": branch, "message": message, "files": changes})
    if status in (404, 405):  # a Gitea before 1.20 has no change-files endpoint: one commit per file
        for change in changes:
            status, answer = gitea.call("PUT", f"/repos/{owner}/{name}/contents/{urllib.parse.quote(change['path'])}",
                                        {"branch": branch, "message": message, "sha": change["sha"],
                                         "content": change["content"]})
            if status not in (200, 201):
                break
    if status not in (200, 201):
        raise Refused(f"the application's name could not be committed ({status}) {_message(answer)}".strip())
    done.append(f"committed the application's name, {title!r}, into {' and '.join(FILES)}")

    status, answer = gitea.call("POST", f"/repos/{owner}/{name}/branch_protections",
                                {"rule_name": branch, **config.protection})
    if status not in (200, 201):
        raise Refused(f"{branch} could not be protected ({status}) {_message(answer)}".strip())
    done.append(f"protected {branch}: changes by a reviewed pull request ({config.protection['required_approvals']} "
                "approval), up to date with it, blocked by a rejected review")

    status, answer = gitea.call("PUT", f"/repos/{owner}/{name}/collaborators/{request.requester}",
                                {"permission": "write"})
    if status not in (200, 204):
        raise Refused(f"{request.requester} could not be given write access ({status}) {_message(answer)}".strip())
    done.append(f"gave {request.requester} write access")

    if not config.actions:
        status, answer = gitea.call("PATCH", f"/repos/{owner}/{name}", {"has_actions": False})
        if status != 200:
            raise Refused(f"Actions could not be turned off ({status}) {_message(answer)}".strip())
        done.append("turned Actions off (this server has no runner)")
    return branch


def verify(gitea: Gitea, config: Config, request: Request, title: str, branch: str) -> list[str]:
    """What is wrong in the new repository, read back from the server; empty when all holds."""
    owner, name, wrong = config.owner, request.name, []
    status, answer = gitea.call("GET", f"/repos/{owner}/{name}/branches/{urllib.parse.quote(branch)}")
    if status != 200 or not isinstance(answer, dict) or not answer.get("protected"):
        wrong.append(f"{branch} is not protected")
    status, answer = gitea.call("GET", f"/repos/{owner}/{name}/collaborators/{request.requester}/permission")
    if status != 200 or not isinstance(answer, dict) or answer.get("permission") not in ("write", "admin", "owner"):
        wrong.append(f"{request.requester} has no write access")
    for path in FILES:
        status, answer = gitea.call("GET", f"/repos/{owner}/{name}/contents/{urllib.parse.quote(path)}"
                                           f"?ref={urllib.parse.quote(branch)}")
        text = base64.b64decode(answer["content"]).decode("utf-8") if status == 200 and isinstance(answer, dict) \
            else ""
        if f'"{title}"' not in text:
            wrong.append(f"{path} does not hold the application's name")
    return wrong


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a project from a person's request, as IT.")
    parser.add_argument("--request", required=True, help="a file with the request e-mail as it arrived, or - for stdin")
    parser.add_argument("--title", required=True, help="the application's name people see, up to 60 characters")
    parser.add_argument("--name", default="", help="the repository's name, instead of the request's proposal")
    parser.add_argument("--requester", default="", help="the requester's git user, when the request names none")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="the configuration file")
    parser.add_argument("--dry-run", action="store_true", help="check everything and change nothing")
    args = parser.parse_args(arguments)
    done: list[str] = []
    try:
        if not TITLE.match(args.title.strip()) or args.title != args.title.strip():
            raise Refused("--title is 1 to 60 characters, with no quotes, backslashes or line breaks")
        text = sys.stdin.read() if args.request == "-" else Path(args.request).read_text(encoding="utf-8")
        request = read_request(text, args.name, args.requester)
        config = read_config(args.config)
        gitea = Gitea(config)
        check(gitea, config, request)
        address = f"{config.owner}/{request.name}"
        if args.dry_run:
            print(f"Dry run: {address} can be created from {config.owner}/{config.template} for {request.requester} "
                  f"(request {request.request}, {request.language}). Nothing was changed.")
            return 0
        branch = create(gitea, config, request, args.title, done)
        wrong = verify(gitea, config, request, args.title, branch)
    except Refused as error:
        if done:
            print("Done so far:\n" + "\n".join(f"- {step}" for step in done), file=sys.stderr)
            print(f"Stopped: {error}. The repository stays as it is; finish the rest by hand or ask for help.",
                  file=sys.stderr)
        else:
            print(f"Nothing was changed: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Nothing was changed: the request cannot be read ({error.strerror or error})", file=sys.stderr)
        return 1
    print("\n".join(f"- {step}" for step in done))
    if wrong:
        print("Check by hand, the server does not show it: " + "; ".join(wrong), file=sys.stderr)
        return 1
    print(f"\n{address} is ready. Reply to the requester:\n\n{REPLY[request.language].format(address=address)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
