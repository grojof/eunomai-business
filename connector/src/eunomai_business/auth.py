"""Sign-in from the connector: authorization code + PKCE, system browser, loopback redirect.

Several identity providers can be configured at once (for example the organization's directory for the
applications and the git server for versions). Each one is a public client: no secret, no certificate.
Tokens are kept in the per-user secret store (see store.py) and never returned to the model.

Configuration: EUNOMAI_PROVIDERS, a JSON object {name: {authorize_url, token_url, client_id, scopes,
redirect_uri, userinfo_url, login_field}}, set by the plugin.
"""

import base64
import hashlib
import json
import os
import secrets
import socket
import ssl
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import truststore

from . import store

_FLOW_TIMEOUT = 300  # seconds the loopback listener waits for the browser
_REQUIRED = ("authorize_url", "token_url", "client_id", "redirect_uri", "userinfo_url")
_LOOPBACK = ("127.0.0.1", "localhost")

_lock = threading.Lock()
_flows: dict[str, dict] = {}


def providers() -> dict:
    raw = os.environ.get("EUNOMAI_PROVIDERS", "")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"EUNOMAI_PROVIDERS is not valid JSON: {exc}") from exc


def check_url(url: str) -> None:
    """Tokens travel only over HTTPS; plain HTTP is accepted for this computer only (tests)."""
    parts = urlsplit(url)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in _LOOPBACK):
        raise ValueError(f"{parts.scheme}://{parts.netloc} is not HTTPS; tokens are never sent in clear text")


def _config(provider: str) -> dict:
    configured = providers()
    if provider not in configured:
        raise ValueError(f"unknown provider {provider!r}; configured: {', '.join(configured) or 'none'}")
    cfg = {"scopes": "", "login_field": "login", **configured[provider]}
    missing = [k for k in _REQUIRED if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"provider {provider!r} not configured: missing {', '.join(missing)}")
    for key in ("authorize_url", "token_url", "userinfo_url"):
        check_url(cfg[key])
    redirect = urlsplit(cfg["redirect_uri"])
    if redirect.scheme != "http" or redirect.hostname not in _LOOPBACK or not redirect.port:
        raise RuntimeError("redirect_uri must be http://127.0.0.1:<port>/... or http://localhost:<port>/...")
    cfg["port"] = redirect.port
    cfg["store_key"] = f"{provider}:{cfg['client_id']}"  # one record per provider
    return cfg


def http_client() -> httpx.Client:
    """HTTP client that trusts the operating system's certificate store (internal CAs included)."""
    return httpx.Client(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=15)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# --- token store ------------------------------------------------------------------------------------------

def _save(cfg: dict, tokens: dict) -> int:
    previous = store.load(cfg["store_key"]) or {}
    record = {
        "access_token": tokens["access_token"],
        # Some providers do not rotate the refresh token: keep the previous one then.
        "refresh_token": tokens.get("refresh_token") or previous.get("refresh_token"),
        "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
        "obtained_at": time.time(),
    }
    return store.save(cfg["store_key"], record)


def sign_out(provider: str) -> dict:
    cfg = _config(provider)
    with _lock:
        _flows.pop(provider, None)
    if store.delete(cfg["store_key"]):
        return {"provider": provider, "signed_out": True}
    return {"provider": provider, "signed_out": False, "reason": "no stored sign-in"}


# --- interactive flow -------------------------------------------------------------------------------------

def _exchange(cfg: dict, data: dict) -> dict:
    form = {**data, "client_id": cfg["client_id"]}
    if cfg["scopes"]:
        form["scope"] = cfg["scopes"]
    with http_client() as client:
        response = client.post(cfg["token_url"], data=form, headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise RuntimeError(f"token endpoint answered {response.status_code}: {response.text[:300]}")
    return response.json()


def _listeners(port: int) -> list[HTTPServer]:
    """Listen on the IPv4 and, when available, the IPv6 loopback: browsers may resolve localhost to ::1."""

    class _V6(HTTPServer):
        address_family = socket.AF_INET6

    servers = [HTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)]
    try:
        servers.append(_V6(("::1", port), BaseHTTPRequestHandler))
    except OSError:
        pass
    return servers


def _listen(provider: str, cfg: dict, servers: list[HTTPServer], state: str, verifier: str) -> None:
    received: dict = {}

    class Callback(BaseHTTPRequestHandler):
        timeout = 5  # a connection that sends nothing cannot hold the port

        def do_GET(self):  # noqa: N802 (stdlib name)
            query = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
            if query.get("state") != state:  # not this sign-in's answer (favicon, another page): keep waiting
                self.send_response(404)
                self.end_headers()
                return
            received.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<p>Sign-in received. You can close this window and go back to Claude.</p>")

        def log_message(self, *args):  # keep stdout clean: it is the MCP channel
            pass

    for server in servers:
        server.RequestHandlerClass = Callback
        server.timeout = 0.5
    deadline = time.time() + _FLOW_TIMEOUT
    try:
        while not received and time.time() < deadline:
            for server in servers:
                server.handle_request()
                if received:
                    break
    finally:
        for server in servers:
            server.server_close()

    def finish(**fields):
        with _lock:
            _flows[provider].update(fields)

    if not received:
        return finish(status="expired", error="no answer from the browser in time")
    if "error" in received:
        return finish(status="failed", error=(received.get("error_description") or received["error"])[:300])
    try:
        tokens = _exchange(cfg, {"grant_type": "authorization_code", "code": received["code"],
                                 "redirect_uri": cfg["redirect_uri"], "code_verifier": verifier})
        stored_bytes = _save(cfg, tokens)
        login = str(_userinfo(cfg, tokens["access_token"]).get(cfg["login_field"], "?"))
        finish(status="signed_in", login=login, error=None, stored_bytes=stored_bytes,
               token_bytes={k: len(str(tokens.get(k) or "")) for k in ("access_token", "refresh_token")})
    except Exception as exc:
        finish(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])


def start(provider: str, open_browser: bool = True) -> dict:
    """Start a sign-in. Returns the URL; the browser is opened by the connector unless told not to."""
    cfg = _config(provider)
    with _lock:
        flow = _flows.get(provider, {})
        if flow.get("status") == "waiting" and time.time() - flow["started_at"] < _FLOW_TIMEOUT:
            return {"provider": provider, "status": "waiting", "url": flow["url"],
                    "note": "a sign-in is already in progress"}
    try:
        servers = _listeners(cfg["port"])
    except OSError as exc:
        return {"provider": provider, "status": "failed", "error": f"cannot listen on port {cfg['port']}: {exc}"}

    verifier = _b64url(secrets.token_bytes(48))
    state = _b64url(secrets.token_bytes(24))
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
    }
    if cfg["scopes"]:
        params["scope"] = cfg["scopes"]
    url = f"{cfg['authorize_url']}?{urlencode(params)}"

    with _lock:
        _flows[provider] = {"status": "waiting", "url": url, "started_at": time.time()}
    threading.Thread(target=_listen, args=(provider, cfg, servers, state, verifier), daemon=True).start()
    opened = webbrowser.open(url) if open_browser else False
    return {"provider": provider, "status": "waiting", "url": url, "browser_opened": opened}


LOST = ("No sign-in is in progress in this connector. Cowork starts the connector again for each turn, and a "
        "sign-in started in an earlier turn ended with it: start a new one, and wait for it in the same turn.")


def status(provider: str, wait: float = 0.0) -> dict:
    """The sign-in's state. While it is `waiting`, waits up to `wait` seconds for it to change, so one call covers the
    time a person takes in the browser: the sign-in lives only as long as the connector that started it."""
    keep = ("status", "login", "error", "stored_bytes", "token_bytes")
    deadline = time.monotonic() + wait
    while True:
        with _lock:
            flow = dict(_flows.get(provider, {"status": "idle"}))
        if flow["status"] != "waiting" or time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    answer = {"provider": provider, **{k: v for k, v in flow.items() if k in keep}}
    if flow["status"] == "idle":
        answer["note"] = LOST
    return answer


# --- using the stored sign-in -----------------------------------------------------------------------------

def _userinfo(cfg: dict, access_token: str) -> dict:
    with http_client() as client:
        response = client.get(cfg["userinfo_url"], headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code == 401:
        raise PermissionError("access token rejected")
    response.raise_for_status()
    return response.json()


def session(provider: str) -> dict | None:
    """The stored sign-in with a working access token (refreshed when needed) and the user's profile.
    None when not signed in. Internal: the token in it must never reach the model."""
    cfg = _config(provider)
    record = store.load(cfg["store_key"])
    if not record:
        return None
    refreshed = False

    def refresh() -> dict | None:
        try:
            tokens = _exchange(cfg, {"grant_type": "refresh_token", "refresh_token": record["refresh_token"]})
        except RuntimeError:  # the server refused it (expired or revoked): the user simply signs in again
            latest = store.load(cfg["store_key"])
            if latest and latest.get("refresh_token") != record["refresh_token"]:
                return latest  # another connector process refreshed it in the meantime
            store.delete(cfg["store_key"])
            return None
        _save(cfg, tokens)
        return store.load(cfg["store_key"])

    if record["expires_at"] < time.time() + 60 and record.get("refresh_token"):
        record, refreshed = refresh(), True
        if record is None:
            return None
    try:
        user = _userinfo(cfg, record["access_token"])
    except PermissionError:
        if not record.get("refresh_token") or refreshed:
            return None
        record, refreshed = refresh(), True
        if record is None:
            return None
        user = _userinfo(cfg, record["access_token"])
    return {"cfg": cfg, "record": record, "refreshed": refreshed, "user": user}


def whoami(provider: str) -> dict:
    """Who the stored sign-in belongs to, refreshing the access token when needed."""
    current = session(provider)
    if not current:
        return {"provider": provider, "signed_in": False}
    cfg, record = current["cfg"], current["record"]
    return {
        "provider": provider,
        "signed_in": True,
        "login": str(current["user"].get(cfg["login_field"], "?")),
        "refreshed": current["refreshed"],
        "token_obtained_minutes_ago": round((time.time() - record["obtained_at"]) / 60, 1),
        "expires_in_minutes": round((record["expires_at"] - time.time()) / 60, 1),
        "credential_store": store.BACKEND,
    }
