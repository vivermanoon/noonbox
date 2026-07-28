#!/bin/bash
# Launch the Retail Inventory dashboard over a local web server (needed for the
# SKU Worklist / Critique tabs, which load skus.json — browsers block that over file://).
cd "$(dirname "$0")"

if [ ! -f rtl_inventory_dashboard.html ] || [ ! -f skus.json ]; then
  echo "rtl_inventory_dashboard.html / skus.json not found."
  echo "Generate them first, e.g.:"
  echo "    python3 generate_dashboard.py --source bq"
  echo "(see README.md for the --source json alternative)"
  exit 1
fi

PORT=8777
python3 -m http.server $PORT >/dev/null 2>&1 &
SRV=$!
sleep 1
URL="http://localhost:$PORT/rtl_inventory_dashboard.html"
# open the default browser (macOS: open, Linux: xdg-open)
(command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true
echo "Dashboard running at $URL"
echo "Close this Terminal window (or press Ctrl+C) to stop the server."
trap "kill $SRV 2>/dev/null" EXIT
wait $SRV
