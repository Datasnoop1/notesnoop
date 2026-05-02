# Bitemporal Read-Path Audit - 2026-05-02

Scope: Phase A tables `administrator`, `shareholder`,
`participating_interest`, and `affiliation`.

## Rule

- Current-state product reads use the explicit `_current` views.
- History, resolver, and ETL jobs use the explicit `_fact` views.
- No production read path should query the four base tables by their bare
  names after this phase. A verification grep is part of the evidence.

## Current-State Reads

These files were moved to `_current` views because their callers expect the
latest active structure, people, enrichment, dashboard, or search surface:

- `backend/ai_client.py`
- `backend/enrichment_worker.py`
- `backend/retrieval.py`
- `backend/routers/admin.py`
- `backend/routers/companies/_helpers.py`
- `backend/routers/companies/financials.py`
- `backend/routers/companies/primer.py`
- `backend/routers/dashboard.py`
- `backend/routers/favourites.py`
- `backend/routers/graveyard.py`
- `backend/routers/people.py`
- `backend/routers/search.py`
- `scripts/elaboration_benchmark.py`
- `scripts/pilot/run_pilot_judge.py`

`backend/routers/companies/network.py` and
`backend/routers/companies/structure.py` are mixed:

- normal/current mode reads `_current` views;
- explicit historical paths read `_fact` views where the API exposes
  history-aware behavior.

## History-Aware / Fact Reads

These files intentionally read `_fact` views:

- `backend/routers/companies/network.py`: `include_historical=true` paths.
- `backend/routers/companies/timeline.py`: chronological mandate event list.
- `scripts/backfill_affiliation.py`: historical affiliation catch-up.
- `scripts/backfill_nbb_governance.py`: historical governance backfill.
- `scripts/ownership_edge_etl.py`: historical ownership-edge rebuild.
- `scripts/person_resolver.py`: Person v1 evidence links across historical
  source mentions.

## Spec Gap

The r25 natural-key sketch names `shareholder.country`, but the live
`shareholder` table has no `country` column. Phase A uses
`COALESCE(address, '')` as the available discriminator for the
`idx_shareholder_current_natural` invariant and for writer-side current-row
closure. This should be formalized as a deep-dive revision callout rather than
treated as a new architecture decision.

## Verification

Production-code grep after the read split:

```bash
git grep -n "\\bFROM administrator\\b\\|\\bJOIN administrator\\b\\|\\bFROM shareholder\\b\\|\\bJOIN shareholder\\b\\|\\bFROM participating_interest\\b\\|\\bJOIN participating_interest\\b\\|\\bFROM affiliation\\b\\|\\bJOIN affiliation\\b" -- backend scripts ':!scripts/test_*' ':!backend/tests'
```

Expected: no output.
