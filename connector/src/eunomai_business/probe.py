"""Where the connector runs and what it can reach."""

import getpass
import os
import platform
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit

import httpx
import truststore

# Environment variables whose values are safe and useful to report; any other is reported by name only.
_REPORTED_VALUES = ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "EUNOMAI_EXPANSION_PROBE")


def environment() -> dict:
    expansion = os.environ.get("EUNOMAI_EXPANSION_PROBE")
    return {
        "host": socket.gethostname(),
        "os": platform.platform(),
        "user": getpass.getuser(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "expansion_probe": expansion,
        "expansion_ok": bool(expansion) and "${" not in expansion,
        "env_values": {k: os.environ.get(k) for k in _REPORTED_VALUES},
        "env_names": sorted(k for k in os.environ if k.startswith(("CLAUDE", "COWORK", "MCP", "EUNOMAI"))),
        "path_has_uv_bin": any(p.rstrip("\\/").endswith(os.path.join(".local", "bin")) for p in
                               os.environ.get("PATH", "").split(os.pathsep)),
    }


def _try_get(url: str, verify) -> dict:
    start = time.monotonic()
    try:
        response = httpx.get(url, verify=verify, timeout=8, follow_redirects=False)
        return {"ok": True, "status": response.status_code, "ms": round((time.monotonic() - start) * 1000)}
    except Exception as exc:  # the error itself is the measurement
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def reach(url: str) -> dict:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return {"error": "url must be http(s)://host/..."}
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443)})
    except OSError as exc:
        addresses = f"DNS failed: {exc}"
    return {
        "url": url,
        "resolves_to": addresses,
        "system_store": _try_get(url, truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)),
        "bundled_store": _try_get(url, True),
    }
