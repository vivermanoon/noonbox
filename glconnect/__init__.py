"""Lightweight helpers to connect to GitLab with a user-login (OAuth) flow."""

from .auth import get_token, token_from_access_token
from .client import get_client
from .query import current_user, fetch

__all__ = ["get_token", "token_from_access_token", "get_client", "current_user", "fetch"]
