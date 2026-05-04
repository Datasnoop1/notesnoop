-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=300s

-- Bitemporal provenance Stage C: add nullable metadata columns for
-- valid_from / valid_to origins. No defaults, no NOT NULL constraints,
-- and no value rewrites.

ALTER TABLE administrator
    ADD COLUMN IF NOT EXISTS valid_from_provenance TEXT,
    ADD COLUMN IF NOT EXISTS valid_to_provenance TEXT;

ALTER TABLE shareholder
    ADD COLUMN IF NOT EXISTS valid_from_provenance TEXT,
    ADD COLUMN IF NOT EXISTS valid_to_provenance TEXT;

ALTER TABLE participating_interest
    ADD COLUMN IF NOT EXISTS valid_from_provenance TEXT,
    ADD COLUMN IF NOT EXISTS valid_to_provenance TEXT;

ALTER TABLE affiliation
    ADD COLUMN IF NOT EXISTS valid_from_provenance TEXT,
    ADD COLUMN IF NOT EXISTS valid_to_provenance TEXT;

COMMENT ON COLUMN administrator.valid_from_provenance IS 'Origin of valid_from: nbb_mandate_start, nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';
COMMENT ON COLUMN administrator.valid_to_provenance IS 'Origin of valid_to: staatsblad_supersession, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';

COMMENT ON COLUMN shareholder.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';
COMMENT ON COLUMN shareholder.valid_to_provenance IS 'Origin of valid_to: staatsblad_supersession, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';

COMMENT ON COLUMN participating_interest.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';
COMMENT ON COLUMN participating_interest.valid_to_provenance IS 'Origin of valid_to: staatsblad_supersession, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';

COMMENT ON COLUMN affiliation.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';
COMMENT ON COLUMN affiliation.valid_to_provenance IS 'Origin of valid_to: staatsblad_supersession, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';
