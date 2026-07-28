#!/usr/bin/env python3
"""Minimal web UI to log in to GitLab and call the API.

Run locally with:

    pip install streamlit
    streamlit run gl_app.py

Click "Log in with GitLab" to open the OAuth authorization screen in your
browser, then call REST API endpoints and preview the JSON results.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from glconnect import config
from glconnect.client import get_client
from glconnect.query import fetch

st.set_page_config(page_title="GitLab Console", page_icon="\U0001f98a")
st.title("GitLab Console")
st.caption(f"Instance: `{config.GITLAB_URL}`")


@st.cache_resource(show_spinner="Connecting to GitLab...")
def _client():
    return get_client()


if "authed" not in st.session_state:
    st.session_state.authed = False

if not st.session_state.authed:
    st.info(
        "First login opens the GitLab authorization screen in your browser. "
        "The token is then cached so you won't be asked again."
    )
    if st.button("Log in with GitLab", type="primary"):
        try:
            _client()
            st.session_state.authed = True
            st.success("Logged in.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001 - surface any auth error to the UI
            st.error(f"Login failed: {exc}")
else:
    client = _client()
    client.auth()
    st.success(f"Connected as `@{client.user.username}` to `{config.GITLAB_URL}`.")

    path = st.text_input("API path", value="/user")
    method = st.selectbox("Method", ["get", "list"], index=0)

    if st.button("Call", type="primary"):
        try:
            with st.spinner("Calling GitLab API..."):
                result = fetch(path, client=client, method=method)
            if isinstance(result, list):
                st.dataframe(pd.json_normalize(result), use_container_width=True)
                st.caption(f"{len(result)} item(s)")
            else:
                st.json(result)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
