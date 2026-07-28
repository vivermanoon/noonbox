"""Central configuration, resolved from environment variables with defaults.

A .env file (if present) is loaded first so local overrides just work.
"""

from __future__ import annotations

import os
from pathlib import Path

# Load a .env file if one exists, without adding a hard dependency.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _val = _line.partition("=")
        os.environ.setdefault(_key.strip(), _val.strip())

# GitLab instance to connect to (defaults to noon's self-hosted instance;
# override via GITLAB_URL for gitlab.com or another host).
GITLAB_URL = os.environ.get("GITLAB_URL", "https://dp-gitlab.noon.team").rstrip("/")

# OAuth application credentials, created under GitLab -> Settings ->
# Applications. CLIENT_SECRET is optional: leave it unset for a
# non-confidential (PKCE-only) application.
CLIENT_ID = os.environ.get("GITLAB_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GITLAB_CLIENT_SECRET") or None

# Cached user token, written after the first successful login.
TOKEN_PATH = os.environ.get("GITLAB_TOKEN_PATH", ".gitlab_token.json")

# The OAuth redirect must exactly match one registered on the application.
# A local server on this port captures the redirect during login.
REDIRECT_PORT = int(os.environ.get("GITLAB_REDIRECT_PORT", "8080"))
REDIRECT_URI = os.environ.get(
    "GITLAB_REDIRECT_URI", f"http://localhost:{REDIRECT_PORT}/callback"
)

# Space-separated OAuth scopes. "api" grants full read/write API access;
# use "read_api" (or "read_user") to stay read-only.
SCOPES = os.environ.get("GITLAB_SCOPES", "api").split()
