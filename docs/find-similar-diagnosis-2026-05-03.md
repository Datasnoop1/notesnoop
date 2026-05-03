# Find-Similar Phase 2 Diagnosis

Date: 2026-05-03
Branch: `feat/find-similar-bitemporal-diagnose`
Base: `master` at `4e64a51835`

## Scope

Phase 2 added temporary structured-log instrumentation for
`/api/companies/{cbe}/similar/ai` after the Phase 1 prod hotfix restored
non-empty results for the known holding and investment-vehicle targets.

No prod deploy was performed for this phase. The branch was deployed only to
staging for reproduction. Prod checks were limited to read-only metadata and
`EXPLAIN`/timed query probes.

Instrumentation added:

- Retrieval-leg timings for `retrieve_by_embedding`, `retrieve_by_nace`, and
  `retrieve_by_size_band`, including timestamps, row counts, and skipped legs.
- `_hydrate_candidates` query latency and row count.
- `_build_group_profiles` total latency plus shareholder and
  participating-interest query latencies, row counts, profile sizes, and sample
  identifiers.
- `blend_candidates` aggregate disposition counts for every candidate drop or
  pass.
- LLM re-rank call latency in `similar.py` for the shortlist and final calls.

## Staging Reproduction

Staging was rebuilt from `feat/find-similar-bitemporal-diagnose` commit
`204af87`. The public staging API is admin-gated, so reproduction invoked the
same FastAPI route function inside `leadpeek-staging-backend-staging-1` with
INFO logging enabled.

Only the three target cache rows were cleared before reproduction:

```text
0400378485
0895825682
0685601641
```

## Summary

| CBE | Entity | Result count | Provenance | Total latency | Result |
|---|---|---:|---|---:|---|
| `0400378485` | Colruyt | 8 | `embedding+nace`, `embedding_only` | 113,359 ms | PASS |
| `0895825682` | DASSY EUROPE | 4 | `sector_fallback` | 58,560 ms | PASS |
| `0685601641` | DOVESCO | 10 | `sector_fallback` | 910 ms | PASS |

The Phase 1 sector fallback keeps affected targets non-empty. The remaining
latency regression is independent: it occurs when the embedding retrieval leg
runs, even before any LLM re-rank.

## Latency Breakdown

| CBE | Embedding leg | NACE leg | Hydrate | Group profiles | LLM wall calls | Notes |
|---|---:|---:|---:|---:|---:|---|
| `0400378485` | 59,506 ms | 2,010 ms | 710 ms | 708 ms | 50,078 ms | Real AI path; shortlist and final LLM calls both ran. |
| `0895825682` | 55,311 ms | 1,810 ms | 714 ms | 389 ms | 0 ms | Empty strict blend, then sector fallback. |
| `0685601641` | skipped | 127 ms | 253 ms | 369 ms | 0 ms | No target embedding, so the slow leg did not run. |

Group-profile query detail:

| CBE | Shareholder query | Shareholder rows | PI query | PI rows |
|---|---:|---:|---:|---:|
| `0400378485` | 236 ms | 286 | 453 ms | 2,599 |
| `0895825682` | 119 ms | recorded in log | 260 ms | recorded in log |
| `0685601641` | 56 ms | recorded in log | 301 ms | recorded in log |

Colruyt's LLM wall latency was also material:

| Call | Wall latency |
|---|---:|
| Shortlist re-rank | 32,872 ms |
| Final re-rank | 17,206 ms |

The existing model telemetry inside the endpoint reported 28,177 ms of
provider-call latency. The larger wall timing is explained by failed local
Ollama attempts and fallback sequencing before remote providers returned.
This is a second latency contributor, but it is not the primary database
regression because DASSY also spent 55,311 ms in embedding retrieval and did
not call the LLM at all.

## Blend Disposition

Percentages below use the instrumented disposition total for the request.

| CBE | Disposition pool | Dominant drops | Passed |
|---|---:|---|---:|
| `0400378485` | 158 | `nace_only_low_activity`: 76 (48.1%); `weak_evidence_emb`: 57 (36.1%); `activity_focus_filter`: 11 (7.0%); `same_group_id`: 4 (2.5%); `score_floor`: 2 (1.3%) | 8 (5.1%) |
| `0895825682` | 160 | `nace_only_low_activity`: 78 (48.8%); `weak_evidence_emb`: 77 (48.1%); `activity_focus_filter`: 2 (1.3%); `score_floor`: 2 (1.3%); `same_group_id`: 1 (0.6%) | 0 |
| `0685601641` | 80 | `nace_only_low_activity`: 77 (96.3%); `score_floor`: 3 (3.8%) | 0 |

Raw aggregate disposition keys:

```text
hydrate_miss
same_group_id
same_group_name
shareholder_intersect_id
shareholder_intersect_name
weak_evidence_size_band
weak_evidence_emb
nace_only_low_activity
activity_focus_filter
score_floor
passed
```

Neither failing target was mainly dropped by same-group logic:

- DASSY had only 1 `same_group_id` drop out of 160 dispositions.
- DOVESCO had 0 same-group or shareholder-intersection drops.
- `same_group_name`, `shareholder_intersect_id`, and
  `shareholder_intersect_name` were 0 for all three test requests.

## Query-Plan Check

The embedding table has an HNSW index on prod:

```text
idx_ce_embedding_hnsw ON company_embedding USING hnsw (embedding vector_cosine_ops)
```

The current query shape in `retrieve_by_embedding` uses a target subquery joined
to `company_embedding` and then orders by vector distance. On prod and staging,
`EXPLAIN` showed a sequential scan plus sort over the embedding table instead
of an HNSW KNN index scan.

Read-only prod probes showed that a parameterized query shape using the target
embedding value directly can use `idx_ce_embedding_hnsw`:

| CBE | Parameterized KNN elapsed | Rows returned |
|---|---:|---:|
| `0400378485` | 382 ms | 39 |
| `0895825682` | 484 ms | 32 |

The low row counts are consistent with the default HNSW `ef_search` value.
Phase 3 should test raising `hnsw.ef_search` for this request path so the
retrieval leg can reliably return the desired 80 candidates while still using
the index.

## Hypotheses

### A. Empty-Blend Bug

Confirmed as an over-strict blend-filter issue for the holding and
investment-vehicle targets. DASSY and DOVESCO retrieved candidates, hydrated
them, and built group profiles, but the strict blend dropped the full candidate
pool before the AI re-rank step.

This is not a same-group over-fire. The dominant drops were
`nace_only_low_activity`, `weak_evidence_emb`, and `score_floor`.

### B. AI-Path Latency Regression

Confirmed as an independent embedding-retrieval query-plan issue plus a
secondary LLM fallback latency contributor.

The decisive evidence is:

- Colruyt and DASSY both spent roughly 55-60 seconds in the embedding leg.
- DASSY did not call the LLM, yet still took 58.6 seconds.
- DOVESCO had no target embedding, skipped the embedding leg, and completed in
  under 1 second.
- The current embedding SQL shape bypasses the existing HNSW index and performs
  a sequential scan plus sort.
- A read-only parameterized KNN probe on prod used the HNSW index and returned
  in under 500 ms.

Colruyt also spent about 50 seconds of wall time around LLM re-rank calls due
to local Ollama timeouts and fallback sequencing. That should be optimized, but
it is separate from the database regression.

### C. Bitemporal `_current` View Regression

Refuted for the remaining latency issue. Phase 1 reverted group-profile reads
to base tables before this test, and the instrumented group-profile work was
sub-second for all three requests.

The original empty-list symptom was unblocked by the Phase 1 sector fallback,
but the Phase 2 disposition evidence shows that the strict blend is still too
aggressive for holding/investment-vehicle targets even when base-table profile
reads are used.

## Phase 3 Recommendation

The two remaining issues should be treated independently:

1. Fix embedding retrieval performance by rewriting the embedding KNN lookup so
   the target vector is supplied in a query shape that uses
   `idx_ce_embedding_hnsw`. Test with a request-local `hnsw.ef_search` setting
   high enough to return the expected 80 candidates.
2. Keep the Phase 1 non-empty degradation behavior while making the strict blend
   less brittle for holding and investment-vehicle targets. The specific drops
   to revisit are `nace_only_low_activity`, `weak_evidence_emb`, and
   `score_floor`.
3. Keep the base-table group-profile read exception in place until the final
   bitemporal read-path classification is updated. Current Phase 2 evidence does
   not justify reinstating `_current` views for this heuristic recommendation
   path as part of the latency fix.

Path selection note: the remaining problem is not the originally suspected
`_current` view query-plan regression. A narrow Phase 3 performance fix can
therefore be pursued without tying it to a `_current` view reinstatement.

## Verification Commands

Local syntax and guardrail checks for the instrumentation branch:

```text
python -m py_compile backend\retrieval.py backend\routers\companies\similar.py
python -m pytest backend\tests\test_bitemporal_phase_a.py -q
```

Result:

```text
3 passed
```
