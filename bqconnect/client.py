"""Construct an authenticated BigQuery client for the configured project."""

from __future__ import annotations

import os

from google.cloud import bigquery

from . import config
from .auth import credentials_from_access_token, get_credentials


def get_client(
    project: str | None = None,
    *,
    access_token: str | None = None,
    open_browser: bool = True,
) -> bigquery.Client:
    """Return a ``bigquery.Client`` for the configured project.

    Credential resolution order:
      1. ``access_token`` argument, if given.
      2. ``BQ_ACCESS_TOKEN`` environment variable, if set (e.g. from
         ``gcloud auth application-default print-access-token``).
      3. The browser user-login flow (cached + auto-refreshing).
    """
    project = project or config.PROJECT
    token = access_token or os.environ.get("BQ_ACCESS_TOKEN")
    if token:
        credentials = credentials_from_access_token(token)
    else:
        credentials = get_credentials(open_browser=open_browser)
    return bigquery.Client(
        project=project,
        credentials=credentials,
        location=config.LOCATION,
    )
