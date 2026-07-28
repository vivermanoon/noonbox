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

# GCP project to run/bill queries against.
PROJECT = os.environ.get("BQ_PROJECT", "noonbimerch")

# OAuth client-secrets file (downloaded from the GCP console, "Desktop app").
CLIENT_SECRETS = os.environ.get("BQ_CLIENT_SECRETS", "client_secret.json")

# Cached user token, written after the first successful login.
TOKEN_PATH = os.environ.get("BQ_TOKEN_PATH", ".bq_token.json")

# Optional job location (US, EU, us-central1, ...). None lets BigQuery decide.
LOCATION = os.environ.get("BQ_LOCATION") or None

# Scopes for read/write BigQuery access via user credentials.
SCOPES = [
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/cloud-platform",
]
