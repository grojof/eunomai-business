"""What the user sees when something technical goes wrong, and what IT receives.

Business users never resolve technical problems. Either the connector resolves a situation safely on its own, or
it stops, keeps the user's work, and returns three things: a sentence the user understands, a report for IT, and
(when the organization set a support address) an e-mail link with that report already written.
"""

import os
import platform
import re
import time
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import quote


class NeedsIT(Exception):
    """A situation the connector must not resolve on its own."""

    def __init__(self, user_message: str, problem: str, details: dict | None = None):
        super().__init__(problem)
        self.user_message = user_message
        self.problem = problem
        self.details = details or {}


class Unreachable(Exception):
    """The server could not be reached; nothing for IT yet."""


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
