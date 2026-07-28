#!/usr/bin/env python3
"""Am I connected to GitLab? A one-command connectivity check.

    python gl_check.py

Prints the authenticated account and a couple of your projects, then exits 0.
On any failure (unreachable host, bad token, TLS/CA error, ...) it prints a
short diagnosis to stderr and exits non-zero, so it's safe to use in scripts:

    python gl_check.py && echo "connected"

Honours the same configuration as the rest of glconnect (GITLAB_URL,
GITLAB_ACCESS_TOKEN / OAuth login, GITLAB_CA_BUNDLE, ...). See GITLAB.md.
"""

from __future__ import annotations

import sys

from glconnect import config


def main() -> int:
    print(f"GitLab: {config.GITLAB_URL}", file=sys.stderr)
    try:
        from glconnect.client import get_client

        # interactive=False: never launch a browser login for a health check;
        # if there's no supplied/cached token, this raises instead of prompting.
        gl = get_client(interactive=False)
        gl.auth()  # makes a real API call; raises on any connection/auth problem
    except Exception as exc:  # noqa: BLE001 - turn any failure into a clean report
        print(f"NOT CONNECTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(_hint(exc), file=sys.stderr)
        return 1

    user = gl.user
    print(f"Connected as: {user.name} (@{user.username}, id={user.id})")

    try:
        projects = gl.projects.list(membership=True, per_page=5, get_all=False)
        if projects:
            print("Sample projects:")
            for proj in projects:
                print(f"  - {proj.path_with_namespace}")
        else:
            print("(no projects visible for this account)")
    except Exception as exc:  # noqa: BLE001 - auth worked; listing is best-effort
        print(f"(connected, but couldn't list projects: {exc})", file=sys.stderr)

    return 0


def _hint(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if "certificate" in text or "ssl" in text or "verify failed" in text:
        return (
            "Hint: TLS verification failed — set GITLAB_CA_BUNDLE to your "
            "instance's internal CA PEM (see GITLAB.md)."
        )
    if "401" in text or "unauthor" in text:
        return (
            "Hint: the token was rejected — check GITLAB_ACCESS_TOKEN and, for a "
            "personal/access token, set GITLAB_TOKEN_TYPE=private."
        )
    if "connection" in text or "timed out" in text or "resolve" in text or "refused" in text:
        return (
            "Hint: couldn't reach the host — confirm GITLAB_URL and that this "
            "machine is on a network that can reach the instance."
        )
    if "gitlab_client_id" in text or "gitlab_access_token" in text:
        return (
            "Hint: no credentials found — set GITLAB_ACCESS_TOKEN, or configure "
            "OAuth login (GITLAB_CLIENT_ID) and run `python gl_login.py`."
        )
    return "See GITLAB.md for configuration."


if __name__ == "__main__":
    sys.exit(main())
