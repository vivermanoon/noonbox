# Retail Inventory & Ageing — Deep-Dive Dashboard

A self-contained, single-page dashboard over retail inventory provisioning,
ageing, live assortment, competitor pricing, our funnel, and category
benchmarks — plus a per-SKU action / deal-tier / diagnosis engine.

Everything is driven by one flat BigQuery table:

```
noonbimerchsandbox.Vivek_test.rtl_invet_prov
```

This repo is the **reproducible pipeline** that rebuilds the dashboard from that
table for any `run_date`.

```
sql/rtl_invet_prov.sql                       # (1) builds the table
dashboard/generate_dashboard.py              # (2) table  →  dashboard data
dashboard/rtl_inventory_dashboard.template.html   # (3) HTML shell (data injected at build)
dashboard/start-dashboard.command            # (4) local web-server launcher
dashboard/requirements.txt
```

The generated `dashboard/rtl_inventory_dashboard.html` and `dashboard/skus.json`
are **not committed** (they embed a full data snapshot); regenerate them with
step 2 below.

---

## How to rebuild

### 1. Refresh the table (daily)

```bash
bq query --use_legacy_sql=false < sql/rtl_invet_prov.sql
```

`run_date` defaults to `CURRENT_DATE()`; the 30-day funnel window is
`run_date-30 … run_date-1`. Edit the `DECLARE`s at the top of the SQL to
backfill a specific date.

### 2. Generate the dashboard from the table

Two ways to feed the table to the generator — pick whichever fits your access.

**A. Query BigQuery directly** (needs the client lib + credentials):

```bash
pip install -r dashboard/requirements.txt
gcloud auth application-default login          # once
python3 dashboard/generate_dashboard.py --source bq
```

**B. From a `bq` CLI export** (no Python deps, no ADC):

```bash
bq query --use_legacy_sql=false --format=json --max_rows=100000000 \
  'SELECT * FROM `noonbimerchsandbox.Vivek_test.rtl_invet_prov`' > dashboard/rows.json
python3 dashboard/generate_dashboard.py --source json --input dashboard/rows.json
```

Either path writes `dashboard/rtl_inventory_dashboard.html` (the shell with the
aggregated `D` object inlined) and `dashboard/skus.json` (the per-SKU worklist).

### 3. View it

```bash
dashboard/start-dashboard.command       # serves over http://localhost:8777 and opens a browser
```

A local web server is required: the **SKU Worklist** and **SKU Critique** tabs
`fetch('skus.json')`, which browsers block over `file://`. The Overview, Ageing
Drilldown, Action Center, and Playbook tabs work from the inlined `D` alone.

---

## What the dashboard shows

| Tab | Content |
|-----|---------|
| **Overview** | KPI band (inventory cost, aged >180d, provision booked & next-month, non-saleable, dark stock, dead stock, live coverage, GMV), cluster table, ageing-bucket stack, action-risk bars, 5 cross-filtering dimension cards, and category-diagnosis / deal-tier performance. |
| **Ageing Drilldown** | Collapsible tree: country ▸ cluster ▸ comcat_2 ▸ comcat_code ▸ product_type ▸ brand ▸ partner, measured by cost / provision / next-prov / qty, with aged-% and sell-through. |
| **Action Center** | One card per `primary_action` with next-provision by cluster and the play-book; deal-tier provision draw-down and category-diagnosis tables; product_type / brand filters. |
| **SKU Worklist** | Virtualised per-SKU table (images, funnel, pricing, per-unit economics, deal engine, category benchmark) with column groups, multi-select filters, and sort. |
| **SKU Critique** | Per-SKU days-of-cover + pricing critique engine → a recommended action per SKU, ranked by severity × next-provision. |
| **Playbook & Gaps** | Operating narrative, decision lens by cluster, life-stage playbook, caveats. |

Global country / cluster / comcat_2 / comcat_code filters cascade across every tab.

---

## Data contract (for maintainers)

The generator only **aggregates and factorizes** — no business logic is
re-implemented. Every per-SKU field (action, deal tier, diagnosis, prices,
flags) is read straight from `rtl_invet_prov`, which `sql/rtl_invet_prov.sql`
owns. If you change a column name or a derived field in the SQL, update the
matching lookup in `generate_dashboard.py`.

### `D` (inlined into the HTML)

- `run_date` — the table's `date` / `run_date`.
- `treedims` — value lists (index → label) shared by `tree`, `diagagg`, `dealagg`:
  `country, cluster, comcat_2, comcat_code, product_type, brand_code, id_partner, bucket, action`.
- `base` — objects at **country × cluster × comcat_2 × comcat_code × bucket ×
  action** grain; drives the global filter-option cascade (`co, cl, c2, cc, bk,
  ac` are raw strings).
- `tree` — 46-column arrays at **…× product_type × brand_code × id_partner ×
  bucket × action** grain. Columns 0–7 are dimension indices, 24 is the action
  index; the rest are summed measures (see the header comments and `tree_out`
  in the generator for the full 0–45 map).
- `diagagg` / `dealagg` — 14-column arrays at **country × cluster × comcat_2 ×
  comcat_code × (category_diagnosis | deal_tier)** grain. Cols 0–3 are dim
  indices, col 4 is the diagnosis / tier **string**, cols 5–13 are
  `n, stock, cost, prov, gmv, units, impr, gvs, atcs`.

### `skus.json` (fetched lazily by the two SKU tabs)

- `rows` — one 49-column array per table row (SKU × partner × country).
  Dimension columns (`0,1,2,3,4,5,6,7,8,9,29,30,34,42,43`) are indices into
  `dims`; the rest are numeric measures / prices / flags / strings. The exact
  index map is in `generate_dashboard.py` (`sku.json row` block) and mirrors the
  `WCOLS` / `CCOLS` / `critOne` / `pu` / `nonsal` readers in the HTML.
- `dims` — per-column value lists: `action, co, cl, c2, cc, pt, br, pn, bk, pos,
  deal_tier, diag, subtype, impr_cat, conv_cat`.
- `base` / `iurl` — prefixes prepended to the image and product-URL columns
  (empty here; each row already carries the full `image_url` and `sku_url`).

---

## Notes & caveats (carried from the analysis)

- Funnel metrics are **allocated** from offer-level to SKU by exposure — directional.
- `current_stock` (live assortment) ≠ `total_qty` (provisioning); the gap is the
  **dark-stock / non-saleable** signal.
- DRR uses a live → sold → impression-day fallback; check `drr_basis` on thin SKUs.
- Comp coverage is partial — SKUs without a comp price are price-blind (`no_comp`).
