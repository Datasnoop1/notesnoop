# Bitemporal Phase B read-path audit - 2026-05-02

Scope: `shareholder`, `participating_interest`, and `affiliation`.

## Rule

- Current-state product reads use `_current` views.
- History-aware, resolver, and ETL paths use `_fact` views.
- No production read path should query these three base tables by bare table
  name after the bitemporal cutover.

## Current-State Reads

Current-state reads use these views:

- `shareholder_current`
- `participating_interest_current`
- `affiliation_current`

The current-state surfaces include company structure, network default mode,
people, retrieval, enrichment context, admin metrics, favourites/graveyard, and
pilot/benchmark scripts.

## History-Aware / Fact Reads

History-aware paths intentionally use:

- `shareholder_fact`
- `participating_interest_fact`
- `affiliation_fact`

These are used by the explicit historical network paths, timeline/fact
surfaces where applicable, backfill scripts, `ownership_edge_etl.py`, and
`person_resolver.py`.

## Spec Gap

The shareholder natural-key sketch in r25 references `shareholder.country`,
but the live table has no `country` column. The shipped migration uses
`COALESCE(address, '')` as the available discriminator. This is the same
documented gap from `docs/bitemporal-readpath-audit.md`; no new architecture
choice was made in this closeout.

## Verification

```text
git grep -n "\bFROM shareholder\b\|\bJOIN shareholder\b\|\bFROM participating_interest\b\|\bJOIN participating_interest\b\|\bFROM affiliation\b\|\bJOIN affiliation\b" -- backend scripts ':!scripts/test_*' ':!backend/tests'
```

Expected and observed: no output.
