# Find-Similar Bitemporal Read-Path Fix

Date: 2026-05-02

## Incident

After Bitemporal Phase A, `/api/companies/{cbe}/similar/ai` returned HTTP 200
with an empty candidate list for holding and investment-vehicle targets such
as `0895825682` (DASSY EUROPE) and `0685601641` (DOVESCO), while an operating
company regression check (`0400378485`, Colruyt) still returned candidates.

The prod log signature for failing cases was:

```text
leg_a_count=80 leg_b_count=80 candidates_after_merge=0 degraded=no_candidates
```

The proximate suspect is commit `beffd00`, which changed the group-profile
hydration in `backend/retrieval.py::_build_group_profiles` from the base
`shareholder` and `participating_interest` tables to the bitemporal
`shareholder_current` and `participating_interest_current` views.

## Phase 1 Hotfix

Phase 1 deliberately restores the find-similar group-profile read path to the
base `shareholder` and `participating_interest` tables only. The rest of
Bitemporal Phase A remains intact: columns, views, helper functions, and NBB
governance durability are unchanged.

This is a user-unblocking hotfix, not the final root-cause diagnosis. Phase 2
will add temporary structured instrumentation to determine whether the failure
comes from query-plan regression, changed `_current` semantics, over-eager
same-group filtering, or another downstream filter.

## Re-Evaluation Gate

When Phase 2 lands, re-evaluate whether find-similar should:

1. Keep reading historical-tolerant base tables because the heuristic
   recommendation use case needs broader ownership evidence than
   current-only views expose.
2. Return to `_current` views after adding the necessary indexes and fixing
   any over-firing filter logic.

## Phase 3 Decision

Phase 2 closed on 2026-05-03 and refuted the `_current` view swap as the
remaining latency root cause. The slow path was the embedding KNN SQL shape
bypassing `idx_ce_embedding_hnsw`; the empty strict blend was caused by
activity/profile filters dropping NACE-backed candidates before re-rank.

Find-similar keeps the base-table group-profile exception for now because this
heuristic recommendation path benefits from broader ownership evidence than a
strict current-only read. Revisit only with a dedicated bitemporal read-path
classification change, not as part of the embedding-latency fix.
