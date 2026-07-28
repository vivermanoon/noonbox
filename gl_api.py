#!/usr/bin/env python3
"""Call the GitLab REST API from the command line.

Examples:
    python gl_api.py /user
    python gl_api.py /projects --param membership=true --param per_page=5
    python gl_api.py /projects/123/issues --param state=opened
    python gl_api.py --method list /groups
"""

from __future__ import annotations

import argparse
import json
import sys

from glconnect import config
from glconnect.query import fetch


def _parse_params(pairs: list[str] | None) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--param expects key=value, got: {pair!r}")
        key, _, value = pair.partition("=")
        params[key.strip()] = value.strip()
    return params


def main() -> int:
    parser = argparse.ArgumentParser(description="Call the GitLab REST API.")
    parser.add_argument("path", help="API path relative to /api/v4, e.g. /user")
    parser.add_argument(
        "--param",
        "-p",
        action="append",
        metavar="KEY=VALUE",
        help="Query parameter (repeatable).",
    )
    parser.add_argument(
        "--method",
        "-m",
        default="get",
        help="get (default), list (auto-paginate), post, put, delete.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=50,
        help="Max list items to print (default: 50).",
    )
    args = parser.parse_args()

    print(f"GitLab: {config.GITLAB_URL}", file=sys.stderr)
    result = fetch(args.path, params=_parse_params(args.param), method=args.method)

    if isinstance(result, list) and len(result) > args.max_rows:
        print(
            f"... showing first {args.max_rows} of {len(result)} items",
            file=sys.stderr,
        )
        result = result[: args.max_rows]

    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
