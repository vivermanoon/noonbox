"""User-login (OAuth) authentication for GitLab.

Implements the OAuth 2.0 authorization-code flow with PKCE: a local web
server is started, your browser opens the GitLab authorization screen, and
the resulting user token is cached to disk so you only log in once (it
auto-refreshes afterwards).
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import time
import urllib.parse
import webbrowser

import requests

from . import config

_LEEWAY_SECONDS = 60  # treat a token as expired this long before it actually is


class Token:
    """A cached OAuth token, with just enough behaviour to refresh itself."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: float | None = None,
        scope: str | None = None,
        token_type: str = "Bearer",
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.scope = scope
        self.token_type = token_type

    @property
    def valid(self) -> bool:
        if not self.access_token:
            return False
        if self.expires_at is None:
            return True
        return time.time() < (self.expires_at - _LEEWAY_SECONDS)

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and not self.valid

    @classmethod
    def from_response(cls, data: dict) -> "Token":
        created = data.get("created_at") or time.time()
        expires_in = data.get("expires_in")
        expires_at = created + expires_in if expires_in else None
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scope=data.get("scope"),
            token_type=data.get("token_type", "Bearer"),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at,
                "scope": self.scope,
                "token_type": self.token_type,
            }
        )

    @classmethod
    def from_file(cls, path: str) -> "Token | None":
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return cls(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_at=data.get("expires_at"),
                scope=data.get("scope"),
                token_type=data.get("token_type", "Bearer"),
            )
        except (OSError, ValueError, KeyError):
            # Missing, corrupt or incompatible token file — re-authorize.
            return None

    def refresh(self) -> None:
        """Exchange the refresh token for a fresh access token, in place."""
        if not self.refresh_token:
            raise RuntimeError("Token has no refresh_token; a new login is required.")
        payload = {
            "client_id": _require_client_id(),
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
            "redirect_uri": config.REDIRECT_URI,
        }
        if config.CLIENT_SECRET:
            payload["client_secret"] = config.CLIENT_SECRET
        data = _post_token(payload)
        refreshed = Token.from_response(data)
        # GitLab may rotate the refresh token; keep the newest of each field.
        self.access_token = refreshed.access_token
        self.refresh_token = refreshed.refresh_token or self.refresh_token
        self.expires_at = refreshed.expires_at
        self.scope = refreshed.scope or self.scope
        self.token_type = refreshed.token_type


def token_from_access_token(access_token: str) -> Token:
    """Build a Token from a raw access token supplied out-of-band.

    Useful when a token is provided directly (e.g. a short-lived OAuth token
    or a personal access token). It cannot be refreshed, so it stops working
    when it expires; supply a fresh one to continue.
    """
    return Token(access_token=access_token.strip())


def _require_client_id() -> str:
    if not config.CLIENT_ID:
        raise RuntimeError(
            "GITLAB_CLIENT_ID is not set.\n"
            "Create an OAuth application in GitLab: Settings -> Applications -> "
            "Add new application. Set the redirect URI to "
            f"{config.REDIRECT_URI!r}, tick the scopes you need (e.g. 'api'), "
            "then export GITLAB_CLIENT_ID (and GITLAB_CLIENT_SECRET for a "
            "confidential app)."
        )
    return config.CLIENT_ID


def _post_token(payload: dict) -> dict:
    resp = requests.post(
        f"{config.GITLAB_URL}/oauth/token",
        data=payload,
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"GitLab token endpoint returned {resp.status_code}: {resp.text}"
        )
    return resp.json()


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures the single OAuth redirect and shows a friendly page."""

    result: dict = {}

    def do_GET(self) -> None:  # noqa: N802 - required name from BaseHTTPRequestHandler
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != urllib.parse.urlparse(config.REDIRECT_URI).path:
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        type(self).result = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            "<html><body style='font-family:sans-serif'>"
            "<h3>GitLab login complete.</h3>"
            "<p>You can close this tab and return to the terminal.</p>"
            "</body></html>"
        )
        self.wfile.write(body.encode())

    def log_message(self, *args) -> None:  # silence default request logging
        return


def _run_login_flow(scopes: list[str]) -> Token:
    client_id = _require_client_id()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    authorize_url = f"{config.GITLAB_URL}/oauth/authorize?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": config.REDIRECT_URI,
            "response_type": "code",
            "state": state,
            "scope": " ".join(scopes),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    headless = os.environ.get("GITLAB_NO_BROWSER") == "1"
    server = http.server.HTTPServer(("localhost", config.REDIRECT_PORT), _CallbackHandler)
    _CallbackHandler.result = {}

    if headless:
        print("Open this URL in a browser to authorize:\n" + authorize_url)
    else:
        print("Opening your browser to authorize with GitLab...")
        webbrowser.open(authorize_url)

    # Serve exactly one request: the OAuth redirect.
    server.handle_request()
    server.server_close()

    result = _CallbackHandler.result
    if "error" in result:
        raise RuntimeError(
            f"Authorization failed: {result.get('error')} "
            f"{result.get('error_description', '')}".strip()
        )
    if result.get("state") != state:
        raise RuntimeError("State mismatch on OAuth redirect; aborting for safety.")
    if "code" not in result:
        raise RuntimeError("No authorization code received from GitLab.")

    payload = {
        "client_id": client_id,
        "code": result["code"],
        "grant_type": "authorization_code",
        "redirect_uri": config.REDIRECT_URI,
        "code_verifier": verifier,
    }
    if config.CLIENT_SECRET:
        payload["client_secret"] = config.CLIENT_SECRET
    return Token.from_response(_post_token(payload))


def get_token(
    token_path: str | None = None,
    scopes: list[str] | None = None,
    *,
    open_browser: bool = True,
) -> Token:
    """Return a valid user token, prompting a web login if needed.

    Order of operations:
      1. Reuse a cached token if present and still valid.
      2. Silently refresh it if expired but refreshable.
      3. Otherwise run the browser authorization flow and cache the new token.

    Set ``open_browser=False`` (or export ``GITLAB_NO_BROWSER=1``) on a
    headless machine to print a URL to open manually instead.
    """
    token_path = token_path or config.TOKEN_PATH
    scopes = scopes or config.SCOPES

    token = Token.from_file(token_path)

    if token and token.valid:
        return token

    if token and token.expired and token.refresh_token:
        try:
            token.refresh()
        except RuntimeError:
            token = None  # refresh rejected (e.g. revoked) — fall back to login
    else:
        token = None

    if token is None:
        if not open_browser:
            os.environ["GITLAB_NO_BROWSER"] = "1"
        token = _run_login_flow(scopes)

    with open(token_path, "w", encoding="utf-8") as fh:
        fh.write(token.to_json())
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass

    return token
