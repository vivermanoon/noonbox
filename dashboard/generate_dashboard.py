#!/usr/bin/env python3
"""
generate_dashboard.py — rebuild the Retail Inventory & Ageing dashboard from
the flat table  noonbimerchsandbox.Vivek_test.rtl_invet_prov.

It produces two files next to the HTML template:
  * rtl_inventory_dashboard.html   (template with the aggregated `D` object injected)
  * skus.json                      (per-SKU worklist, loaded lazily by the dashboard)

Two ways to feed it the table (pick one with --source):

  # A) query BigQuery directly (needs `pip install google-cloud-bigquery`
  #    and Application Default Credentials, e.g. `gcloud auth application-default login`)
  python3 generate_dashboard.py --source bq

  # B) from an export you already pulled with the bq CLI (no python deps):
  bq query --use_legacy_sql=false --format=json --max_rows=100000000 \
     'SELECT * FROM `noonbimerchsandbox.Vivek_test.rtl_invet_prov`' > rows.json
  python3 generate_dashboard.py --source json --input rows.json

The `D` object and skus.json follow the exact contract the dashboard JS reads;
see README.md for the column map. Only aggregation happens here — no business
logic is duplicated: every per-SKU field (action, deal_tier, diagnosis, prices…)
is read straight from the table, which the SQL in ../sql/rtl_invet_prov.sql owns.
"""

import argparse
import json
import os
import sys

TABLE = "noonbimerchsandbox.Vivek_test.rtl_invet_prov"

# Canonical ageing-bucket order (matches BORDER in the dashboard).
BUCKET_ORDER = ['0-30', '31-60', '61-90', '91-120', '121-180',
                '181-270', '271-360', '361-540', '541-720', '721+']


# ----------------------------------------------------------------------------- helpers
def num(v):
    """Coerce a BQ value (Decimal, str, int, float, None) to float or None."""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ri(v):
    """Round to int (0 for None) — for summable money/count measures."""
    n = num(v)
    return int(round(n)) if n is not None else 0


def r2(v):
    """Round to 2dp, preserving None — for prices."""
    n = num(v)
    return round(n, 2) if n is not None else None


def r4(v):
    """Round to 4dp, preserving None — for ratios (sell-through, premium…)."""
    n = num(v)
    return round(n, 4) if n is not None else None


def as01(v):
    """Boolean-ish (bool / 'true' / 1) → 1/0."""
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, str):
        return 1 if v.strip().lower() in ('true', 't', '1', 'yes') else 0
    n = num(v)
    return 1 if (n or 0) != 0 else 0


def is_true(v):
    return as01(v) == 1


class Factor:
    """Assigns a stable integer index to each distinct value (first-seen order)."""
    def __init__(self):
        self.index = {}
        self.values = []

    def idx(self, v):
        v = '' if v is None else str(v)
        i = self.index.get(v)
        if i is None:
            i = len(self.values)
            self.index[v] = i
            self.values.append(v)
        return i


# ----------------------------------------------------------------------------- row sources
def rows_from_bq():
    from google.cloud import bigquery  # imported lazily so --source json needs no deps
    client = bigquery.Client()
    query = f"SELECT * FROM `{TABLE}`"
    print(f"  querying {TABLE} …", file=sys.stderr)
    for row in client.query(query).result():
        yield dict(row)


def rows_from_json(path):
    """Accept either a JSON array (bq --format=json) or newline-delimited JSON."""
    with open(path, 'r', encoding='utf-8') as fh:
        head = fh.read(1)
        fh.seek(0)
        if head == '[':
            for r in json.load(fh):
                yield r
        else:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


# ----------------------------------------------------------------------------- build
def build(rows):
    # shared dimension factorizations for D (tree / base / diagagg / dealagg)
    fCountry, fCluster, fC2, fCode = Factor(), Factor(), Factor(), Factor()
    fPtype, fBrand, fPartner, fBucket, fAction = Factor(), Factor(), Factor(), Factor(), Factor()

    # independent per-column factorizations for skus.json dims
    s_action, s_co, s_cl, s_c2, s_cc = Factor(), Factor(), Factor(), Factor(), Factor()
    s_pt, s_br, s_pn, s_bk, s_pos = Factor(), Factor(), Factor(), Factor(), Factor()
    s_deal, s_diag, s_sub, s_imprcat, s_convcat = Factor(), Factor(), Factor(), Factor(), Factor()

    tree = {}    # (co,cl,c2,cc,pt,br,pn,bucket,action) -> measures
    base = {}    # (co,cl,c2,cc,bucket,action) -> measures
    diag = {}    # (co,cl,c2,cc,diagnosis)  -> funnel measures
    deal = {}    # (co,cl,c2,cc,deal_tier)  -> funnel measures
    sku_rows = []
    run_date = None
    n_rows = 0

    def tree_slot():
        return {k: 0 for k in (
            'n', 'qty', 'cost', 'prov', 'nprov', 'stock', 'aged', 'units',
            'dead_n', 'dead_qty', 'dead_cost', 'dead_prov',
            'nl_n', 'nl_qty', 'nl_cost', 'nl_prov', 'gmv', 'live_n', 'darknp',
            't3_n', 't3_prov', 't2_n', 't2_prov', 't1_n', 't1_prov',
            'nonsal_n', 'nonsal_qty', 'nonsal_cost',
            'atcs', 'gvs', 'impr', 'live_days', 'sold_days', 'impr_days',
            'vis', 'conv', 'star')}

    def base_slot():
        return {k: 0 for k in (
            'n', 'qty', 'cost', 'prov', 'nprov', 'aged', 'stock', 'units',
            'gmv', 'liven', 'deadn', 'deadc', 'darkn', 'darkc', 'darknp')}

    def dd_slot():
        return {k: 0 for k in ('n', 'stock', 'cost', 'prov', 'gmv', 'units', 'impr', 'gvs', 'atcs')}

    for row in rows:
        n_rows += 1
        if run_date is None:
            run_date = row.get('date') or row.get('run_date')

        co = row.get('country')
        cl = row.get('cluster')
        c2 = row.get('comcat_2')
        cc = row.get('comcat_code')
        pt = row.get('product_type')
        br = row.get('brand_code')
        pn = row.get('id_partner')
        bucket = row.get('weighted_age_bucket')
        action = row.get('primary_action')
        diagnosis = row.get('category_diagnosis')
        tier = row.get('deal_tier')

        qty = ri(row.get('total_qty'))
        cost = ri(row.get('total_cost'))
        prov = ri(row.get('total_prov'))
        nprov = ri(row.get('next_prov'))
        stock = ri(row.get('current_stock'))
        aged = ri(row.get('aged_cost_gt_180'))
        units = ri(row.get('units'))
        gmv = ri(row.get('gmv'))
        impr = ri(row.get('impressions'))
        gvs = ri(row.get('gvs'))
        atcs = ri(row.get('atcs'))
        live_days = ri(row.get('live_days_l30d'))
        sold_days = ri(row.get('sold_days'))
        impr_days = ri(row.get('impr_days'))
        ns_qty = ri(row.get('non_saleable_qty'))
        ns_cost = ri(row.get('non_saleable_cost'))

        live = is_true(row.get('has_live_assortment'))
        dead = is_true(row.get('dead_stock_flag'))
        nonsal = is_true(row.get('is_non_saleable'))
        notlive = not live

        # ---- tree ----
        tk = (fCountry.idx(co), fCluster.idx(cl), fC2.idx(c2), fCode.idx(cc),
              fPtype.idx(pt), fBrand.idx(br), fPartner.idx(pn),
              fBucket.idx(bucket), fAction.idx(action))
        m = tree.get(tk)
        if m is None:
            m = tree[tk] = tree_slot()
        m['n'] += 1
        m['qty'] += qty; m['cost'] += cost; m['prov'] += prov; m['nprov'] += nprov
        m['stock'] += stock; m['aged'] += aged; m['units'] += units; m['gmv'] += gmv
        m['atcs'] += atcs; m['gvs'] += gvs; m['impr'] += impr
        m['live_days'] += live_days; m['sold_days'] += sold_days; m['impr_days'] += impr_days
        if dead:
            m['dead_n'] += 1; m['dead_qty'] += qty; m['dead_cost'] += cost; m['dead_prov'] += prov
        if notlive:
            m['nl_n'] += 1; m['nl_qty'] += qty; m['nl_cost'] += cost; m['nl_prov'] += prov
            m['darknp'] += nprov
        else:
            m['live_n'] += 1
        if tier == 'T3 - liquidate':
            m['t3_n'] += 1; m['t3_prov'] += prov
        elif tier == 'T2 - clear':
            m['t2_n'] += 1; m['t2_prov'] += prov
        elif tier == 'T1 - nudge':
            m['t1_n'] += 1; m['t1_prov'] += prov
        if nonsal:
            m['nonsal_n'] += 1; m['nonsal_qty'] += ns_qty; m['nonsal_cost'] += ns_cost
        if diagnosis:
            if diagnosis.startswith('Visibility gap'):
                m['vis'] += 1
            elif diagnosis.startswith('Conversion gap'):
                m['conv'] += 1
            elif diagnosis.startswith('Category star'):
                m['star'] += 1

        # ---- base (drives the global filter cascade) ----
        bk = (co, cl, c2, cc, bucket, action)
        b = base.get(bk)
        if b is None:
            b = base[bk] = base_slot()
        b['n'] += 1
        b['qty'] += qty; b['cost'] += cost; b['prov'] += prov; b['nprov'] += nprov
        b['aged'] += aged; b['stock'] += stock; b['units'] += units; b['gmv'] += gmv
        if live:
            b['liven'] += 1
        if dead:
            b['deadn'] += 1; b['deadc'] += cost
        if notlive:
            b['darkn'] += 1; b['darkc'] += cost; b['darknp'] += nprov

        # ---- diagagg / dealagg (category diagnosis & deal-tier funnel) ----
        for store, label in ((diag, diagnosis), (deal, tier)):
            key = (fCountry.idx(co), fCluster.idx(cl), fC2.idx(c2), fCode.idx(cc),
                   '' if label is None else str(label))
            o = store.get(key)
            if o is None:
                o = store[key] = dd_slot()
            o['n'] += 1; o['stock'] += stock; o['cost'] += cost; o['prov'] += prov
            o['gmv'] += gmv; o['units'] += units; o['impr'] += impr; o['gvs'] += gvs; o['atcs'] += atcs

        # ---- skus.json row (49 columns) ----
        sr = [0] * 49
        sr[0] = s_action.idx(action)
        sr[1] = s_co.idx(co)
        sr[2] = s_cl.idx(cl)
        sr[3] = s_c2.idx(c2)
        sr[4] = s_cc.idx(cc)
        sr[5] = s_pt.idx(pt)
        sr[6] = s_br.idx(br)
        sr[7] = s_pn.idx(pn)
        sr[8] = s_bk.idx(bucket)
        sr[9] = s_pos.idx(row.get('price_position'))
        sr[10] = ri(row.get('weighted_age_days'))
        sr[11] = cost
        sr[12] = nprov
        sr[13] = stock
        sr[14] = r2(row.get('offer_price'))
        sr[15] = r2(row.get('comp_price'))
        sr[16] = impr
        sr[17] = units
        sr[18] = r4(row.get('sell_through_30d'))
        sr[19] = r2(row.get('drr_units_l30d'))
        doc = num(row.get('days_of_cover'))
        sr[20] = int(round(doc)) if doc is not None else None
        sr[21] = row.get('sku')
        sr[22] = row.get('image_url') or ''
        sr[23] = row.get('title_en') or ''
        sr[24] = row.get('sku_url') or ''
        sr[25] = r4(row.get('price_premium_pct'))
        sr[26] = as01(row.get('has_live_assortment'))
        sr[27] = qty
        sr[28] = prov
        sr[29] = s_deal.idx(tier)
        sr[30] = s_diag.idx(diagnosis)
        sr[31] = r4(row.get('deal_discount_pct'))
        sr[32] = r2(row.get('recommended_deal_price'))
        sr[33] = r2(row.get('deal_floor_price'))
        sr[34] = s_sub.idx(row.get('product_subtype'))
        sr[35] = gmv
        sr[36] = gvs
        sr[37] = atcs
        sr[38] = live_days
        sr[39] = row.get('comp_seller') or ''
        sr[40] = as01(row.get('is_live'))
        sr[41] = as01(row.get('in_stock'))
        sr[42] = s_imprcat.idx(row.get('impr_vs_cat'))
        sr[43] = s_convcat.idx(row.get('conv_vs_cat'))
        sr[44] = 0
        sr[45] = 0
        sr[46] = ns_qty
        sr[47] = ns_cost
        sr[48] = as01(row.get('is_non_saleable'))
        sku_rows.append(sr)

    if n_rows == 0:
        raise SystemExit("No rows read from the table — check the source / export.")

    # ---- emit tree rows (46 columns) ----
    tree_out = []
    for k, m in tree.items():
        (i_co, i_cl, i_c2, i_cc, i_pt, i_br, i_pn, i_bk, i_ac) = k
        tree_out.append([
            i_co, i_cl, i_c2, i_cc, i_pt, i_br, i_pn, i_bk,        # 0-7 dims
            m['n'], m['qty'], m['cost'], m['prov'], m['nprov'],    # 8-12
            m['stock'], m['aged'], m['units'],                     # 13-15
            m['dead_n'], m['dead_qty'], m['dead_cost'], m['dead_prov'],   # 16-19
            m['nl_n'], m['nl_qty'], m['nl_cost'], m['nl_prov'],    # 20-23
            i_ac,                                                  # 24 action
            m['gmv'], m['live_n'], m['darknp'],                    # 25-27
            m['t3_n'], m['t3_prov'], m['t2_n'], m['t2_prov'],      # 28-31
            m['nonsal_n'], m['nonsal_qty'], m['nonsal_cost'],      # 32-34
            m['t1_n'], m['t1_prov'],                               # 35-36
            m['atcs'], m['gvs'], m['impr'],                        # 37-39 (funnel roll-up)
            m['live_days'], m['sold_days'], m['impr_days'],        # 40-42 (reserve)
            m['vis'], m['conv'], m['star'],                        # 43-45
        ])

    base_out = []
    for (co, cl, c2, cc, bucket, action), b in base.items():
        base_out.append({
            'co': co, 'cl': cl, 'c2': c2, 'cc': cc,
            'bk': bucket, 'ac': action,
            'n': b['n'], 'qty': b['qty'], 'cost': b['cost'], 'prov': b['prov'],
            'nprov': b['nprov'], 'aged': b['aged'], 'stock': b['stock'],
            'units': b['units'], 'gmv': b['gmv'], 'liven': b['liven'],
            'deadn': b['deadn'], 'deadc': b['deadc'],
            'darkn': b['darkn'], 'darkc': b['darkc'], 'darknp': b['darknp'],
        })

    def dd_out(store):
        out = []
        for (i_co, i_cl, i_c2, i_cc, label), o in store.items():
            out.append([i_co, i_cl, i_c2, i_cc, label,
                        o['n'], o['stock'], o['cost'], o['prov'], o['gmv'],
                        o['units'], o['impr'], o['gvs'], o['atcs']])
        return out

    D = {
        'run_date': str(run_date) if run_date is not None else '',
        'base': base_out,
        'treedims': {
            'country': fCountry.values,
            'cluster': fCluster.values,
            'comcat_2': fC2.values,
            'comcat_code': fCode.values,
            'product_type': fPtype.values,
            'brand_code': fBrand.values,
            'id_partner': fPartner.values,
            'bucket': fBucket.values,
            'action': fAction.values,
        },
        'tree': tree_out,
        'diagagg': dd_out(diag),
        'dealagg': dd_out(deal),
    }

    skus = {
        'base': '',    # image_url is stored whole in each row (col 22)
        'iurl': '',    # sku_url  is stored whole in each row (col 24)
        'dims': {
            'action': s_action.values, 'co': s_co.values, 'cl': s_cl.values,
            'c2': s_c2.values, 'cc': s_cc.values, 'pt': s_pt.values,
            'br': s_br.values, 'pn': s_pn.values, 'bk': s_bk.values,
            'pos': s_pos.values, 'deal_tier': s_deal.values, 'diag': s_diag.values,
            'subtype': s_sub.values, 'impr_cat': s_imprcat.values,
            'conv_cat': s_convcat.values,
        },
        'rows': sku_rows,
    }
    return D, skus, n_rows


# ----------------------------------------------------------------------------- main
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', choices=('bq', 'json'), default='bq',
                    help="'bq' queries BigQuery directly; 'json' reads --input.")
    ap.add_argument('--input', help="path to a JSON/NDJSON export of the table (for --source json).")
    ap.add_argument('--template', default=os.path.join(here, 'rtl_inventory_dashboard.template.html'))
    ap.add_argument('--out', default=os.path.join(here, 'rtl_inventory_dashboard.html'))
    ap.add_argument('--skus', default=os.path.join(here, 'skus.json'))
    ap.add_argument('--standalone', action='store_true',
                    help="Inline the SKU worklist into the HTML instead of writing skus.json — "
                         "produces one self-contained file that opens over file:// with no web server.")
    args = ap.parse_args()

    if args.source == 'json':
        if not args.input:
            ap.error('--source json requires --input <file>')
        rows = rows_from_json(args.input)
    else:
        rows = rows_from_bq()

    print("Building dashboard data …", file=sys.stderr)
    D, skus, n_rows = build(rows)

    with open(args.template, 'r', encoding='utf-8') as fh:
        template = fh.read()
    for token in ('__DASHBOARD_DATA__', '__SKUS_DATA__'):
        if token not in template:
            raise SystemExit(f"Template {args.template} has no {token} placeholder.")
    # separators without spaces keep the embedded blobs compact
    data_js = json.dumps(D, separators=(',', ':'), ensure_ascii=False)
    # --standalone inlines the SKU payload; otherwise it stays null and the page
    # lazily fetches skus.json (which we write alongside the HTML).
    skus_js = json.dumps(skus, separators=(',', ':'), ensure_ascii=False) if args.standalone else 'null'
    html = template.replace('__DASHBOARD_DATA__', data_js).replace('__SKUS_DATA__', skus_js)
    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(html)
    if not args.standalone:
        with open(args.skus, 'w', encoding='utf-8') as fh:
            json.dump(skus, fh, separators=(',', ':'), ensure_ascii=False)

    print(f"✓ {n_rows:,} table rows → "
          f"{len(D['tree']):,} tree groups, {len(D['base']):,} base groups, "
          f"{len(skus['rows']):,} SKU rows", file=sys.stderr)
    print(f"✓ wrote {args.out}" + (" (standalone — SKU data inlined)" if args.standalone
                                    else ""), file=sys.stderr)
    if not args.standalone:
        print(f"✓ wrote {args.skus}", file=sys.stderr)
    print(f"  run_date = {D['run_date']}", file=sys.stderr)


if __name__ == '__main__':
    main()
