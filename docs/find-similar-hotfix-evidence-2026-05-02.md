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

Pending operator/server execution.

## Prod Gate

Prod deploy remains gated on explicit operator approval after staging is green.

## Prod Smoke Results

Pending operator-approved prod deploy.
