# Find-Similar Phase 3 Fix Evidence

Date: 2026-05-03
Branch: `feat/find-similar-phase3-fix`
Base: `master` at `4e64a51835`
Fix SHA: `19b84bb`

## Scope

Phase 3 fixes the two independent issues identified by Phase 2:

- Embedding retrieval latency: rewrite the pgvector KNN lookup so the planner
  can use the existing `idx_ce_embedding_hnsw` index.
- Empty strict blend: soften the over-aggressive activity/profile filters for
  holding/investment targets and for NACE/revenue-backed peers whose profile
  text overlap is sparse.

No schema change is required. `hnsw.ef_search` is set per transaction with
`set_config(..., true)`.

## Code Changes

- `retrieve_by_embedding` now uses a two-step query shape:
  1. Fetch the target embedding into Python as `embedding::text`.
  2. In the same transaction, set `hnsw.ef_search = 100` and run the KNN query
     with the target vector supplied as a bound `%s::vector` parameter.
- `_build_group_profiles` keeps the Phase 1 base-table read exception and now
  points readers to `docs/find-similar-diagnosis-2026-05-03.md`.
- `blend_candidates` now applies softer gates for:
  - holding/investment-vehicle targets by NACE code or small-revenue subsidiary
    structure;
  - NACE-only candidates with exact NACE plus some revenue comparability;
  - related NACE candidates only when revenue comparability is very strong.

## Local Verification

```text
python -m py_compile backend\retrieval.py backend\routers\companies\similar.py
python -m pytest backend\tests\test_bitemporal_phase_a.py -q
```

Result:

```text
3 passed
```

## Prod Read-Only KNN Probe

The exact Phase 3 SQL shape was tested read-only inside the prod backend
container. This did not deploy code or mutate prod data.

`hnsw.ef_search = 100`, `LIMIT 80`:

| CBE | Rows | Timed KNN query | Plan |
|---|---:|---:|---|
| `0400378485` | 80 | 28 ms | `Index Scan using idx_ce_embedding_hnsw` |
| `0895825682` | 80 | 19 ms | `Index Scan using idx_ce_embedding_hnsw` |

EXPLAIN snippet:

```text
0400378485
Limit  (cost=1825.98..1942.34 rows=80 width=27)
->  Index Scan using idx_ce_embedding_hnsw on company_embedding ce

0895825682
Limit  (cost=1825.98..1942.34 rows=80 width=27)
->  Index Scan using idx_ce_embedding_hnsw on company_embedding ce
```

This replaces the Phase 2 diagnosis plan shape that used sequential scan plus
sort over `company_embedding`.

## Staging Blend Acceptance

Staging was rebuilt from `feat/find-similar-phase3-fix` at `19b84bb`. The
smoke invoked retrieval and `blend_candidates` directly inside
`leadpeek-staging-backend-staging-1`, avoiding cache and LLM variability.

Note: staging does not have the prod HNSW index, so embedding-leg elapsed times
remain staging-only and are not representative of the production latency fix.

| CBE | Leg A | Leg B | Leg C | Passed strict blend | Elapsed | Result |
|---|---:|---:|---:|---:|---:|---|
| `0400378485` | 80 | 80 | 0 | 40 | 28,948 ms | PASS |
| `0895825682` | 80 | 80 | 0 | 40 | 26,129 ms | PASS |
| `0685601641` | 0 | 80 | 0 | 40 | 1,025 ms | PASS |

Acceptance thresholds:

- Colruyt: `passed >= 6`
- DASSY: `passed >= 5`
- DOVESCO: `passed >= 5`

All three pass.

## Deferred

The Colruyt LLM fallback latency observed in Phase 2 was not changed in this
PR. The database leg is the primary regression and is fixed by the KNN rewrite;
LLM timeout/fallback ordering can ship as a separate follow-up.

## Phase 4 Handoff

After Phase 3 is reviewed, merged, operator-approved, deployed to prod, and
smoked:

- Add the route-level guard test with latency thresholds.
- Record prod before/after smoke results in the final evidence doc.
- Close the Phase 2 diagnosis PR without merging if it remains draft-only.
