"""Lightweight helpers to connect to BigQuery with a user-login (OAuth) flow."""

from .auth import get_credentials
from .client import get_client
from .query import run_query

__all__ = ["get_credentials", "get_client", "run_query"]
