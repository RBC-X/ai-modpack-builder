"""Credential-free checks for Microsoft browser sign-in and Windows storage."""
from __future__ import annotations

import os
import sys
import threading
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import minecraft_auth as auth  # noqa: E402


CLIENT_ID = "11111111-2222-3333-4444-555555555555"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


protected = auth._protect(b"credential-roundtrip")
check("Windows DPAPI round trip", auth._unprotect(protected) == b"credential-roundtrip")

flow = auth.begin_browser_login(CLIENT_ID)
query = urllib.parse.parse_qs(urllib.parse.urlsplit(flow.authorize_url).query)
check("browser flow uses authorization code", query.get("response_type") == ["code"])
check("browser flow uses PKCE S256", query.get("code_challenge_method") == ["S256"]
      and bool(query.get("code_challenge", [""])[0]))
check("browser flow uses random state", query.get("state") == [flow.state])
check("browser flow returns to localhost", flow.redirect_uri.startswith("http://localhost:"))

original_request = auth._request_json
original_complete = auth._complete_minecraft_login
try:
    auth._request_json = lambda url, **_kwargs: {  # type: ignore[assignment]
        "access_token": "microsoft-access", "refresh_token": "refresh-token"
    }
    auth._complete_minecraft_login = lambda client_id, _access, _refresh: {  # type: ignore[assignment]
        "username": "RealPlayer", "clientId": client_id
    }

    def return_from_browser() -> None:
        callback = flow.redirect_uri + "?" + urllib.parse.urlencode({
            "code": "one-time-code", "state": flow.state,
        })
        with urllib.request.urlopen(callback, timeout=5) as response:
            response.read()

    callback_thread = threading.Thread(target=return_from_browser, daemon=True)
    callback_thread.start()
    session = auth.finish_browser_login(flow)
    callback_thread.join(timeout=5)
    check("localhost callback returns to launcher", session.get("username") == "RealPlayer")
finally:
    auth._request_json = original_request  # type: ignore[assignment]
    auth._complete_minecraft_login = original_complete  # type: ignore[assignment]

print("MICROSOFT BROWSER AUTH FLOW PASS")
