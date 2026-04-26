# Staatsblad Pipeline — Operations Runbook

The Staatsblad pipeline ingests Belgian Official Gazette (`ejustice.just.fgov.be`)
publications and turns them into structured **events** (admin appointments,
capital changes, share transfers, M&A, dissolutions, etc.) that surface on
the company profile and in semantic search.

This is the doc to read first for **anyone touching Staatsblad code** —
the producer / consumer / scraper roles are split across machines and the
naming is non-obvious.

Read together with:

- `docs/architecture.md`
- `docs/product.md`
- `CLAUDE.md`

---

## Components

| Role | Where | Script | Cadence |
|---|---|---|---|
| **Producer** | RunPod (5y backfill) | `scripts/staatsblad_backfill.py` | one-shot, resumable |
| **Consumer** | Hetzner | `scripts/staatsblad_batch_every_2d.py` | cron every 2 days at 04:00 |
| **Bulk scraper** | Hetzner | `scripts/staatsblad_bulk_scrape.py` | manual, drains queue |
| **Embedder** | Hetzner | `scripts/staatsblad_embed.py` | runs after each extraction pass |
| **On-demand loader** | Backend | `backend/routers/staatsblad.py` | per-CBE API call (24 h cooldown) |
| **Event API** | Backend | `backend/routers/staatsblad_events.py` | reads only |

The producer + consumer talk to the **same Postgres database** through the
queue tables below. There is no message broker. Postgres `FOR UPDATE SKIP
LOCKED` makes multi-worker safe.

---

## Data flow

```
ejustice.just.fgov.be
        │
        │  scrape (httpx + Webshare proxy or 1 req/s direct)
        ▼
┌────────────────────────────┐
│ staatsblad_publication      │  raw publication metadata
│ (cbe, pub_date, pub_type,   │  ON CONFLICT DO NOTHING
│  reference, pdf_url, …)     │
└────────────────────────────┘
        │  PDF download + OCR (PyMuPDF / EasyOCR)
        ▼
┌────────────────────────────┐
│ staatsblad_publication_text │  cached OCR body, reused
└────────────────────────────┘
        │  Anthropic batch API (claude-3-5-haiku, 50% discount)
        ▼
┌────────────────────────────┐
│ staatsblad_event            │  structured events
│ (admin/capital/m&a/…)       │  unique on (cbe, ref, type, person, entity)
└────────────────────────────┘
        │  embed (text-embedding-3-small, 256 dim)
        ▼
┌────────────────────────────┐
│ staatsblad_event_embedding  │  pgvector for /events/search
└────────────────────────────┘
```

---

## Tables

| Table | Notes |
|---|---|
| `staatsblad_publication` | `(enterprise_number, pub_date, reference)` PK. ~1M+ rows. |
| `staatsblad_publication_text` | OCR cache. Keyed on `pub_reference`. |
| `staatsblad_event` | Structured events. Dedup unique index on `(enterprise_number, pub_reference, event_type, person_name, entity_name)`. |
| `staatsblad_event_embedding` | 256-dim vectors. ON DELETE CASCADE. Schema comment may say 1024 — that is wrong; the live setting is 256. |
| `staatsblad_backfill_progress` | `(run_id, pub_reference)` checkpoint table. Resume is safe — re-runs skip `status='extracted'`. |
| `staatsblad_bulk_queue` | Bulk scrape work queue. `(cbe)` PK; partial indexes on pending / in_progress for fast dequeue. |

---

## Status signals

The admin **Data Readiness** dashboard reads these queries to decide
healthy / warning / broken for the Staatsblad block. Replicate them
locally if you need to debug:

```sql
-- Total events extracted, plus 24h / 7d throughput
SELECT
  (SELECT COUNT(*) FROM staatsblad_event)                                AS events_total,
  (SELECT COUNT(*) FROM staatsblad_event WHERE extracted_at >= NOW() - INTERVAL '24 hours') AS events_24h,
  (SELECT COUNT(*) FROM staatsblad_event WHERE extracted_at >= NOW() - INTERVAL '7 days')  AS events_7d,
  (SELECT MAX(extracted_at) FROM staatsblad_event)                       AS last_extraction;

-- Bulk-scrape queue health
SELECT status, COUNT(*) FROM staatsblad_bulk_queue GROUP BY status;

-- Recent failures (last 5)
SELECT cbe, last_error
FROM staatsblad_bulk_queue
WHERE status = 'failed' AND last_error IS NOT NULL
ORDER BY completed_at DESC
LIMIT 5;
```

The unified backend route is `GET /api/admin/readiness` (admin-only).

### Health rules (from `backend/routers/admin_phase22.py`)

* **broken** — no `staatsblad_event` extracted in the last 36 h
* **warning** — no event in 12 h, or `staatsblad_bulk_queue.status='failed'` count > 25, or daily throughput < 50
* **healthy** — otherwise

---

## Cron

`crontab -e` on the prod server contains:

```
0 4 */2 * *  docker exec leadpeek-backend-1 python /app/scripts/staatsblad_batch_every_2d.py >> /var/log/staatsblad_batch.log 2>&1
```

The batch consumer captures the last 72 h of new publications that lack
events, filtered to event-dense `pub_type` values (NOMINATION, CAPITAL,
FUSION, DISSOLUTION variants). Cheaper than daily incremental; the
Anthropic batch API 50% discount amortises ~$10–20/month.

There is **no daily incremental cron** — that was deliberately removed
when the 2-day batch landed.

---

## Bulk scrape — operator workflow

When new candidates need to be added to coverage (e.g. a fresh KBO load
brings in companies without Staatsblad publications):

```bash
# Seed from financial_latest \ staatsblad_publication
docker compose -p leadpeek exec backend \
  python scripts/staatsblad_bulk_scrape.py --seed --workers 20

# Drain the queue (Webshare proxies, ~10 req/s)
docker compose -p leadpeek exec backend \
  python scripts/staatsblad_bulk_scrape.py --drain

# Slow mode without proxies (1 req/s)
docker compose -p leadpeek exec backend \
  python scripts/staatsblad_bulk_scrape.py --drain --mode slow
```

The queue auto-resets stale locks older than 10 minutes — a worker crash
won't strand jobs.

---

## Failure modes

| Symptom | Likely cause | Action |
|---|---|---|
| Queue stuck in `in_progress > 10 min` | Worker crash, network blip | Self-resets; manual: `UPDATE staatsblad_bulk_queue SET status='pending', locked_at=NULL WHERE locked_at < NOW()-INTERVAL '10 min';` |
| Anthropic batch never `ended` after 24 h | Anthropic backend slow | `python -c "import anthropic; print(anthropic.Anthropic().messages.batches.retrieve('<batch_id>'))"` |
| `extract_domicile` returns NULL | OCR noise, non-Belgian format, or name not present | Regex-based, no LLM fallback. Confidence 0.6-1.0 expected. |
| pgvector search slow / high mem | IVFflat with 100 lists on 100k+ rows | `REINDEX INDEX CONCURRENTLY idx_staatsblad_event_embedding_cos;` |
| ejustice.be rate-limit | Too many workers / no proxy rotation | Reduce `--workers` or use `--mode slow` |

---

## Cost envelope

* **Bulk scrape**: free. Webshare proxies are paid by the month, not per
  request.
* **Anthropic batch**: ~$0.20–0.40 per 1k filings (claude-3-5-haiku batch
  is 50% off the standard rate).
* **Embeddings**: ~$0.09 to embed all 110k existing events.
* **Cap**: producer respects `--max-spend-usd` to bound a backfill run.

---

## Session-handoff checklist

Leave the repo in a state where the next session can answer in <5 min:

* What was the most recent extraction (`MAX(extracted_at)`)?
* Is the bulk scraper drained or stuck?
* Have new pub_types been added to the consumer filter?
* Is the embedding backfill caught up?

If any of those are unclear, update this file before stopping.
