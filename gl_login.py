#!/usr/bin/env python3
"""Log in to GitLab via the browser and cache the token.

Run this once (locally, where a browser is available):

    python gl_login.py

It opens the GitLab authorization screen, then verifies the connection by
looking up your account and listing a few projects you belong to.
"""

from __future__ import annotations

import sys

from glconnect import config
from glconnect.client import get_client


def main() -> int:
    print(f"Authenticating to GitLab: {config.GITLAB_URL}")
    gl = get_client()

    print("Login OK. Verifying access...")
    gl.auth()  # populates gl.user from the token
    user = gl.user
    print(f"Connected as: {user.name} (@{user.username}, id={user.id})")

    projects = gl.projects.list(membership=True, per_page=10, get_all=False)
    if projects:
        print(f"Found {len(projects)} project(s) you belong to (showing up to 10):")
        for proj in projects:
            print(f"  - {proj.path_with_namespace}")
    else:
        print("Connected, but you don't appear to be a member of any projects.")

    print(f"\nToken cached at: {config.TOKEN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
