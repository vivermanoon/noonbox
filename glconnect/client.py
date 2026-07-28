"""Construct an authenticated GitLab client for the configured instance."""

from __future__ import annotations

import os

import gitlab

from . import config
from .auth import get_token, token_from_access_token


def get_client(
    url: str | None = None,
    *,
    access_token: str | None = None,
    open_browser: bool = True,
) -> gitlab.Gitlab:
    """Return a ``gitlab.Gitlab`` client for the configured instance.

    Credential resolution order:
      1. ``access_token`` argument, if given.
      2. ``GITLAB_ACCESS_TOKEN`` environment variable, if set.
      3. The browser user-login flow (cached + auto-refreshing).

    A supplied token (arg or env) may be an OAuth access token or a personal
    access token; set ``GITLAB_TOKEN_TYPE=private`` to use it as the latter.
    """
    url = url or config.GITLAB_URL
    token = access_token or os.environ.get("GITLAB_ACCESS_TOKEN")

    if token:
        token = token.strip()
        if os.environ.get("GITLAB_TOKEN_TYPE", "oauth").lower() == "private":
            return gitlab.Gitlab(url, private_token=token)
        return gitlab.Gitlab(url, oauth_token=token)

    tok = get_token(open_browser=open_browser)
    return gitlab.Gitlab(url, oauth_token=tok.access_token)
