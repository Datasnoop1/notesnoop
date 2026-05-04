# Bitemporal valid_from Stage B

Created on 2026-05-04 after Stage A shipped on production in PR #63.

## Scope

Stage B applies Staatsblad supremacy without changing the Stage C/D schema:

- B1 fills NULL valid_from on Staatsblad-sourced rows whose
  `deposit_key` or `via_deposit_key` is `sb_` plus
  `staatsblad_event.pub_reference`.
- B1 uses `event_date` when the event states an effective date, otherwise
  `pub_date`.
- B2 closes older NBB-sourced rows by setting NULL valid_to when a later
  Staatsblad event supersedes the row.
- B2 only closes rows where the Staatsblad effective date is strictly later
  than the row's `source_deposit_date`.

The repository branch does not contain `scripts/staatsblad_consumer_proc.py`.
The linkage used here is confirmed from the current event writer and legacy
projection path: `backend/staatsblad_extraction/extractor.py` persists
`staatsblad_event.pub_reference`, and
`backend/routers/companies/structure.py` projects administrator deposit keys
as `sb_{pub_reference}`.

## Hard NOs

This stage does not add a provenance column, does not set any valid_from column
to NOT NULL, and does not overwrite existing non-NULL valid_from or valid_to.

## Expected Residuals

Stage A production residuals before this stage:

| Table | Stage A residual NULL valid_from |
| --- | ---: |
| administrator | 17,607 |
| shareholder | 2,645 |
| participating_interest | 4,720 |
| affiliation | 17 |

Expected Stage B impact:

- administrator NULL valid_from should drop by up to the roughly 103
  Staatsblad-sourced `sb_%` rows observed after Stage A.
- shareholder / participating_interest / affiliation NULL valid_from should
  only drop where `sb_%` rows exist and match a structured event.
- B2 changes valid_to, not valid_from, so it will not reduce residual
  valid_from counts.

## Production Verification

Run before and after applying
`migrations/2026-05-04_bitemporal_valid_from_stage_b.sql`:

```sql
SELECT 'administrator' AS table_name,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE valid_from IS NULL) AS still_null,
       COUNT(*) FILTER (WHERE deposit_key LIKE 'sb\_%' ESCAPE '\' AND valid_from IS NULL) AS sb_still_null
FROM administrator
UNION ALL
SELECT 'shareholder',
       COUNT(*),
       COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE deposit_key LIKE 'sb\_%' ESCAPE '\' AND valid_from IS NULL)
FROM shareholder
UNION ALL
SELECT 'participating_interest',
       COUNT(*),
       COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE deposit_key LIKE 'sb\_%' ESCAPE '\' AND valid_from IS NULL)
FROM participating_interest
UNION ALL
SELECT 'affiliation',
       COUNT(*),
       COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE via_deposit_key LIKE 'sb\_%' ESCAPE '\' AND valid_from IS NULL)
FROM affiliation
ORDER BY table_name;
```

Spot-check B1 administrator rows:

```sql
SELECT a.enterprise_number,
       a.deposit_key,
       a.name,
       a.role,
       a.valid_from,
       ev.event_date,
       ev.pub_date
FROM administrator a
JOIN staatsblad_event ev
  ON ev.enterprise_number = a.enterprise_number
 AND ev.pub_reference = substring(a.deposit_key FROM 4)
WHERE a.deposit_key LIKE 'sb\_%' ESCAPE '\'
  AND a.valid_from IS NOT NULL
  AND a.valid_from = COALESCE(ev.event_date, ev.pub_date)
ORDER BY random()
LIMIT 10;
```

Spot-check B2 closures using the orchestrator-created backup tables:

```sql
SELECT a.enterprise_number,
       a.deposit_key,
       a.name,
       a.role,
       before.valid_to AS before_valid_to,
       a.valid_to AS after_valid_to,
       a.source_deposit_date,
       ev.event_date,
       ev.pub_date
FROM administrator a
JOIN _bt_vf_stage_b_backup_administrator before
  ON before.enterprise_number = a.enterprise_number
 AND before.deposit_key = a.deposit_key
 AND before.name = a.name
 AND before.role = a.role
JOIN staatsblad_event ev
  ON ev.enterprise_number = a.enterprise_number
 AND ev.event_type = 'admin_event'
WHERE before.valid_to IS NULL
  AND a.valid_to IS NOT NULL
  AND a.valid_to = COALESCE(ev.event_date, ev.pub_date)
  AND COALESCE(ev.event_date, ev.pub_date) > a.source_deposit_date
ORDER BY random()
LIMIT 10;
```
