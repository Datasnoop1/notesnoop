# Phase-2 pilot — automated judge

Runs the full Spike-2 judge methodology against a finished pilot batch
and emits `PILOT_REPORT.md` with a PASS / CONDITIONAL / FAIL verdict.

## When to run it

After `enrichment_worker` has finished processing a pilot-sized batch
(default: 500 CBEs). Every row in the batch must be `status='done'`
in `enrichment_job`. Run on staging; it's read-only against the DB.

## Invocation

```
# 1. Seed the pilot queue on staging and dump the CBE list.
python scripts/seed_enrichment_queue.py \
    --scope pilot --limit 500 \
    --dump-json scripts/pilot/pilot_cbes.json

# 2. Wait for the worker to churn through them. Watch the admin page
#    at /admin/enrichment — queue depth should hit 0.

# 3. Run the judge.
python scripts/pilot/run_pilot_judge.py \
    --pilot-set scripts/pilot/pilot_cbes.json

# 4. Read scripts/pilot/PILOT_REPORT.md.
```

## Flags

| Flag | Purpose |
|---|---|
| `--pilot-set PATH` | Required. JSON from `seed_enrichment_queue --dump-json`. |
| `--out-dir PATH` | Where artifacts land. Default `scripts/pilot`. |
| `--sample-size N` | Override the 30-row judge sample (for smoke tests). |
| `--dry-run` | Stop after sampling (Step 1). No LLM spend. |
| `--skip-plausibility` | Skip Step 4 (the 470-row flag pass). |

## Env vars

- `ANTHROPIC_API_KEY` — direct Anthropic SDK for Opus + Sonnet.
- `OPENROUTER_API_KEY` — OpenRouter for GPT-4o-mini plausibility check.
- `DATABASE_URL` — same Postgres the backend uses.
- `PILOT_HARD_BUDGET` — abort if spend exceeds this USD (default 15).

## Artifacts written to `scripts/pilot/`

| File | Step | What's in it |
|---|---|---|
| `pilot_sample_30.json` | 1 | The 30 stratified CBEs + bucket + KBO context fields. |
| `ground_truth_pilot.json` | 2 | Opus-authored factual summaries for each of the 30. |
| `judge_packet.json` | 3 | Input to the Sonnet judge (pipeline output + ground truth). |
| `judge_scores.csv` | 3 | Sonnet's 5-axis scores per row. |
| `plausibility_flags.csv` | 4 | GPT-4o-mini hallucination flags on the other 470. |
| `deterministic_checks.json` | 5 | SQL pass/fail for dormant bypass, schema, floor. |
| `meta_review.md` | 6 | Opus 4.7 meta-review of the judge + plausibility. |
| `PILOT_REPORT.md` | 7 | Operator-readable verdict + metrics + recommendation. |

## Budget

| Step | Calls | ~cost |
|---|---|---|
| 2 — Opus ground truth | 30 | $5.00 |
| 3 — Sonnet judge | 1 | $0.80 |
| 4 — GPT-4o-mini plausibility | 470 | $0.15 |
| 5 — deterministic SQL | — | $0 |
| 6 — Opus meta-review | 1 | $1.50 |
| **Total (per run)** |  | **~$7.50** |

Hard cap at `PILOT_HARD_BUDGET` (default $15). Budget breach writes
`ABORTED.md` next to the artifacts and exits with a non-zero code.

## Pass gates

A **PASS** verdict requires ALL of:

1. 30-row sample `overall_avg` ≥ 3.06 (matches the Spike 1 Option A floor).
2. Tier-1 bucket avg ≥ 3.40.
3. Zero hallucinated executive names flagged by the plausibility pass.
4. Deterministic compliance 100% (dormant bypass, schema, confidence-floor data present).
5. Opus meta-review returns **PASS** (no CRITICAL blockers).

Anything less → CONDITIONAL (fixable) or FAIL (halt).

## Mock / smoke test

Want to exercise the plumbing without burning real budget?

```
python scripts/seed_enrichment_queue.py \
    --scope pilot --limit 10 \
    --dump-json scripts/pilot/mock_cbes.json

python scripts/pilot/run_pilot_judge.py \
    --pilot-set scripts/pilot/mock_cbes.json \
    --sample-size 5 --dry-run
```

`--dry-run` stops after stratified sampling — the CBE list + bucket
classification lands in `pilot_sample_30.json` for eyeballing without
any LLM calls.

## What this script doesn't do

- It does NOT re-seed or re-run the bulk worker. It only judges what's
  already written.
- It does NOT change production settings. The confidence-floor check
  in Step 5 is a read-only verification that the `/api/search/semantic`
  endpoint is filtering correctly.
- It does NOT decide Phase 3 for you — even a PASS verdict requires the
  operator's explicit go signal before the tier-1+tier-2 backfill runs.
