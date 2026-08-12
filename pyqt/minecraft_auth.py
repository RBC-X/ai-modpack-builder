"""Microsoft/Xbox/Minecraft authentication for the desktop launcher.

The public Microsoft application id is stored in ``state.json`` by the UI.
Refresh and Minecraft access tokens are never stored there: on Windows they
are protected with DPAPI, which binds the encrypted credential to the signed-in
Windows user.  The launcher never asks for a Microsoft password; sign-in is
completed on Microsoft's own device-login page.
"""
from __future__ import annotations

import ctypes
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from product_config import MICROSOFT_CLIENT_ID


DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
AUTHORIZE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBOX_USER_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MINECRAFT_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MINECRAFT_ENTITLEMENTS_URL = "https://api.minecraftservices.com/entitlements/mcstore"
MINECRAFT_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
SCOPES = "XboxLive.signin offline_access"
USER_AGENT = "AI-Modpack-Builder/1.2"


class AuthError(RuntimeError):
    """A safe, user-facing authentication failure."""


class _ServiceError(AuthError):
    def __init__(self, code: str, description: str, status: int = 0, payload: dict | None = None):
        super().__init__(description or code)
        self.code = code
        self.status = status
        self.payload = payload or {}


class BrowserLogin:
    """Short-lived local callback listener and PKCE state for browser sign-in."""

    def __init__(self, client_id: str):
        self.client_id = validate_client_id(client_id)
        self.state = secrets.token_urlsafe(32)
        self.verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self.verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(handler) -> None:  # noqa: N802
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
                handler.server.auth_result = {key: values[0] for key, values in query.items()}  # type: ignore[attr-defined]
                html = ("<!doctype html><html><head><meta charset='utf-8'><title>Microsoft sign-in complete</title>"
                        "<style>body{margin:0;background:#111416;color:#f4f6f8;font:16px Segoe UI,Arial,sans-serif;"
                        "display:grid;place-items:center;min-height:100vh}.card{max-width:480px;padding:36px;"
                        "background:#191d20;border:1px solid #30363b;border-radius:14px}h1{font-size:24px}"
                        "p{color:#a7adb4;line-height:1.55}</style></head><body><main class='card'>"
                        "<h1>You're signed in</h1><p>Return to AI Minecraft Launcher. You can close this tab.</p>"
                        "</main></body></html>")
                body = html.encode("utf-8")
                handler.send_response(200)
                handler.send_header("Content-Type", "text/html; charset=utf-8")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
        self.server.timeout = 0.5
        self.server.auth_result = None  # type: ignore[attr-defined]
        port = self.server.server_address[1]
        self.redirect_uri = f"http://localhost:{port}"
        self.authorize_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": SCOPES,
            "state": self.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })

    def close(self) -> None:
        self.server.server_close()


def validate_client_id(value: str) -> str:
    client_id = value.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", client_id):
        raise AuthError("Enter a valid Microsoft application (client) ID.")
    return client_id


def configured_client_id() -> str:
    """Return the publisher-owned application id; never ask a player for it."""
    if not MICROSOFT_CLIENT_ID:
        raise AuthError("Microsoft sign-in is not enabled in this launcher build.")
    return validate_client_id(MICROSOFT_CLIENT_ID)


def _request_json(url: str, *, data: dict | None = None, payload: dict | None = None,
                  headers: dict[str, str] | None = None, timeout: float = 30) -> dict:
    request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    body: bytes | None = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers,
                                     method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            detail = {}
        code = str(detail.get("error") or detail.get("XErr") or f"HTTP {exc.code}")
        message = str(detail.get("error_description") or detail.get("errorMessage")
                      or detail.get("Message") or detail.get("message") or code)
        raise _ServiceError(code, message, exc.code, detail) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise AuthError(f"Microsoft sign-in could not connect: {reason}") from exc


def begin_device_login(client_id: str) -> dict:
    """Start Microsoft device authorization and return the public prompt data."""
    return _request_json(DEVICE_CODE_URL, data={
        "client_id": validate_client_id(client_id),
        "scope": SCOPES,
    })


def begin_browser_login(client_id: str) -> BrowserLogin:
    """Prepare standard Microsoft system-browser sign-in with PKCE."""
    return BrowserLogin(client_id)


def finish_browser_login(flow: BrowserLogin,
                         cancel: threading.Event | None = None) -> dict:
    """Wait for Microsoft's localhost redirect and exchange its one-time code."""
    deadline = time.monotonic() + 10 * 60
    try:
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                raise AuthError("Microsoft sign-in was canceled.")
            flow.server.handle_request()
            result = flow.server.auth_result  # type: ignore[attr-defined]
            if result:
                break
        else:
            raise AuthError("Microsoft sign-in timed out. Try again.")
    finally:
        flow.close()
    if result.get("error"):
        description = str(result.get("error_description") or result.get("error"))
        raise AuthError(f"Microsoft sign-in failed: {description}")
    if not secrets.compare_digest(str(result.get("state") or ""), flow.state):
        raise AuthError("Microsoft sign-in returned an invalid security state.")
    code = str(result.get("code") or "")
    if not code:
        raise AuthError("Microsoft sign-in did not return an authorization code.")
    try:
        token = _request_json(TOKEN_URL, data={
            "client_id": flow.client_id,
            "scope": SCOPES,
            "code": code,
            "redirect_uri": flow.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": flow.verifier,
        })
    except _ServiceError as exc:
        raise AuthError(f"Microsoft sign-in could not finish: {exc}") from exc
    refresh_token = str(token.get("refresh_token") or "")
    if not refresh_token:
        raise AuthError("Microsoft did not issue a refresh credential. Try signing in again.")
    return _complete_minecraft_login(
        flow.client_id, str(token.get("access_token") or ""), refresh_token)


def finish_device_login(client_id: str, flow: dict,
                        cancel: threading.Event | None = None) -> dict:
    """Poll Microsoft until the browser sign-in finishes, then verify Minecraft."""
    client_id = validate_client_id(client_id)
    device_code = str(flow.get("device_code") or "")
    if not device_code:
        raise AuthError("Microsoft did not return a device sign-in code.")
    interval = max(2, int(flow.get("interval") or 5))
    deadline = time.monotonic() + max(30, int(flow.get("expires_in") or 900))
    token: dict | None = None
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_set():
            raise AuthError("Microsoft sign-in was canceled.")
        try:
            token = _request_json(TOKEN_URL, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            })
            break
        except _ServiceError as exc:
            if exc.code == "authorization_pending":
                time.sleep(interval)
                continue
            if exc.code == "slow_down":
                interval += 5
                time.sleep(interval)
                continue
            if exc.code == "authorization_declined":
                raise AuthError("Microsoft sign-in was declined.") from exc
            if exc.code in ("expired_token", "bad_verification_code"):
                raise AuthError("The Microsoft sign-in code expired. Start sign-in again.") from exc
            raise AuthError(f"Microsoft sign-in failed: {exc}") from exc
    if token is None:
        raise AuthError("The Microsoft sign-in code expired. Start sign-in again.")
    refresh_token = str(token.get("refresh_token") or "")
    if not refresh_token:
        raise AuthError("Microsoft did not issue a refresh credential. Try signing in again.")
    return _complete_minecraft_login(client_id, str(token.get("access_token") or ""), refresh_token)


def _refresh_microsoft(client_id: str, refresh_token: str) -> tuple[str, str]:
    try:
        token = _request_json(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": validate_client_id(client_id),
            "refresh_token": refresh_token,
            "scope": SCOPES,
        })
    except _ServiceError as exc:
        if exc.code in ("invalid_grant", "interaction_required"):
            raise AuthError("Your Microsoft sign-in expired. Connect the account again.") from exc
        raise AuthError(f"Microsoft account refresh failed: {exc}") from exc
    access_token = str(token.get("access_token") or "")
    if not access_token:
        raise AuthError("Microsoft did not return an access token.")
    return access_token, str(token.get("refresh_token") or refresh_token)


def _complete_minecraft_login(client_id: str, microsoft_access_token: str,
                              refresh_token: str) -> dict:
    if not microsoft_access_token:
        raise AuthError("Microsoft did not return an access token.")
    xbox = _request_json(XBOX_USER_URL, payload={
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": "d=" + microsoft_access_token,
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    }, headers={"x-xbl-contract-version": "1"})
    xbox_token = str(xbox.get("Token") or "")
    try:
        user_hash = str(xbox["DisplayClaims"]["xui"][0]["uhs"])
    except (KeyError, IndexError, TypeError) as exc:
        raise AuthError("Xbox Live did not return an account identity.") from exc
    try:
        xsts = _request_json(XSTS_URL, payload={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbox_token]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        }, headers={"x-xbl-contract-version": "1"})
    except _ServiceError as exc:
        xerr = str(exc.payload.get("XErr") or exc.code)
        messages = {
            "2148916233": "This Microsoft account does not have an Xbox profile yet.",
            "2148916235": "Xbox Live is unavailable for this account's region.",
            "2148916238": "A parent must finish setting up this child account on Xbox.",
        }
        raise AuthError(messages.get(xerr, f"Xbox authorization failed ({xerr}).")) from exc
    xsts_token = str(xsts.get("Token") or "")
    minecraft = _request_json(MINECRAFT_LOGIN_URL, payload={
        "identityToken": f"XBL3.0 x={user_hash};{xsts_token}",
    })
    minecraft_token = str(minecraft.get("access_token") or "")
    if not minecraft_token:
        raise AuthError("Minecraft Services did not return a game token.")
    bearer = {"Authorization": "Bearer " + minecraft_token}
    entitlements = _request_json(MINECRAFT_ENTITLEMENTS_URL, headers=bearer)
    if not (entitlements.get("items") or []):
        raise AuthError("This Microsoft account does not own Minecraft: Java Edition.")
    try:
        profile = _request_json(MINECRAFT_PROFILE_URL, headers=bearer)
    except _ServiceError as exc:
        if exc.status in (403, 404):
            raise AuthError("This account has no Minecraft: Java Edition profile.") from exc
        raise
    name = str(profile.get("name") or "").strip()
    uuid = re.sub(r"[^0-9a-fA-F]", "", str(profile.get("id") or ""))
    if not re.fullmatch(r"[0-9a-fA-F]{32}", uuid) or not re.fullmatch(r"\w{1,16}", name):
        raise AuthError("Minecraft Services returned an invalid Java profile.")
    credential = {
        "version": 1,
        "clientId": client_id,
        "refreshToken": refresh_token,
        "minecraftAccessToken": minecraft_token,
        "minecraftExpiresAt": int(time.time()) + max(300, int(minecraft.get("expires_in") or 86400)),
        "profile": {"id": uuid.lower(), "name": name},
        "xuid": str(minecraft.get("username") or ""),
    }
    _save_credential(credential)
    return _session_from_credential(credential)


def get_minecraft_session(client_id: str) -> dict:
    """Return a current Minecraft launch session, refreshing when necessary."""
    client_id = validate_client_id(client_id)
    credential = _load_credential()
    if not credential or credential.get("clientId") != client_id:
        raise AuthError("Connect your Microsoft account before launching.")
    if (credential.get("minecraftAccessToken")
            and int(credential.get("minecraftExpiresAt") or 0) > int(time.time()) + 300):
        return _session_from_credential(credential)
    access_token, rotated_refresh = _refresh_microsoft(
        client_id, str(credential.get("refreshToken") or ""))
    return _complete_minecraft_login(client_id, access_token, rotated_refresh)


def _session_from_credential(credential: dict) -> dict:
    profile = credential.get("profile") or {}
    return {
        "username": str(profile.get("name") or ""),
        "uuid": str(profile.get("id") or ""),
        "accessToken": str(credential.get("minecraftAccessToken") or ""),
        "userType": "msa",
        "xuid": str(credential.get("xuid") or ""),
        "clientId": str(credential.get("clientId") or ""),
    }


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


_ENTROPY = b"AI Modpack Builder Microsoft account v1"


def _credential_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return root / "AI Modpack Builder" / "credentials" / "minecraft-account.dpapi"


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise AuthError("Secure Microsoft account storage is currently available on Windows only.")
    incoming, incoming_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    outgoing = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(incoming), "AI Modpack Builder", ctypes.byref(entropy),
        None, None, 0x1, ctypes.byref(outgoing))
    if not ok:
        raise AuthError("Windows could not protect the Microsoft credential.")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise AuthError("Secure Microsoft account storage is currently available on Windows only.")
    incoming, incoming_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    outgoing = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(incoming), None, ctypes.byref(entropy),
        None, None, 0x1, ctypes.byref(outgoing))
    if not ok:
        raise AuthError("The saved Microsoft credential cannot be unlocked by this Windows account.")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def _save_credential(credential: dict) -> None:
    path = _credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    protected = _protect(json.dumps(credential, separators=(",", ":")).encode("utf-8"))
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(protected)
    temporary.replace(path)


def _load_credential() -> dict | None:
    path = _credential_path()
    if not path.is_file():
        return None
    try:
        return json.loads(_unprotect(path.read_bytes()).decode("utf-8"))
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AuthError("The saved Microsoft credential is damaged. Disconnect and sign in again.") from exc


def disconnect() -> None:
    try:
        _credential_path().unlink(missing_ok=True)
    except OSError as exc:
        raise AuthError(f"Could not remove the saved Microsoft account: {exc}") from exc


def has_saved_credential() -> bool:
    return _credential_path().is_file()
