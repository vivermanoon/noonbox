"""Construct an authenticated BigQuery client for the configured project."""

from __future__ import annotations

from google.cloud import bigquery

from . import config
from .auth import get_credentials


def get_client(
    project: str | None = None,
    *,
    open_browser: bool = True,
) -> bigquery.Client:
    """Return a ``bigquery.Client`` authenticated as the logged-in user.

    The first call triggers a browser login (unless a cached token exists);
    subsequent calls reuse the cached, auto-refreshing credentials.
    """
    project = project or config.PROJECT
    credentials = get_credentials(open_browser=open_browser)
    return bigquery.Client(
        project=project,
        credentials=credentials,
        location=config.LOCATION,
    )
