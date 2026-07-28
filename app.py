#!/usr/bin/env python3
"""Minimal web UI to log in to BigQuery and run queries.

Run locally with:

    pip install streamlit
    streamlit run app.py

Click "Log in with Google" to open the OAuth consent screen in your browser,
then run SQL against the configured project and preview results.
"""

from __future__ import annotations

import streamlit as st

from bqconnect import config
from bqconnect.client import get_client
from bqconnect.query import run_query

st.set_page_config(page_title="BigQuery Console", page_icon="\U0001f50e")
st.title("BigQuery Console")
st.caption(f"Project: `{config.PROJECT}`")


@st.cache_resource(show_spinner="Connecting to BigQuery...")
def _client():
    return get_client()


if "authed" not in st.session_state:
    st.session_state.authed = False

if not st.session_state.authed:
    st.info(
        "First login opens a Google consent screen in your browser. "
        "The token is then cached so you won't be asked again."
    )
    if st.button("Log in with Google", type="primary"):
        try:
            _client()
            st.session_state.authed = True
            st.success("Logged in.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001 - surface any auth error to the UI
            st.error(f"Login failed: {exc}")
else:
    client = _client()
    st.success(f"Connected as authorized user to `{config.PROJECT}`.")

    default_sql = "SELECT CURRENT_DATE() AS today, SESSION_USER() AS who"
    sql = st.text_area("SQL", value=default_sql, height=160)

    col1, col2 = st.columns(2)
    with col1:
        run = st.button("Run", type="primary")
    with col2:
        dry = st.button("Dry run (estimate only)")

    if dry:
        try:
            job = run_query(sql, client=client, dry_run=True)
            gib = (job.total_bytes_processed or 0) / (1024**3)
            st.info(f"Would scan ~{gib:.3f} GiB.")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    if run:
        try:
            with st.spinner("Running query..."):
                df = run_query(sql, client=client).to_dataframe()
            st.dataframe(df, use_container_width=True)
            st.caption(f"{len(df)} row(s)")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
