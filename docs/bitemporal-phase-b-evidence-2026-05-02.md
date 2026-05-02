# Bitemporal Phase B evidence - 2026-05-02

Branch: `feat/bitemporal-phase-b-closeout`

## Scope

Close out Bitemporal Phase B for `shareholder`, `participating_interest`, and
`affiliation`.

No new migration was needed: the additive Phase A migration shipped the three
Phase B tables alongside `administrator` in
`migrations/2026-05-02_bitemporal_phase_a.sql`. Creating a second migration
would duplicate already-applied DDL, so this closeout records verification
instead.

## Local validation

```text
pytest backend/tests/test_bitemporal_phase_a.py -q
3 passed
```

Read-path grep for bare base-table reads:

```text
git grep ... shareholder|participating_interest|affiliation -- backend scripts ':!scripts/test_*' ':!backend/tests'
```

Expected and observed: no output.

## Staging verification

```text
staging_database: leadpeek_staging
staging_bitemporal_migration_applied: True
staging_shareholder: valid_from_null=7808 recorded_from_null=0 recorded_to_closed=21933 total=43980
staging_participating_interest: valid_from_null=32900 recorded_from_null=0 recorded_to_closed=114424 total=174611
staging_affiliation: valid_from_null=7 recorded_from_null=0 recorded_to_closed=1300 total=49975
staging_shareholder_current_exists: True
staging_shareholder_fact_exists: True
staging_participating_interest_current_exists: True
staging_participating_interest_fact_exists: True
staging_affiliation_current_exists: True
staging_affiliation_fact_exists: True
staging_shareholders_as_of_exists: True
staging_participating_interests_as_of_exists: True
staging_affiliations_as_of_exists: True
staging_shareholders_as_of_count: 22047
staging_participating_interests_as_of_count: 60187
staging_affiliations_as_of_count: 48675
```

## Production verification

```text
prod_database: leadpeek
prod_bitemporal_migration_applied: True
prod_shareholder: valid_from_null=7808 recorded_from_null=0 recorded_to_closed=22014 total=44194
prod_participating_interest: valid_from_null=32900 recorded_from_null=0 recorded_to_closed=115338 total=176015
prod_affiliation: valid_from_null=9 recorded_from_null=0 recorded_to_closed=1836 total=53142
prod_shareholder_current_exists: True
prod_shareholder_fact_exists: True
prod_participating_interest_current_exists: True
prod_participating_interest_fact_exists: True
prod_affiliation_current_exists: True
prod_affiliation_fact_exists: True
prod_shareholders_as_of_exists: True
prod_participating_interests_as_of_exists: True
prod_affiliations_as_of_exists: True
prod_shareholders_as_of_count: 22180
prod_participating_interests_as_of_count: 60677
prod_affiliations_as_of_count: 51306
```

## Postcondition

Phase B is green as an already-shipped subset of the merged bitemporal
migration. `valid_from` NOT NULL tightening remains data-quality gated and is
handled in the next closeout phase.
