#!/usr/bin/env python3
"""Run a SQL query against BigQuery from the command line.

Examples:
    python bq_query.py "SELECT 1 AS one"
    python bq_query.py --file query.sql
    python bq_query.py --dry-run "SELECT * FROM \`noonbimerch.dataset.table\`"
    echo "SELECT CURRENT_DATE() AS today" | python bq_query.py -
"""

from __future__ import annotations

import argparse
import sys

from bqconnect import config
from bqconnect.query import run_query


def _read_sql(args: argparse.Namespace) -> str:
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            return fh.read()
    if args.sql == "-":
        return sys.stdin.read()
    return args.sql


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SQL against BigQuery.")
    parser.add_argument("sql", nargs="?", help="SQL string, or '-' to read stdin.")
    parser.add_argument("--file", "-f", help="Read SQL from this file instead.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and estimate bytes scanned without running the query.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=50,
        help="Max rows to print (default: 50).",
    )
    args = parser.parse_args()

    if not args.sql and not args.file:
        parser.error("provide a SQL string, --file, or '-' for stdin")

    sql = _read_sql(args)
    print(f"Project: {config.PROJECT}", file=sys.stderr)

    if args.dry_run:
        job = run_query(sql, dry_run=True)
        gib = (job.total_bytes_processed or 0) / (1024**3)
        print(f"Dry run OK. Would scan ~{gib:.3f} GiB.", file=sys.stderr)
        return 0

    rows = run_query(sql)
    fields = [f.name for f in rows.schema]
    print("\t".join(fields))
    for i, row in enumerate(rows):
        if i >= args.max_rows:
            print(f"... (truncated at {args.max_rows} rows)", file=sys.stderr)
            break
        print("\t".join("" if row[f] is None else str(row[f]) for f in fields))
    return 0


if __name__ == "__main__":
    sys.exit(main())
