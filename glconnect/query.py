"""Call the GitLab REST API and get results back as parsed JSON."""

from __future__ import annotations

from typing import Any

import gitlab

from .client import get_client


def fetch(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    client: gitlab.Gitlab | None = None,
    method: str = "get",
) -> Any:
    """Call an API endpoint and return the decoded JSON.

    ``path`` is relative to the instance's ``/api/v4`` root, e.g.::

        fetch("/user")                                   # the current user
        fetch("/projects", params={"membership": True})  # your projects
        fetch("/projects/123/issues", params={"state": "opened"})

    For list endpoints, ``params`` accepts the usual query options
    (``per_page``, ``page``, filters, ...). Returns a dict or list depending
    on the endpoint.
    """
    client = client or get_client()
    method = method.lower()

    if method == "get":
        return client.http_get(path, query_data=params or {})
    if method == "list":
        # Auto-paginating list helper; returns all matching items.
        return client.http_list(path, query_data=params or {}, iterator=False)
    return client.http_request(method, path, query_data=params or {}).json()


def current_user(client: gitlab.Gitlab | None = None) -> dict:
    """Return the authenticated user's profile (a convenience wrapper)."""
    return fetch("/user", client=client)
