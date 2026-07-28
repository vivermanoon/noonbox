#!/bin/bash
# One-command build of the standalone dashboard from the live table.
# Run this in an environment where the `bq` CLI is authenticated (your
# bq-connected shell). It exports the table, then inlines all data into a
# single self-contained HTML — no skus.json, no web server needed to view it.
#
#   bash dashboard/build.sh
#
set -euo pipefail
cd "$(dirname "$0")"

TABLE="noonbimerchsandbox.Vivek_test.rtl_invet_prov"
ROWS="rows.json"
OUT="rtl_inventory_dashboard.html"

echo "→ exporting ${TABLE} …"
# bq paginates automatically, so this streams the full result set to a file.
bq query --use_legacy_sql=false --format=json --max_rows=100000000 \
  "SELECT * FROM \`${TABLE}\`" > "${ROWS}"

echo "→ building standalone dashboard …"
python3 generate_dashboard.py --source json --input "${ROWS}" --standalone --out "${OUT}"

echo
echo "✓ Done. Open ${PWD}/${OUT} in any browser (double-click works — it's self-contained)."
echo "  (delete ${ROWS} when finished; it's the raw export.)"
