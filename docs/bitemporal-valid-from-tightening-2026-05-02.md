# Bitemporal valid_from tightening check - 2026-05-02

Branch: `feat/bitemporal-valid-from-tightening-check`

## Scope

Check whether `administrator`, `shareholder`, `participating_interest`, and
`affiliation` are ready for:

```sql
ALTER TABLE <table> ALTER COLUMN valid_from SET NOT NULL;
```

No tightening migration is shipped in this phase because every table still has
nonzero unknown-start rows.

## Production counts

```text
administrator: valid_from_null=228207 source_deposit_date_null=228207 null_with_deposit_key_null=265 null_with_deposit_key_present=227942 total=1221539
shareholder: valid_from_null=7808 source_deposit_date_null=7808 null_with_deposit_key_null=0 null_with_deposit_key_present=7808 total=44194
participating_interest: valid_from_null=32900 source_deposit_date_null=32900 null_with_deposit_key_null=0 null_with_deposit_key_present=32900 total=176016
affiliation: valid_from_null=9 source_deposit_date_null=9 null_with_source_deposit_date_null=9 total=53142
```

## Missing source summary

For the NBB-backed tables, the unknown-start rows are missing matching
`financial_summary` deposit-date coverage for the row's deposit key:

```text
administrator_null_financial_summary: deposit_date_missing=228205 no_summary_match=228205 summary_match_but_date_null=0
shareholder_null_financial_summary: deposit_date_missing=7807 no_summary_match=7807 summary_match_but_date_null=0
participating_interest_null_financial_summary: deposit_date_missing=32899 no_summary_match=32899 summary_match_but_date_null=0
```

The dominant null-key prefixes are old `2022-20*` deposit-key ranges:

```text
administrator_null_key_prefixes: 2022-200=57056; 2022-201=44140; 2022-202=43824; 2022-203=39295; 2022-204=29950
shareholder_null_key_prefixes: 2022-200=2313; 2022-201=1936; 2022-202=1463; 2022-203=802; 2022-204=710
participating_interest_null_key_prefixes: 2022-200=9552; 2022-201=7994; 2022-202=5978; 2022-203=3799; 2022-204=3534
```

For `affiliation`, the remaining gaps are all `represents_admin` rows with no
`source_deposit_date`:

```text
affiliation_null_types: represents_admin=9
```

## Decision

No table qualifies for `valid_from NOT NULL` yet:

- `administrator`: leave nullable.
- `shareholder`: leave nullable.
- `participating_interest`: leave nullable.
- `affiliation`: leave nullable.

Operator decision needed later: either backfill deposit dates for the missing
historical NBB deposit-key ranges and the nine affiliation rows, or keep the
r25 unknown-start convention permanently for these tables.
