# Find-Similar Hotfix Evidence

Date: 2026-05-02
Branch: `hotfix/find-similar-revert-bitemporal-views`

## Scope

Phase 1 hotfix for the post-Bitemporal Phase A regression where
`/api/companies/{cbe}/similar/ai` returned HTTP 200 with an empty candidate
list for holding and investment-vehicle targets.

Changed only the find-similar read path, the existing bitemporal guardrail
test's allow-list for this temporary exception, and supporting documentation:

- Restored shareholder group-profile hydration to `FROM shareholder`.
- Restored subsidiary group-profile hydration to `FROM participating_interest`.
- Left all bitemporal schema, `_current` views, helper functions, and NBB
  governance durability in place.
- Added explicit comments marking the base-table read as a temporary Phase 1
  hotfix pending Phase 2 diagnosis.
- Added a narrow test allow-list entry for `backend/retrieval.py` so the
  broader "no bare fact table reads" guardrail still protects every other
  production read path.
- Added a narrow `/similar/ai` degradation fallback: when the strict AI blend
  produces zero candidates despite successful retrieval legs, the endpoint
  returns the existing sector-peer results shaped with the AI-similar response
  fields instead of returning an empty list.

## Known Prod Baseline Before Hotfix

| CBE | Entity | Observed result | Notes |
|---|---|---:|---|
| `0400378485` | Colruyt | 8 candidates | Regression control still worked. |
| `0895825682` | DASSY EUROPE | 0 candidates | Holding-target regression. Prod log had `candidates_after_merge=0`. |
| `0685601641` | DOVESCO | 0 candidates | Investment-vehicle regression. Prod log had `candidates_after_merge=0`. |

## Local Verification

Run from `hotfix/find-similar-revert-bitemporal-views`:

```text
python -m py_compile backend\retrieval.py backend\tests\test_bitemporal_phase_a.py
python -m pytest backend\tests\test_bitemporal_phase_a.py -q
```

Result:

```text
3 passed in 0.42s
```

`git diff --check` returned exit code 0. PowerShell reported line-ending
normalization warnings for existing tracked Python files only.

After the sector-fallback amendment:

```text
python -m py_compile backend\retrieval.py backend\routers\companies\similar.py backend\tests\test_bitemporal_phase_a.py
python -m pytest backend\tests\test_bitemporal_phase_a.py -q
```

Result:

```text
3 passed in 0.36s
```

## Staging Smoke Plan

After PR 1 is merged and staging is rebuilt from `master`, run from inside the
backend staging container:

```bash
python - <<'PY'
import json
import urllib.request

for cbe in ["0400378485", "0895825682", "0685601641"]:
    url = f"http://localhost:8000/api/companies/{cbe}/similar/ai?limit=10"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.load(response)
    items = payload.get("items") if isinstance(payload, dict) else payload
    print(cbe, len(items or []))
PY
```

Expected:

- `0400378485`: non-empty, roughly 10 results.
- `0895825682`: non-empty.
- `0685601641`: non-empty.

## Staging Smoke Results

First PR build at `c2b1888` restored the base-table group-profile reads, but
the smoke still failed for the two holding/investment-vehicle targets:

| CBE | Count | Expected | Result |
|---|---:|---:|---|
| `0400378485` | 8 | >=5 | PASS |
| `0895825682` | 0 | >=1 | FAIL |
| `0685601641` | 0 | >=1 | FAIL |

Read-only in-container diagnosis showed same-group filtering was not the
remaining blocker. The strict blend was empty because existing activity/profile
filters dropped the full pool (`nace_only_low_activity`, `weak_evidence_emb`,
and `score_floor`). The existing non-AI sector-peer route returned 4 DASSY
peers and 15 DOVESCO peers on `leadpeek_staging`, so the hotfix was amended to
use that route as the empty-blend degradation path.

Final staging smoke after the sector-fallback amendment (`c681093`):

| CBE | Count | Expected | Elapsed | Provenance | Result |
|---|---:|---:|---:|---|---|
| `0400378485` | 8 | >=5 | 59,694 ms | `embedding_only`, `embedding+nace` | PASS |
| `0895825682` | 4 | >=1 | 58,080 ms | `sector_fallback` | PASS |
| `0685601641` | 10 | >=1 | 850 ms | `sector_fallback` | PASS |

Notes:

- Staging was rebuilt from PR #50 commit `c681093` and uses
  `leadpeek_staging`.
- The public staging API is admin-gated, so the smoke invoked the same
  FastAPI route function inside `leadpeek-staging-backend-staging-1`.
- The empty-list user regression is unblocked for the known failing targets.
- DASSY remains slow at roughly 58 seconds, so Phase 2 should still diagnose
  query latency and blend-filter disposition before the permanent fix.

## Prod Gate

Prod deploy remains gated on explicit operator approval after staging is green.

## Prod Smoke Results

Pending operator-approved prod deploy.
