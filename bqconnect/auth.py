"""User-login (OAuth) authentication for BigQuery.

Uses the installed-app flow: a local web server is started, your browser
opens the Google consent screen, and the resulting user credentials are
cached to disk so you only log in once (they auto-refresh afterwards).
"""

from __future__ import annotations

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from . import config


def _load_cached(token_path: str, scopes: list[str]) -> Credentials | None:
    if not os.path.exists(token_path):
        return None
    try:
        return Credentials.from_authorized_user_file(token_path, scopes)
    except (ValueError, KeyError):
        # Corrupt or incompatible token file — ignore and re-authorize.
        return None


def get_credentials(
    client_secrets: str | None = None,
    token_path: str | None = None,
    scopes: list[str] | None = None,
    *,
    open_browser: bool = True,
) -> Credentials:
    """Return valid user credentials, prompting a web login if needed.

    Order of operations:
      1. Reuse a cached token if present and still valid.
      2. Silently refresh it if expired but refreshable.
      3. Otherwise run the browser consent flow and cache the new token.

    Set ``open_browser=False`` (or export ``BQ_NO_BROWSER=1``) on a headless
    machine to print a URL to paste into a browser instead.
    """
    client_secrets = client_secrets or config.CLIENT_SECRETS
    token_path = token_path or config.TOKEN_PATH
    scopes = scopes or config.SCOPES

    creds = _load_cached(token_path, scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not os.path.exists(client_secrets):
            raise FileNotFoundError(
                f"OAuth client-secrets file not found: {client_secrets!r}.\n"
                "Create one in the GCP console: APIs & Services -> Credentials -> "
                "Create credentials -> OAuth client ID -> Application type "
                '"Desktop app", then download the JSON. Point BQ_CLIENT_SECRETS '
                "at it (default: client_secret.json)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets, scopes)
        headless = not open_browser or os.environ.get("BQ_NO_BROWSER") == "1"
        # run_local_server starts a tiny web server and captures the OAuth
        # redirect. With open_browser=False it just prints the consent URL for
        # you to open manually (useful over SSH, as long as the browser can
        # reach this machine's localhost port).
        creds = flow.run_local_server(port=0, open_browser=not headless)

    with open(token_path, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass

    return creds
