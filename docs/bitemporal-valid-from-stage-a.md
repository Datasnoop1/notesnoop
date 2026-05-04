# Bitemporal valid_from Stage A

Created on 2026-05-04 for the residual NULL valid_from backfill.

## Scope

This is only Stage A of the valid_from policy rollout. It backfills NULL
valid_from values from NBB evidence already present in the database:

- administrator: exact mandate_start from any matching NBB filing first; if no
  exact start exists, use the earliest NBB filing that mentions the same
  administrator name/role as an upper-bound date.
- shareholder: earliest NBB filing date mentioning the same shareholder
  identity.
- participating_interest: earliest NBB filing date mentioning the same
  participating-interest identity.
- affiliation: earliest NBB filing date mentioning the same representative
  affiliation relationship.

The migration does not add provenance, does not read Staatsblad events, and
does not tighten valid_from to NOT NULL.

## Production Verification

Run before and after applying
`migrations/2026-05-04_bitemporal_valid_from_stage_a.sql`:

```sql
SELECT 'administrator' AS table_name,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE valid_from IS NULL) AS still_null
FROM administrator
UNION ALL
SELECT 'shareholder', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL)
FROM shareholder
UNION ALL
SELECT 'participating_interest', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL)
FROM participating_interest
UNION ALL
SELECT 'affiliation', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL)
FROM affiliation
ORDER BY table_name;
```

Use the handoff's Phase 1 production counts as the Stage A before baseline:

| Table | Total | Before Stage A NULL |
| --- | ---: | ---: |
| administrator | 1,243,089 | 99,882 |
| shareholder | 44,362 | 7,805 |
| participating_interest | 176,594 | 32,895 |
| affiliation | 56,300 | 21 |

Because the provenance column deliberately lands in Stage C, capture the 10
administrator residual keys before applying Stage A if you need exact row-level
spot checks. After the migration, query those same keys and verify the new
valid_from is within bounds:

```sql
SELECT a.enterprise_number,
       e.start_date::date AS enterprise_start_date,
       a.deposit_key,
       a.name,
       a.role,
       a.mandate_start,
       a.valid_from
FROM administrator a
JOIN enterprise e ON e.enterprise_number = a.enterprise_number
WHERE (a.enterprise_number, a.deposit_key, a.name, a.role) IN (
      -- Replace these with the 10 residual keys captured before migration.
      VALUES ('0000000000', '2024-00000000', 'Example Name', 'fct:m13')
)
  AND a.valid_from IS NOT NULL
  AND a.valid_from <= CURRENT_DATE
  AND a.valid_from >= e.start_date::date
  AND a.deposit_key NOT LIKE 'sb\_%' ESCAPE '\';
```

For the PR summary, report:

| Table | Total | Before Stage A NULL | After Stage A NULL | Backfilled by Stage A |
| --- | ---: | ---: | ---: | ---: |
| administrator |  |  |  |  |
| shareholder |  |  |  |  |
| participating_interest |  |  |  |  |
| affiliation |  |  |  |  |
