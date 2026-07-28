"""Run SQL against BigQuery and get results back as rows or a DataFrame."""

from __future__ import annotations

from typing import Any

from google.cloud import bigquery

from .client import get_client


def run_query(
    sql: str,
    *,
    params: dict[str, Any] | None = None,
    client: bigquery.Client | None = None,
    dry_run: bool = False,
) -> bigquery.table.RowIterator:
    """Execute ``sql`` and return the result iterator.

    Pass ``params`` for parameterized queries, e.g.::

        run_query("SELECT * FROM t WHERE country = @c", params={"c": "AE"})

    Set ``dry_run=True`` to validate the query and get the bytes-scanned
    estimate without actually running (or being billed for) it.
    """
    client = client or get_client()

    job_config = bigquery.QueryJobConfig(dry_run=dry_run, use_query_cache=not dry_run)
    if params:
        job_config.query_parameters = [
            _to_query_parameter(name, value) for name, value in params.items()
        ]

    job = client.query(sql, job_config=job_config)
    if dry_run:
        return job  # QueryJob; inspect job.total_bytes_processed
    return job.result()


def _to_query_parameter(name: str, value: Any) -> bigquery.ScalarQueryParameter:
    type_map = {
        bool: "BOOL",
        int: "INT64",
        float: "FLOAT64",
        str: "STRING",
    }
    bq_type = type_map.get(type(value), "STRING")
    return bigquery.ScalarQueryParameter(name, bq_type, value)
