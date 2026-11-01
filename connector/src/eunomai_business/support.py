"""What the user sees when something technical goes wrong, and what IT receives.

Business users never resolve technical problems. Either the connector resolves a situation safely on its own, or
it stops, keeps the user's work, and returns three things: a sentence the user understands, a report for IT, and
(when the organization set a support address) an e-mail link with that report already written.
"""

import os
import platform
import re
import socket
import time
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import quote

import httpx
import urllib3

# Mistakes in how a tool was called: Claude fixes the call. A server that cannot be reached is the user's network.
# Anything else unexpected goes to IT, never to the user.
_FOR_CLAUDE = (ValueError, FileExistsError, FileNotFoundError, PermissionError)
_NETWORK = (httpx.TransportError, urllib3.exceptions.HTTPError, ConnectionError, TimeoutError, socket.gaierror)


class NeedsIT(Exception):
    """A situation the connector must not resolve on its own."""

    def __init__(self, user_message: str, problem: str, details: dict | None = None):
        super().__init__(problem)
        self.user_message = user_message
        self.problem = problem
        self.details = details or {}


class Unreachable(Exception):
    """The server could not be reached; nothing for IT yet, unless it names an address only IT can open."""

    def __init__(self, address: str = ""):
        super().__init__(address)
        self.address = address


def _connector_version() -> str:
    try:
        return version("eunomai-business")
    except PackageNotFoundError:
        return "unknown"


def clean(text: object, limit: int = 500) -> str:
    """Text from servers or the system, made safe to show and to mail: no control characters, bounded length."""
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(text))[:limit]


def report(error: NeedsIT) -> dict:
    lines = [f"Problem: {error.problem}", ""]
    lines += [f"{key}: {clean(value)}" for key, value in error.details.items()]
    build = os.environ.get("EUNOMAI_BUILD", "").strip()
    lines += ["", f"Connector: eunomai-business {_connector_version()}" + (f" (build {build})" if build else ""),
              f"Computer: {platform.platform()}",
              f"Time: {time.strftime('%Y-%m-%d %H:%M:%S %z')}"]
    text = "\n".join(lines)
    result = {"status": "needs_it", "user_message": error.user_message, "it_report": text}
    address = os.environ.get("EUNOMAI_SUPPORT_EMAIL", "").strip()
    if address:
        subject = f"eunomai-business: {error.problem}"
        result["email_link"] = f"mailto:{address}?subject={quote(subject)}&body={quote(text)}"
    return result


def unreachable() -> dict:
    return {"status": "unreachable",
            "user_message": "The server could not be reached. Check the network or VPN and try again; your work "
                            "is safe on this computer."}


def audit_unavailable(workspace: str, user_message: str, error: Unreachable) -> dict:
    """The audit could not run. A passing failure asks to try again; an address that stays closed is IT's to open."""
    answer = {"status": "audit_unavailable", "workspace": workspace, "user_message": user_message}
    if error.address:
        answer = {**report(NeedsIT(user_message, f"the audit could not reach {error.address}", {
            "Workspace": workspace, "Cannot reach": error.address,
            "What IT can do": f"Allow {error.address} through the proxy."})), **answer}
    return answer


def safe(call, *args) -> dict:
    """A tool's answer, whatever happens in `call`."""
    try:
        return call(*args)
    except NeedsIT as exc:
        return report(exc)
    except Unreachable:
        return unreachable()
    except _FOR_CLAUDE as exc:
        return {"error": clean(f"{type(exc).__name__}: {exc}", 300)}
    except _NETWORK:
        return unreachable()
    except Exception as exc:
        return report(NeedsIT("Something unexpected happened. Your work is safe on this computer.",
                              "unexpected error in the connector",
                              {"Tool": getattr(call, "__name__", "?"), "Error": f"{type(exc).__name__}: {exc}"[:500]}))
