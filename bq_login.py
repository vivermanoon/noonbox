#!/usr/bin/env python3
"""Log in to BigQuery via the browser and cache the token.

Run this once (locally, where a browser is available):

    python bq_login.py

It opens the Google consent screen, then verifies the connection to the
configured project by listing a few datasets.
"""

from __future__ import annotations

import sys

from bqconnect import config
from bqconnect.client import get_client


def main() -> int:
    print(f"Authenticating to BigQuery project: {config.PROJECT}")
    client = get_client()

    print("Login OK. Verifying access...")
    datasets = list(client.list_datasets(max_results=10))
    if datasets:
        print(f"Found {len(datasets)} dataset(s) (showing up to 10):")
        for ds in datasets:
            print(f"  - {ds.dataset_id}")
    else:
        print("Connected, but no datasets are visible in this project.")

    print(f"\nToken cached at: {config.TOKEN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
