# Semantic Pipeline Operations

This is the runbook for the bulk semantic-enrichment pipeline:
LLM-generated `company_enrichment.bulk_summary` rows plus
`company_embedding` vectors used by `/api/search/semantic`.

Read this together with:

- `docs/product.md`
- `docs/architecture.md`

If a future session needs to answer "what is the current semantic policy?",
"how do I restart it safely?", or "why did ETA jump?", this is the file it
should trust first.

## Current operating policy

These are the standing rules as of **23 April 2026**.

1. The semantic database comes before any public frontend rollout.
2. Quality beats raw throughput. We throttle DuckDuckGo conservatively rather
   than flooding discovery and polluting the corpus.
3. The worker treats **known latest EBITDA below
   `SEMANTIC_FASTLANE_EBITDA_FLOOR`** as explicit fast lane.
   Default floor: `200000` EUR. Here "fast lane" means the cheap,
   deterministic template path that avoids wasting discovery and LLM spend on
   sub-threshold companies; it does **not** mean "priority enrichment".
4. **Missing EBITDA is not automatically fast-lane.** That is a separate
   product decision and must not be silently inferred by future sessions.
   Missing-EBITDA companies stay on the standard discovery/scrape/Q2 path
   unless another shortcut rule applies first.
5. The following legal forms are **outside the semantic corpus** and should
   not consume LLM calls, embeddings, or queue capacity:
   - `017` `Vereniging zonder winstoogmerk`
   - `070` `Vereniging van mede-eigenaars`
   - `030` `Buitenlandse entiteit`
   - `011` `Vennootschap onder firma`
   - `012` `Gewone commanditaire vennootschap`
   - `612` `Commanditaire vennootschap`
   - `721` `Vennootschap of vereniging zonder rechtspersoonlijkheid`
   - `124` `Openbare instelling`
   Source of truth: `backend/enrichment_routing.py::EXCLUDED_JURIDICAL_FORMS`.
6. Public semantic search only trusts `bulk_confidence IN ('high', 'medium')`
   by default. `low` and `insufficient_information` are fallback/search-tail
   material, not the public quality bar.

## Queue semantics

`enrichment_job.status` now has six meaningful states:

- `queued`: waiting to be claimed
- `claimed`: currently held by a worker
- `done`: semantically processed and kept in corpus
- `failed`: transient failure, can be retried
- `dead`: exhausted retry budget, manual inspection needed
- `excluded`: intentionally outside the semantic corpus

Important:

- `excluded` is **not** the same as `done`.
- ETA and completion should be read against the **target corpus**, not against
  rows intentionally excluded from scope.
- If a session bulk-excludes companies, it should also remove their
  `bulk_summary` and `company_embedding` rows so search quality stays clean.

## Canonical files

These files own the current semantic flow:

- `backend/enrichment_worker.py`
- `backend/enrichment_routing.py`
- `backend/enrichment_queue.py`
- `backend/routers/admin_enrichment.py`
- `scripts/seed_enrichment_queue.py`
- `scripts/reclassify_enrichment_queue.py`
- `scripts/apply_semantic_exclusions.py`
- `frontend/src/components/admin/enrichment-dashboard.tsx`

If a future session changes queue policy without touching the matching helper
script, that is drift and should be fixed before rollout.

## What "healthy" looks like

The pipeline is healthy when all of the following are true:

- `company_enrichment`, `enrichment_job`, `company_embedding`,
  `query_embedding_cache`, and `aggregator_skiplist` exist.
- `meta.enrichment_enabled=true`.
- `OPENROUTER_API_KEY` and `ENRICHMENT_ADMIN_PASSWORD` are present in the
  worker/backend runtime. (`ZENROWS_API_KEY` was required until 2026-04-25;
  Zenrows is now disabled pending the Playwright + Webshare replacement,
  and its absence is no longer a health-check failure.)
- The worker heartbeat on `/admin/enrichment` is fresh.
- `company_enrichment.bulk_summary` has rows.
- `company_embedding` has rows.
- Worker logs show believable path mix, not only failures:
  `q2`, `q2+haiku`, `template`, `fastlane_ebitda`, and where relevant
  `excluded_juridical_form`.

## One-command status check

From the repo root:

```bash
python scripts/semantic_status.py
```

Useful variants:

```bash
python scripts/semantic_status.py --json
python scripts/semantic_status.py --env-file .env.production
python scripts/semantic_status.py --ensure-schema
```

`--ensure-schema` creates missing semantic tables and default meta rows.

Useful SQL spot-checks:

```sql
SELECT value
FROM meta
WHERE variable = 'enrichment_enabled';

SELECT value
FROM meta
WHERE variable = 'enrichment_daily_budget';
```

## Routing summary

The worker currently makes decisions in this order:

1. Unknown / branch-only CBE: skip
2. Excluded legal form: mark `excluded`
3. Dormant / dissolved juridical situation: deterministic template path
4. Known EBITDA below floor: deterministic fast lane (`fastlane_ebitda`)
5. Website resolve
6. Scrape
7. Template fallback if scrape is absent or untrustworthy
8. KBO context block
9. Q2 summary
10. Entity-collision check
11. Optional Haiku escalation
12. Persist + embed

This ordering matters. If a future session moves website discovery ahead of the
excluded-form or EBITDA checks, throughput will drop again for no benefit.

## Bring it back up from cold or broken state

**Warning: staging and production share the same Postgres database.**
Even during incident recovery, schema or queue commands executed from a
staging shell still mutate the live production dataset. Use staging to verify
code paths and dry-runs only; run real `--apply` actions from the production
backend container after explicit approval.

1. Ensure schema is present:

```bash
python scripts/semantic_status.py --ensure-schema
```

2. Confirm runtime secrets exist in the environment used by backend and worker:

- `OPENROUTER_API_KEY`
- `ENRICHMENT_ADMIN_PASSWORD`
- (`ZENROWS_API_KEY` no longer required as of 2026-04-25 — Zenrows disabled
  pending Playwright + Webshare replacement)

3. Seed the queue if needed, from the **production backend container only**.
   Start small:

```bash
docker compose -p leadpeek exec backend python scripts/seed_enrichment_queue.py --scope pilot --limit 500
```

Then scale:

```bash
docker compose -p leadpeek exec backend python scripts/seed_enrichment_queue.py --scope tier1_2
docker compose -p leadpeek exec backend python scripts/seed_enrichment_queue.py --scope tier3_web
docker compose -p leadpeek exec backend python scripts/seed_enrichment_queue.py --scope tier3_no_web
```

Scope guide (`scripts/seed_enrichment_queue.py` is the source of truth):

- `pilot`: mixed smoke-test sample across revenue/web buckets for manual QA
- `tier1_2`: active commercial companies with revenue of at least `1m` EUR
- `tier3_web`: active in-scope companies with a KBO website on file
- `tier3_no_web`: active in-scope companies without a KBO website
- `template`: dormant or non-normal juridical situations; deterministic path

4. Start or restart the staging backend for code-path validation, but do **not**
   let a staging semantic worker drain the shared production queue.
5. Open `/admin/enrichment` and confirm:
   - worker heartbeat is moving
   - queue depth is falling
   - recent completed rows appear
   - bulk row count and embedding row count rise over time

## Safe rollout procedure

### Rule zero

**Staging and production share the same Postgres database.**

That means:

- a staging deploy is still required before prod
- but any script run with `--apply` from the staging container still mutates the
  production database

So the correct pattern is:

1. Deploy code to staging
2. Smoke-test staging UI and worker behavior
3. Run mutating scripts on staging only as **dry-run**
4. After explicit operator approval, deploy prod
5. Run `--apply` only from the **production backend container**

### Standard sequence

1. Deploy staging:

```bash
./scripts/deploy_staging.sh <SERVER_IP> <SSH_KEY_PATH>
```

2. Smoke test:
   - `http://<SERVER_IP>:8080/api/health`
   - `/admin/enrichment`
   - staging UI/backend behavior only

   For semantic or other shared-DB workflows, staging is **not** an isolated
   worker sandbox. If the staging compose project launches a worker against the
   shared production DB, stop it before continuing.

3. Dry-run any matching maintenance script:

```bash
python scripts/reclassify_enrichment_queue.py
python scripts/apply_semantic_exclusions.py
```

4. Only after approval, deploy prod:

```bash
./scripts/deploy.sh <SERVER_IP> <SSH_KEY_PATH>
```

5. Before any destructive `--apply`, take a backup of the affected semantic
   tables and verify that the dump is readable. Minimum acceptable safety step:

```bash
pg_dump "$DATABASE_URL" --format=custom --file semantic-preapply.dump --table=company_enrichment --table=company_embedding --table=enrichment_job
pg_restore --list semantic-preapply.dump
```

6. Then apply the mutation on the server, from the prod backend container only.
   Use `docker compose ... exec` rather than hard-coded container names.

Examples:

```bash
docker compose -p leadpeek exec backend python scripts/reclassify_enrichment_queue.py --apply
docker compose -p leadpeek exec backend python scripts/apply_semantic_exclusions.py --apply
```

7. Verify:
   - `https://datasnoop.be/api/health`
   - `docker logs --tail 50 leadpeek-enrichment-worker-1`
   - `/admin/enrichment`

## Canonical maintenance scripts

### `scripts/reclassify_enrichment_queue.py`

Use this when the **priority model** changes but the target corpus stays the
same. Current use case: explicit EBITDA fast lane.

Dry-run:

```bash
python scripts/reclassify_enrichment_queue.py
```

Apply:

```bash
python scripts/reclassify_enrichment_queue.py --apply
```

What it does:

- recalculates `priority`
- does **not** change `status`
- keeps missing-EBITDA rows untouched by the explicit fast-lane rule

### `scripts/apply_semantic_exclusions.py`

Use this when legal-form scope changes and a class of companies should leave the
semantic corpus entirely.

Dry-run:

```bash
python scripts/apply_semantic_exclusions.py
```

Apply:

```bash
python scripts/apply_semantic_exclusions.py --apply
```

Before `--apply`, take a semantic backup first and verify the dump:

```bash
pg_dump "$DATABASE_URL" --format=custom --file semantic-preapply.dump --table=company_enrichment --table=company_embedding --table=enrichment_job
pg_restore --list semantic-preapply.dump
```

What it does:

- marks matching queue rows as `excluded`
- clears `company_enrichment.bulk_*` fields for those rows
- deletes matching `company_embedding` rows

This is intentionally stronger than reprioritisation. It is corpus cleanup, not
just queue shuffling.

## ETA interpretation

The admin ETA is only a rough planning aid.

Use these rules:

1. Prefer the **last 24h completed** pace over tiny time windows.
2. Ignore ETA immediately after a deploy or worker restart. The first
   20 to 60 minutes are warm-up and often look worse than steady state.
3. Excluded jobs must not count toward target backlog.
4. If ETA suddenly worsens, check whether:
   - the worker restarted recently
   - DDG throttling tightened
   - a large low-signal group was moved out of scope but not yet marked
     `excluded`
5. Always communicate ETA with an absolute date if there is any ambiguity.

Simple formula:

```text
eta_days = remaining_target_jobs / last_24h_completed
```

Where `remaining_target_jobs` means queued + claimed, excluding rows that are
intentionally out of scope.

## Quality checks

The semantic exercise is only worth finishing if output quality stays useful.

Minimum quality checks:

- inspect recent worker logs for a believable path mix
- inspect `/admin/enrichment` confidence distribution
- sample real `bulk_summary` output from recently completed companies
- verify that search still surfaces `high` and `medium` rows, not just
  templates

Signs quality is degrading:

- sudden spike in `template` only
- many `insufficient_information` rows from relevant commercial companies
- DDG 202/403 noise increasing sharply
- excluded or obviously irrelevant legal forms still appearing in embeddings

## Failure modes this runbook should help avoid

- treating missing EBITDA as if it were already approved fast lane
- running `--apply` from staging and mutating the prod DB by accident
- forgetting to reclassify the existing queue after a routing change
- excluding companies from the queue but leaving old embeddings in search
- reading ETA off a warm-up window right after restart
- assuming `done` and `excluded` mean the same thing

## Session handoff checklist

Before ending a semantic-focused session, leave the repo in a state where the
next one can answer these questions in under five minutes:

- Is the worker healthy?
- What are the current deterministic shortcut and fast-lane rules?
- Which legal forms are intentionally excluded?
- Was a queue mutation only dry-run, or already applied?
- What is the latest trustworthy ETA window?
- Is the semantic corpus quality still acceptable?

If any of those are unclear, update this file before you stop.
