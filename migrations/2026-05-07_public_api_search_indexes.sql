-- @migration: no-tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=1800s

-- Public API search-endpoint indexes. CONCURRENTLY-built so reads on
-- financial_latest / company_master / company_info aren't blocked
-- during the build. statement_timeout is 30 min for the largest
-- composite (financial_latest has multi-million rows after Phase 5).
--
-- v1 ships indexes for the three sort metrics we expect to dominate
-- traffic (`total_assets`, `revenue`, `ebitda`) in both directions
-- (DESC for "biggest", ASC for "smallest"). Other sort metrics in
-- _SORT_TABLE will fall back to whatever single-column index exists
-- (or seq-scan); we'll add their composite indexes reactively if
-- pg_stat_statements shows them as hot.
--
-- A composite (metric, enterprise_number) is what the keyset
-- pagination cursor seek needs — `(metric, en) < (last_v, last_en)`
-- is a single-step index seek when the index has both columns in
-- tiebreak order.
--
-- Operator runbook: each CONCURRENTLY can take minutes on a large
-- table; monitor pg_stat_progress_create_index. If the migration
-- aborts mid-statement, the offending index is left INVALID — drop
-- it (DROP INDEX IF EXISTS …) and rerun.

-- financial_latest sort indexes (3 metrics × 2 directions = 6).
-- The DESC/ASC direction of the metric must match the ORDER BY
-- direction in _SORT_TABLE for the planner to pick the index
-- without a sort step.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fl_total_assets_desc_en
  ON financial_latest (total_assets DESC NULLS LAST, enterprise_number ASC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fl_total_assets_asc_en
  ON financial_latest (total_assets ASC NULLS LAST, enterprise_number ASC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fl_revenue_desc_en
  ON financial_latest (revenue DESC NULLS LAST, enterprise_number ASC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fl_revenue_asc_en
  ON financial_latest (revenue ASC NULLS LAST, enterprise_number ASC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fl_ebitda_desc_en
  ON financial_latest (ebitda DESC NULLS LAST, enterprise_number ASC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fl_ebitda_asc_en
  ON financial_latest (ebitda ASC NULLS LAST, enterprise_number ASC);

-- Functional index for case-insensitive juridical_form filter.
-- `company_master` is a VIEW (joins enterprise + denomination + address +
-- activity), and you can't index a view. The PG planner pushes a
-- LOWER(juridical_form) predicate through the view to the underlying
-- `enterprise` table where the column actually lives — so this is the
-- index that gets picked.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_enterprise_juridical_form_lower
  ON enterprise (LOWER(juridical_form));

-- text_pattern_ops gives the planner a left-anchored prefix-search
-- index for `LIKE 'prefix%'`. A plain B-tree on nace_code will NOT
-- be picked for this on a non-C collation database — the operator
-- class is the difference.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ci_nace_code_pattern
  ON company_info (nace_code text_pattern_ops);
