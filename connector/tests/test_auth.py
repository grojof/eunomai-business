"""Sign-in: authorization code + PKCE against the fake server, the encrypted store, refresh, sign-out."""

import json
import time

import pytest

from eunomai_business import auth, data_dir, store


def test_sign_in_is_stored_encrypted_and_reused(signed_in):
    status = auth.status("git")
    assert status["login"] == "tester" and status["stored_bytes"] > 0
    me = auth.whoami("git")
    assert me["signed_in"] and me["login"] == "tester" and me["refreshed"] is False
    if store.BACKEND == "dpapi-file":
        for record in data_dir().glob("signin-*.dpapi"):
            assert b"token-" not in record.read_bytes()  # encrypted, not plain JSON


def test_forged_callback_is_rejected(server, monkeypatch):
    import httpx
    from urllib.parse import parse_qs, urlsplit

    monkeypatch.setenv("EUNOMAI_PROVIDERS", json.dumps({"forged": server.provider("forged-client")}))
    started = auth.start("forged", open_browser=False)
    redirect = parse_qs(urlsplit(started["url"]).query)["redirect_uri"][0]
    httpx.get(redirect, params={"code": "code-1", "state": "not-the-one-we-sent"})
    for _ in range(50):
        if auth.status("forged")["status"] != "waiting":
            break
        time.sleep(0.1)
    assert auth.status("forged") == {"provider": "forged", "status": "failed", "error": "state mismatch"}
    assert "code_challenge_method=S256" in started["url"]


def test_expired_token_is_refreshed(signed_in, monkeypatch):
    cfg = auth._config("git")
    record = store.load(cfg["store_key"])
    record["expires_at"] = time.time() - 1
    store.save(cfg["store_key"], record)
    assert auth.whoami("git")["refreshed"] is True


def test_sign_out_forgets_and_resets_the_status(signed_in):
    assert auth.sign_out("git")["signed_out"] is True
    assert auth.status("git")["status"] == "idle"
    assert auth.whoami("git") == {"provider": "git", "signed_in": False}


def test_each_provider_has_its_own_record(server, monkeypatch):
    shared = server.provider(client_id="same-id")
    monkeypatch.setenv("EUNOMAI_PROVIDERS", json.dumps({"one": shared, "two": dict(shared)}))
    assert auth._config("one")["store_key"] != auth._config("two")["store_key"]


@pytest.mark.parametrize("url", ["http://git.example.test/x", "ftp://git.example.test/x", "git.example.test",
                                 "http://[::1]/x"])
def test_tokens_never_travel_in_clear_text(url):
    with pytest.raises(ValueError, match="not HTTPS"):
        auth.check_url(url)


@pytest.mark.parametrize("url", ["https://git.example.test/x", "http://127.0.0.1:8080/x", "http://localhost/x"])
def test_https_and_this_computer_are_accepted(url):
    auth.check_url(url)


def test_provider_with_http_endpoint_is_refused(server, monkeypatch):
    provider = dict(server.provider(), token_url="http://git.example.test/token")
    monkeypatch.setenv("EUNOMAI_PROVIDERS", json.dumps({"git": provider}))
    with pytest.raises(ValueError, match="not HTTPS"):
        auth.start("git", open_browser=False)


def test_a_refused_refresh_means_signing_in_again(signed_in):
    cfg = auth._config("git")
    record = store.load(cfg["store_key"])
    record["expires_at"] = time.time() - 1
    store.save(cfg["store_key"], record)
    signed_in.reject_refresh = True
    try:
        assert auth.whoami("git") == {"provider": "git", "signed_in": False}
        assert store.load(cfg["store_key"]) is None
    finally:
        signed_in.reject_refresh = False


def test_an_unknown_provider_is_a_mistake_in_the_call(server, monkeypatch):
    from eunomai_business import server as tools

    monkeypatch.setenv("EUNOMAI_PROVIDERS", json.dumps({"git": server.provider()}))
    assert "unknown provider" in tools._safe(auth.whoami, "nope")["error"]


def test_a_network_outage_asks_the_user_to_check_the_network(signed_in, monkeypatch):
    import httpx

    from eunomai_business import server as tools

    def down():
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(auth, "http_client", down)
    assert tools._safe(auth.whoami, "git")["status"] == "unreachable"
