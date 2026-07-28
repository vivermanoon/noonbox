-- =====================================================================
-- rtl_invet_prov  —  Retail Inventory & Ageing provisioning base table
-- =====================================================================
-- Rebuilds noonbimerchsandbox.Vivek_test.rtl_invet_prov, the single flat
-- table that powers the Retail Inventory & Ageing dashboard.
--
-- Grain: one row per (country, nub_code, comcat_2, comcat_code,
--        product_type, product_subtype, brand_code, sku, id_partner).
--
-- The table joins, per SKU/partner/country:
--   * inventory provisioning  (qty, cost, provision, ageing buckets)
--   * live assortment         (stock, offer price, is_live)  — noon + rocket
--   * competitor price        (lowest comp)
--   * our retail funnel L30D   (impressions/gvs/atcs/units/gmv, DRR)
--   * category-wide benchmark  (subtype→product_type percentile bands)
-- and derives the per-SKU action, deal tier, and category diagnosis the
-- dashboard reads directly. Re-run daily; run_date defaults to today.
-- =====================================================================

DECLARE run_date     DATE  DEFAULT CURRENT_DATE();
DECLARE window_start DATE  DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
DECLARE window_end   DATE  DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
DECLARE min_bench_n  INT64 DEFAULT 20;    -- subtype needs >=20 qualified SKUs, else fall back to product_type

CREATE OR REPLACE TABLE `noonbimerchsandbox.Vivek_test.rtl_invet_prov` AS
WITH
partner_base AS (
  SELECT DISTINCT id_partner
  FROM `noonbicedata.cogs_v3.retail_partner_ids`
  WHERE partner_override_nub_code_v2 IN ('nub_noon','nub_privatelabel','nub_cocoblu','nub_unknown')
),
catalog_slim AS (
  SELECT sku, sku_config, comcat_2, comcat_code, product_type, product_subtype, brand_code
  FROM `noonbigrowth.assortment_noon.catalog`
),
cat_by_sku AS (
  SELECT sku, ANY_VALUE(comcat_2) comcat_2, ANY_VALUE(comcat_code) comcat_code,
         ANY_VALUE(product_type) product_type, ANY_VALUE(product_subtype) product_subtype, ANY_VALUE(brand_code) brand_code
  FROM catalog_slim GROUP BY sku
),

bridge as (
  select zsku_child, min(nsku_child) as nsku_child
  from `noonbicedata.comcat_v2_staging.psku_content_sku`
  where zsku_child is not null
    and nsku_child is not null
    and zsku_child != nsku_child
  group by 1
),

cat_by_code AS (SELECT comcat_code, ANY_VALUE(comcat_2) comcat_2 FROM catalog_slim GROUP BY comcat_code),
cfg_map  AS (SELECT DISTINCT sku, sku_config FROM catalog_slim WHERE sku_config IS NOT NULL),
cfg_attr AS (   -- full hierarchy per sku_config, to disambiguate subtype/ptype by parent
  SELECT sku_config,
         ANY_VALUE(comcat_code)     ccode,
         ANY_VALUE(product_type)    ptype,
         ANY_VALUE(product_subtype) subtype
  FROM catalog_slim WHERE sku_config IS NOT NULL GROUP BY sku_config
),

temp AS (
  SELECT
    country, nub_code,
    COALESCE(b.comcat_2, c.comcat_2, cc.comcat_2)      AS comcat_2,
    COALESCE(b.comcat_code, c.comcat_code)             AS comcat_code,
    COALESCE(b.product_type, c.product_type)           AS product_type,
    c.product_subtype                                  AS product_subtype,
    COALESCE(b.brand_code, c.brand_code)               AS brand_code,
    sku, id_partner,
    SUM(qty) AS total_qty,
    ROUND(SUM(total_cost_aed), 2)           AS total_cost,
    ROUND(SUM(total_provision_aed), 2)      AS total_prov,
    ROUND(SUM(next_month_provision_aed), 2) AS next_prov,
    ROUND(SAFE_DIVIDE(SUM(qty * CASE ageing_bucket
      WHEN '0-30' THEN 15 WHEN '31-60' THEN 45 WHEN '61-90' THEN 75
      WHEN '91-120' THEN 105 WHEN '121-180' THEN 150 WHEN '181-270' THEN 225
      WHEN '271-360' THEN 315 WHEN '361-540' THEN 450 WHEN '541-720' THEN 630
      ELSE 900 END), SUM(qty)), 0) AS weighted_age_days,
    MAX(CASE ageing_bucket
      WHEN '0-30' THEN 1 WHEN '31-60' THEN 2 WHEN '61-90' THEN 3 WHEN '91-120' THEN 4
      WHEN '121-180' THEN 5 WHEN '181-270' THEN 6 WHEN '271-360' THEN 7 WHEN '361-540' THEN 8
      WHEN '541-720' THEN 9 ELSE 10 END) AS max_bucket_ord,
    COUNT(DISTINCT ageing_bucket) AS num_buckets,
    SUM(CASE WHEN ageing_bucket IN ('0-30','31-60','61-90','91-120','121-180') THEN 0 ELSE qty END) AS qty_aged_gt_180,
    ROUND(SUM(CASE WHEN ageing_bucket IN ('0-30','31-60','61-90','91-120','121-180') THEN 0 ELSE total_cost_aed END), 2) AS aged_cost_gt_180
  FROM `noonbigrowth.commercial_supply_v2.inventory_provisions` b
  JOIN partner_base USING(id_partner)
  LEFT JOIN cat_by_sku  c  USING(sku)
  LEFT JOIN cat_by_code cc ON b.comcat_code = cc.comcat_code
  WHERE date = run_date AND country IN ('AE','SA')
    AND nub_code IN ('nub_noon','nub_privatelabel','nub_cocoblu','nub_unknown')
    and id_partner not in (9303,9403,1437,9405,9505,476694, 508309)
  GROUP BY 1,2,3,4,5,6,7,8,9
),

-- live assortment (is_live=1, no stock filter → keeps live-but-OOS)
sm_assort AS (
  SELECT country, sku, id_partner, SUM(stock_net) AS current_stock,
         ROUND(SAFE_DIVIDE(SUM(offer_price*stock_net), NULLIF(SUM(stock_net),0)),2) AS offer_price, MAX(is_live) is_live
  FROM `noonbigrowth.assortment_rocket.psku_sku_mapped_*`
  JOIN partner_base USING(id_partner)
  WHERE date = run_date AND country IN ('AE','SA') AND is_live = 1
  GROUP BY country, sku, id_partner
),
noon_assort AS (
  SELECT country, sku, id_partner, SUM(stock_net) AS current_stock,
         ROUND(SAFE_DIVIDE(SUM(offer_price*stock_net), NULLIF(SUM(stock_net),0)),2) AS offer_price, MAX(is_live) is_live
  FROM `noonbigrowth.assortment_noon.psku_sku_mapped_*`
  JOIN partner_base USING(id_partner)
  WHERE date = run_date AND country IN ('AE','SA') AND id_mp = 1 AND is_live = 1 AND is_active = 1
  GROUP BY country, sku, id_partner
),
assort AS (
  SELECT country, sku, id_partner, SUM(current_stock) AS current_stock,
         ROUND(SAFE_DIVIDE(SUM(offer_price*current_stock), NULLIF(SUM(current_stock),0)),2) AS offer_price, MAX(is_live) is_live
  FROM (SELECT * FROM sm_assort UNION ALL SELECT * FROM noon_assort)
  GROUP BY country, sku, id_partner
),
assort_z AS (   -- combined live assortment, stock-weighted price, deduped per (country,sku,partner), bridged to zsku
  select distinct country, coalesce(bridge.zsku_child,p.sku)sku,  id_partner, current_stock, offer_price,is_live
  from
  (SELECT country, sku, id_partner,
         SUM(current_stock) AS current_stock,
         ROUND(SAFE_DIVIDE(SUM(offer_price * current_stock), NULLIF(SUM(current_stock),0)), 2) AS offer_price,
         MAX(is_live) AS is_live
  FROM (SELECT * FROM sm_assort UNION ALL SELECT * FROM noon_assort)
  GROUP BY all
)p
left join bridge on bridge.nsku_child=p.sku
),

comp AS (
  SELECT country, sku, effective_comp_price AS comp_price, comp_seller_name AS comp_seller,
         is_comparable AS comp_is_comparable, is_outlier AS comp_is_outlier
  FROM `noonbigrowth.comp_noon_v2.lowest_comp_price`
  WHERE date = run_date AND country IN ('AE','SA') AND effective_comp_price IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY country, sku ORDER BY effective_comp_price ASC) = 1
),

-- ===== our retail funnel (partner-filtered), allocated to SKU =====
funnel_matrix AS (
  WITH
  offer_perf AS (
    SELECT country, offer_code, id_partner, SUM(impressions) impressions, SUM(gvs) gvs, SUM(atcs) atcs,
           COUNT(DISTINCT IF(impressions>0 OR gvs>0, date, NULL)) impr_days
    FROM `noonbione.category_analytics.sku_performance_2026*`
    JOIN partner_base USING(id_partner)
    WHERE _table_suffix BETWEEN format_date("%m%d", window_start) AND format_date("%m%d", window_end) AND country IN ('AE','SA')
    GROUP BY country, offer_code, id_partner
  ),
  sales AS (
    SELECT s.country, s.offer_code, s.sku_original AS sku, s.id_partner,
           SUM(gmv_aed) gmv, SUM(units_sold) units, COUNT(DISTINCT order_pdate) sold_days
    FROM `noonbigmktg.reporting_noon.sales_complete` s
    JOIN partner_base USING(id_partner)
    WHERE s.country IN ('AE','SA') AND id_mp=1 AND order_pdate BETWEEN window_start AND window_end
    GROUP BY s.country, s.offer_code, s.sku_original, s.id_partner
  ),
  live AS (
    SELECT country, offer_code, sku, id_partner, SUM(is_live) live_days_l30d
    FROM `noonbione.category_analytics.sku_live_status_daily`
    JOIN partner_base USING(id_partner)
    WHERE date BETWEEN window_start AND window_end AND country IN ('AE','SA')
    GROUP BY country, offer_code, sku, id_partner
  ),
  sku_offer_base AS (
    SELECT COALESCE(l.country,s.country) country, COALESCE(l.offer_code,s.offer_code) offer_code,
           COALESCE(l.sku,s.sku) sku, COALESCE(l.id_partner,s.id_partner) id_partner,
           COALESCE(l.live_days_l30d,0) live_days_l30d, COALESCE(s.gmv,0) gmv, COALESCE(s.units,0) units, COALESCE(s.sold_days,0) sold_days
    FROM live l FULL OUTER JOIN sales s USING(country, offer_code, sku, id_partner)
  ),
  allocated AS (
    SELECT b.*, p.impressions offer_impr, p.gvs offer_gvs, p.atcs offer_atcs, p.impr_days offer_impr_days,
      COALESCE(SAFE_DIVIDE(b.live_days_l30d, NULLIF(SUM(b.live_days_l30d) OVER w,0)), SAFE_DIVIDE(1, COUNT(*) OVER w)) alloc_w
    FROM sku_offer_base b LEFT JOIN offer_perf p USING(country, offer_code, id_partner)
    WINDOW w AS (PARTITION BY b.country, b.offer_code, b.id_partner)
  )
  SELECT country, sku, id_partner, SUM(gmv) gmv, SUM(units) units,
    SUM(offer_impr*alloc_w) impressions, SUM(offer_gvs*alloc_w) gvs, SUM(offer_atcs*alloc_w) atcs,
    MAX(live_days_l30d) live_days_l30d, MAX(sold_days) sold_days, MAX(offer_impr_days) impr_days,
    COALESCE(NULLIF(GREATEST(MAX(live_days_l30d),MAX(sold_days)),0), NULLIF(MAX(offer_impr_days),0)) drr_days_basis,
    SAFE_DIVIDE(SUM(units), COALESCE(NULLIF(GREATEST(MAX(live_days_l30d),MAX(sold_days)),0), NULLIF(MAX(offer_impr_days),0))) drr_units_l30d,
    CASE WHEN MAX(live_days_l30d)>=MAX(sold_days) AND MAX(live_days_l30d)>0 THEN 'live'
         WHEN MAX(sold_days)>0 THEN 'sold_days' WHEN MAX(offer_impr_days)>0 THEN 'impression_days_fallback' ELSE 'none' END drr_basis
  FROM allocated GROUP BY country, sku, id_partner
),

-- ===== CATEGORY-WIDE benchmark (ALL sellers, not just our partners) =====
cat_perf AS (   -- funnel at sku_config grain, all sellers
  SELECT country, sku_config, SUM(impressions) impr, SUM(gvs) gvs, SUM(atcs) atc
  FROM `noonbione.category_analytics.sku_performance_2026*`
  WHERE _table_suffix BETWEEN format_date("%m%d", window_start) AND format_date("%m%d", window_end)
    AND country IN ('AE','SA') AND sku_config IS NOT NULL
  GROUP BY country, sku_config
),
cat_sales AS (  -- sales rolled from sku -> sku_config, all sellers
  SELECT s.country, m.sku_config, SUM(s.gmv_aed) gmv, SUM(s.units_sold) units
  FROM `noonbigmktg.reporting_noon.sales_complete` s
  JOIN cfg_map m ON s.sku_original = m.sku
  WHERE s.country IN ('AE','SA') AND s.id_mp=1 AND s.order_pdate BETWEEN window_start AND window_end
  GROUP BY s.country, m.sku_config
),
cat_sku AS (    -- one row per category sku_config, active in L30; carries comcat_code + ptype for disambiguation
  SELECT COALESCE(p.country,s.country) country, COALESCE(p.sku_config,s.sku_config) sku_config,
         a.ccode, a.ptype, a.subtype,
         COALESCE(p.impr,0) impr, COALESCE(p.gvs,0) gvs, COALESCE(p.atc,0) atc,
         COALESCE(s.gmv,0) gmv, COALESCE(s.units,0) units
  FROM cat_perf p FULL OUTER JOIN cat_sales s USING(country, sku_config)
  LEFT JOIN cfg_attr a USING(sku_config)
  WHERE COALESCE(p.impr,0)>0 OR COALESCE(s.units,0)>0
),
-- SUBTYPE-RELATIVE impression floor: p25 of impressions among visible (impr>0) configs, within each group.
-- Adapts the "real competitor" bar to each shelf's own demand level.
sub_floor AS (
  SELECT country, ccode, ptype, subtype,
    APPROX_QUANTILES(IF(impr>0, impr, NULL), 4)[OFFSET(1)] impr_floor
  FROM cat_sku WHERE subtype IS NOT NULL GROUP BY country, ccode, ptype, subtype
),
pty_floor AS (
  SELECT country, ccode, ptype,
    APPROX_QUANTILES(IF(impr>0, impr, NULL), 4)[OFFSET(1)] impr_floor
  FROM cat_sku WHERE ptype IS NOT NULL GROUP BY country, ccode, ptype
),
-- subtype benchmark keyed by (country, comcat_code, product_type, subtype).
-- Population: impr/conv over configs with impr >= subtype p25-floor; units/gmv over configs that actually sold.
subtype_bench AS (
  SELECT cs.country, cs.ccode, cs.ptype, cs.subtype,
    COUNTIF(cs.impr>=f.impr_floor OR cs.units>=1) n_sku,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.impr,NULL),4)[OFFSET(1)] impr_p25,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.impr,NULL),4)[OFFSET(2)] impr_p50,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.impr,NULL),4)[OFFSET(3)] impr_p75,
    APPROX_QUANTILES(IF(cs.units>=1,cs.units,NULL),4)[OFFSET(1)] u_p25,
    APPROX_QUANTILES(IF(cs.units>=1,cs.units,NULL),4)[OFFSET(2)] u_p50,
    APPROX_QUANTILES(IF(cs.units>=1,cs.units,NULL),4)[OFFSET(3)] u_p75,
    APPROX_QUANTILES(IF(cs.units>=1,cs.gmv,NULL),4)[OFFSET(1)] gmv_p25,
    APPROX_QUANTILES(IF(cs.units>=1,cs.gmv,NULL),4)[OFFSET(2)] gmv_p50,
    APPROX_QUANTILES(IF(cs.units>=1,cs.gmv,NULL),4)[OFFSET(3)] gmv_p75,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.gvs,NULL),4)[OFFSET(2)] gvs_p50,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.atc,NULL),4)[OFFSET(2)] atc_p50,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,SAFE_DIVIDE(cs.units,cs.impr),NULL),4)[OFFSET(1)] conv_p25,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,SAFE_DIVIDE(cs.units,cs.impr),NULL),4)[OFFSET(3)] conv_p75
  FROM cat_sku cs
  JOIN sub_floor f ON f.country=cs.country AND f.ccode=cs.ccode AND f.ptype=cs.ptype AND f.subtype=cs.subtype
  WHERE cs.subtype IS NOT NULL
  GROUP BY cs.country, cs.ccode, cs.ptype, cs.subtype
),
ptype_bench AS (  -- fallback for thin subtypes, keyed by (country, comcat_code, product_type)
  SELECT cs.country, cs.ccode, cs.ptype,
    COUNTIF(cs.impr>=f.impr_floor OR cs.units>=1) n_sku,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.impr,NULL),4)[OFFSET(1)] impr_p25,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.impr,NULL),4)[OFFSET(2)] impr_p50,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.impr,NULL),4)[OFFSET(3)] impr_p75,
    APPROX_QUANTILES(IF(cs.units>=1,cs.units,NULL),4)[OFFSET(1)] u_p25,
    APPROX_QUANTILES(IF(cs.units>=1,cs.units,NULL),4)[OFFSET(2)] u_p50,
    APPROX_QUANTILES(IF(cs.units>=1,cs.units,NULL),4)[OFFSET(3)] u_p75,
    APPROX_QUANTILES(IF(cs.units>=1,cs.gmv,NULL),4)[OFFSET(1)] gmv_p25,
    APPROX_QUANTILES(IF(cs.units>=1,cs.gmv,NULL),4)[OFFSET(2)] gmv_p50,
    APPROX_QUANTILES(IF(cs.units>=1,cs.gmv,NULL),4)[OFFSET(3)] gmv_p75,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.gvs,NULL),4)[OFFSET(2)] gvs_p50,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,cs.atc,NULL),4)[OFFSET(2)] atc_p50,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,SAFE_DIVIDE(cs.units,cs.impr),NULL),4)[OFFSET(1)] conv_p25,
    APPROX_QUANTILES(IF(cs.impr>=f.impr_floor,SAFE_DIVIDE(cs.units,cs.impr),NULL),4)[OFFSET(3)] conv_p75
  FROM cat_sku cs
  JOIN pty_floor f ON f.country=cs.country AND f.ccode=cs.ccode AND f.ptype=cs.ptype
  WHERE cs.ptype IS NOT NULL
  GROUP BY cs.country, cs.ccode, cs.ptype
),
bench AS (       -- one row per (country, comcat_code, ptype, subtype) with subtype→product_type fallback applied
  SELECT sb.country, sb.ccode, sb.ptype, sb.subtype, sb.n_sku, sb.gmv_p50,
    IF(sb.n_sku>=min_bench_n, sb.impr_p25, pb.impr_p25) impr_p25, IF(sb.n_sku>=min_bench_n, sb.impr_p75, pb.impr_p75) impr_p75,
    IF(sb.n_sku>=min_bench_n, sb.u_p25,   pb.u_p25)   u_p25,   IF(sb.n_sku>=min_bench_n, sb.u_p75,   pb.u_p75)   u_p75,
    IF(sb.n_sku>=min_bench_n, sb.gmv_p25, pb.gmv_p25) gmv_p25, IF(sb.n_sku>=min_bench_n, sb.gmv_p75, pb.gmv_p75) gmv_p75,
    IF(sb.n_sku>=min_bench_n, sb.conv_p25,pb.conv_p25) conv_p25, IF(sb.n_sku>=min_bench_n, sb.conv_p75,pb.conv_p75) conv_p75,
    IF(sb.n_sku>=min_bench_n, 'subtype','product_type') bench_grain
  FROM subtype_bench sb
  LEFT JOIN ptype_bench pb ON pb.country=sb.country AND pb.ccode=sb.ccode AND pb.ptype=sb.ptype
),

enriched AS (
  SELECT
    ip.*,
    CASE WHEN weighted_age_days<=30 THEN '0-30' WHEN weighted_age_days<=60 THEN '31-60'
      WHEN weighted_age_days<=90 THEN '61-90' WHEN weighted_age_days<=120 THEN '91-120'
      WHEN weighted_age_days<=180 THEN '121-180' WHEN weighted_age_days<=270 THEN '181-270'
      WHEN weighted_age_days<=360 THEN '271-360' WHEN weighted_age_days<=540 THEN '361-540'
      WHEN weighted_age_days<=720 THEN '541-720' ELSE '721+' END AS weighted_age_bucket,
    CASE WHEN weighted_age_days<=30 THEN 1 WHEN weighted_age_days<=60 THEN 2 WHEN weighted_age_days<=90 THEN 3
      WHEN weighted_age_days<=120 THEN 4 WHEN weighted_age_days<=180 THEN 5 WHEN weighted_age_days<=270 THEN 6
      WHEN weighted_age_days<=360 THEN 7 WHEN weighted_age_days<=540 THEN 8 WHEN weighted_age_days<=720 THEN 9 ELSE 10 END AS weighted_bucket_ord,
    coalesce(a.offer_price,az.offer_price)offer_price,
    COALESCE(coalesce(a.is_live,az.is_live),0)=1 AS has_live_assortment,
    COALESCE(coalesce(a.is_live,az.is_live),0)   AS is_live,
    COALESCE(coalesce(a.current_stock,az.current_stock),0) AS current_stock,
    (COALESCE(coalesce(a.current_stock,az.current_stock),0)>0) AS in_stock,
    cp.comp_price, cp.comp_seller, cp.comp_is_comparable, cp.comp_is_outlier,
    COALESCE(f.impressions,0) impressions, COALESCE(f.gvs,0) gvs, COALESCE(f.atcs,0) atcs,
    COALESCE(f.units,0) units, COALESCE(f.gmv,0) gmv,
    COALESCE(f.live_days_l30d,0) live_days_l30d, COALESCE(f.impr_days,0) impr_days, COALESCE(f.sold_days,0) sold_days,
    COALESCE(f.drr_days_basis,0) drr_days_basis, COALESCE(f.drr_units_l30d,0) drr_units_l30d, COALESCE(f.drr_basis,'none') drr_basis,
    b.bench_grain, b.n_sku AS bench_n_sku,
    b.impr_p25, b.impr_p75, b.u_p25, b.u_p75, b.gmv_p25, b.gmv_p75, b.conv_p25, b.conv_p75
  FROM temp ip
  LEFT JOIN assort        a  USING(country, id_partner, sku)
  LEFT JOIN assort_z      az USING(country, id_partner, sku)
  LEFT JOIN funnel_matrix f  USING(country, id_partner, sku)
  LEFT JOIN comp          cp USING(country, sku)
  LEFT JOIN bench         b  ON b.country=ip.country
                            AND b.ccode=ip.comcat_code
                            AND b.ptype=ip.product_type
                            AND b.subtype=ip.product_subtype
),

scored AS (
  SELECT
    *,
    CASE
      WHEN comcat_2 IN ('audio_video','camera','headphones','home_appliances','laptops','mobiles','video_games','wearables') THEN 'Electronics'
      WHEN comcat_2 IN ('automotive','baby_toys','beauty','books_stationery','eyewear_watches','health_nutrition','home','sports_outdoor') THEN 'Non-Electronics'
      WHEN comcat_2 IN ('fashion') THEN 'Fashion' WHEN comcat_2 IN ('grocery') THEN 'Grocery' ELSE 'rest' END AS cluster,
    ("https://www.noon.com/"||IF(country='AE','uae','saudi')||"-en/"||sku_config||'/p') AS sku_url,
    SAFE_DIVIDE(current_stock, NULLIF(drr_units_l30d,0))       AS days_of_cover,
    SAFE_DIVIDE(units, NULLIF(units+current_stock,0))          AS sell_through_30d,
    SAFE_DIVIDE(total_prov, NULLIF(total_cost,0))              AS provision_coverage_pct,
    next_prov - total_prov                                     AS provision_delta_next,
    SAFE_DIVIDE(qty_aged_gt_180, NULLIF(total_qty,0))          AS pct_aged_gt_180,
    (current_stock>0 AND units=0 AND weighted_age_days>90)     AS dead_stock_flag,
        SAFE_DIVIDE(GREATEST(total_qty-current_stock,0), NULLIF(total_qty,0)) AS non_saleable_pct,
    ((total_qty>0 AND current_stock=0) OR (total_qty>=10 AND SAFE_DIVIDE(total_qty-current_stock,total_qty)>0.10)) AS is_non_saleable,
    IF((total_qty>0 AND current_stock=0) OR (total_qty>=10 AND SAFE_DIVIDE(total_qty-current_stock,total_qty)>0.10),
       GREATEST(total_qty-current_stock,0), 0) AS non_saleable_qty,
       ROUND(IF((total_qty>0 AND current_stock=0) OR (total_qty>=10 AND SAFE_DIVIDE(total_qty-current_stock,total_qty)>0.10),
       SAFE_DIVIDE(total_cost, NULLIF(total_qty,0)) * GREATEST(total_qty-current_stock,0), 0), 2) AS non_saleable_cost,
    SAFE_DIVIDE(total_cost, NULLIF(total_qty,0))               AS puc,
    SAFE_DIVIDE(total_prov, NULLIF(total_qty,0))               AS pup,
    SAFE_DIVIDE(total_cost-total_prov, NULLIF(total_qty,0))    AS eff_cpu,     -- net cost floor
    offer_price - comp_price                                   AS price_gap_vs_comp,
    SAFE_DIVIDE(offer_price-comp_price, comp_price)            AS price_premium_pct,
    CASE WHEN offer_price IS NULL OR comp_price IS NULL THEN 'no_comp'
         WHEN ABS(offer_price-comp_price)<=0.01*comp_price THEN 'at_comp'
         WHEN offer_price>comp_price THEN 'above_comp' ELSE 'below_comp' END AS price_position,
    (has_live_assortment AND current_stock>0 AND comp_price IS NOT NULL AND offer_price>comp_price AND impressions>0 AND units=0) AS price_lever_candidate,
    CASE WHEN impr_p25 IS NULL THEN 'n/a' WHEN impressions<impr_p25 THEN 'low' WHEN impressions>impr_p75 THEN 'high' ELSE 'par' END AS impr_vs_cat,
    CASE WHEN u_p25 IS NULL    THEN 'n/a' WHEN units<u_p25       THEN 'low' WHEN units>u_p75       THEN 'high' ELSE 'par' END AS units_vs_cat,
    CASE WHEN gmv_p25 IS NULL  THEN 'n/a' WHEN gmv<gmv_p25       THEN 'low' WHEN gmv>gmv_p75       THEN 'high' ELSE 'par' END AS gmv_vs_cat,
    CASE WHEN conv_p25 IS NULL OR impressions=0 THEN 'n/a'
         WHEN SAFE_DIVIDE(units,impressions)<conv_p25 THEN 'low'
         WHEN SAFE_DIVIDE(units,impressions)>conv_p75 THEN 'high' ELSE 'par' END AS conv_vs_cat
  FROM enriched
  left join (select distinct content_sku sku,sku_config, from `noonbicedata.comcat_v2.content_sku`) using(sku)
  LEFT JOIN (SELECT DISTINCT sku_config,  title_en FROM `noonbigrowth.assortment_noon.catalog`) USING(sku_config)
  LEFT JOIN (SELECT DISTINCT sku_config, image_url FROM `noonbiretail.test.sku_images_url` WHERE primary_key=1) USING(sku_config)
),

deal AS (   -- feasibility + discount room
  SELECT *,
    ( has_live_assortment AND current_stock>0 AND NOT is_non_saleable
      AND provision_coverage_pct>0.10 AND (days_of_cover IS NULL OR days_of_cover>60) ) AS dealable,
    SAFE_DIVIDE(offer_price-eff_cpu, NULLIF(offer_price,0)) AS discount_room
  FROM scored
),
tiers AS (   -- 3-tier deal engine (single source of truth for the tier condition)
  SELECT *,
    CASE
      WHEN NOT dealable THEN 'none'
      WHEN (provision_coverage_pct>0.60 AND (days_of_cover IS NULL OR days_of_cover>90))
           OR (dead_stock_flag AND weighted_age_days>360) THEN 'T3 - liquidate'
      WHEN provision_coverage_pct>0.30 OR weighted_age_days>270 THEN 'T2 - clear'
      ELSE 'T1 - nudge'
    END AS deal_tier,
    CASE
      WHEN NOT dealable THEN 0.0
      WHEN (provision_coverage_pct>0.60 AND (days_of_cover IS NULL OR days_of_cover>90))
           OR (dead_stock_flag AND weighted_age_days>360) THEN 0.40
      WHEN provision_coverage_pct>0.30 OR weighted_age_days>270 THEN 0.25
      ELSE 0.12
    END AS deal_target
  FROM deal
)

SELECT
  * EXCEPT(dealable, discount_room, deal_target),   -- deal_tier stays

  CASE
    WHEN NOT has_live_assortment AND total_qty>0 THEN 'Not live - dark stock'
    WHEN has_live_assortment AND current_stock=0 THEN 'Replenish - live but OOS'
    WHEN has_live_assortment AND weighted_age_days<=60 AND impressions<130 THEN 'Launch watch - low visibility'
    WHEN price_lever_candidate THEN 'Reprice - above comp'
    WHEN has_live_assortment AND impressions>=130 AND units=0 AND weighted_age_days>180 AND comp_price IS NOT NULL AND offer_price<=comp_price THEN 'Stop replenish - no demand'
    WHEN has_live_assortment AND impressions<130 AND units=0 AND weighted_age_days>60 THEN 'Boost visibility'
    WHEN dead_stock_flag OR weighted_age_days>270 THEN 'Liquidate - aged'
    WHEN units>0 AND sell_through_30d>=0.2 AND weighted_age_days<=90 THEN 'Healthy'
    ELSE 'Monitor'
  END AS primary_action,

  CASE
    WHEN NOT has_live_assortment THEN 'n/a (not live)'
    WHEN impr_vs_cat='n/a' THEN 'no category benchmark'
    WHEN impr_vs_cat='low' THEN 'Visibility gap — below-category impressions (push deals / merchandising)'
    WHEN impr_vs_cat IN ('par','high') AND conv_vs_cat='low' THEN 'Conversion gap — traffic OK but converts below category (price / content / reviews)'
    WHEN units_vs_cat='high' AND gmv_vs_cat='high' THEN 'Category star — protect & expand depth'
    ELSE 'At / above category par'
  END AS category_diagnosis,

  LEAST(deal_target, GREATEST(COALESCE(discount_room,0),0)) AS deal_discount_pct,
  ROUND(GREATEST(eff_cpu, offer_price*(1 - LEAST(deal_target, GREATEST(COALESCE(discount_room,0),0)))), 2) AS recommended_deal_price,
  ROUND(eff_cpu,2) AS deal_floor_price,

  CASE
    WHEN NOT has_live_assortment AND total_qty>0
      THEN CONCAT('Go live or RTV - dark stock; ', CAST(total_qty AS STRING), ' units held not sellable')
    WHEN has_live_assortment AND current_stock=0
      THEN CONCAT('Replenish - live but 0 sellable stock', IF(units>0,' (was selling - urgent)',''))
    WHEN deal_tier='T3 - liquidate'
      THEN CONCAT('T3 deal - liquidate: ~', CAST(ROUND(100*LEAST(0.40,GREATEST(COALESCE(discount_room,0),0))) AS STRING),
                  '% to AED ', CAST(ROUND(GREATEST(eff_cpu, offer_price*(1-LEAST(0.40,GREATEST(COALESCE(discount_room,0),0))))) AS STRING),
                  ' (floor AED ', CAST(ROUND(eff_cpu) AS STRING), '); ', CAST(ROUND(100*provision_coverage_pct) AS STRING),
                  '% provisioned, ', IFNULL(CAST(ROUND(days_of_cover) AS STRING),'∞'), 'd cover - deals amplify visibility + draw down provision')
    WHEN price_lever_candidate
      THEN CONCAT('Cut price toward comp (AED ', CAST(ROUND(offer_price) AS STRING), '->', CAST(ROUND(comp_price) AS STRING), ') - seen, above comp, not selling')
    WHEN deal_tier IN ('T2 - clear','T1 - nudge')
      THEN CONCAT(IF(deal_tier='T2 - clear','T2 deal - clear: ~25%','T1 deal - nudge: ~12%'),
                  ' (cap ', CAST(ROUND(100*GREATEST(COALESCE(discount_room,0),0)) AS STRING),'% room) - draws down ',
                  CAST(ROUND(100*provision_coverage_pct) AS STRING), '% provision + adds browse visibility')
    WHEN has_live_assortment AND impr_vs_cat='low'
      THEN 'Visibility gap vs category - merchandising / deals / placement'
    WHEN has_live_assortment AND impr_vs_cat IN ('par','high') AND conv_vs_cat='low'
      THEN 'Conversion gap vs category - fix price / content / reviews'
    WHEN units>0 AND sell_through_30d>=0.2 AND weighted_age_days<=90
      THEN 'Protect - maintain buybox/availability, replenish to target cover'
    ELSE 'Monitor - review'
  END AS action_recommendation,

  CONCAT('live=', IF(has_live_assortment,'Y','N'), ' · stock ', CAST(current_stock AS STRING),
    ' · age ', CAST(weighted_age_days AS STRING), 'd · cover ', IFNULL(CAST(ROUND(days_of_cover) AS STRING),'∞'), 'd',
    ' · prov ', CAST(ROUND(100*provision_coverage_pct) AS STRING), '%',
    ' · impr ', CAST(CAST(ROUND(impressions) AS INT64) AS STRING), ' (cat:', impr_vs_cat, ')',
    ' · conv ', conv_vs_cat, ' · units ', CAST(units AS STRING),
    ' · ', IFNULL(price_position,'no_comp'),
    ' · bench=', IFNULL(bench_grain,'none')) AS action_logic

FROM tiers
