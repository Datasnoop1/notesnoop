-- Rollback for 2026-04-26_address_trgm.sql
-- Drops the four GIN trigram indexes on address. Safe to run any time —
-- search just falls back to a sequential scan, which is slow but correct.

DROP INDEX CONCURRENTLY IF EXISTS idx_address_street_nl_trgm;
DROP INDEX CONCURRENTLY IF EXISTS idx_address_street_fr_trgm;
DROP INDEX CONCURRENTLY IF EXISTS idx_address_municipality_nl_trgm;
DROP INDEX CONCURRENTLY IF EXISTS idx_address_municipality_fr_trgm;
