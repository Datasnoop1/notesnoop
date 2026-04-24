"""Bulk enrichment worker — long-running async loop.

Claims jobs from `enrichment_job`, runs the per-company Q2 pipeline
(dormant-bypass → website resolve → scrape → KBO context → Q2 → entity
collision → Haiku escalation → embedding → write), and loops.

Lifecycle contract (see `plans/i-want-to-explore-delightful-storm.md`):
  - `enrichment_enabled` meta flag = false drains after current in-flight
  - `ENRICHMENT_DAILY_BUDGET_USD` caps spend per UTC day
  - WORKER_CONCURRENCY controls parallel in-flight jobs (3s DDG throttle
    is process-global, so true parallelism on DDG is bounded by that)
  - 5 attempts per job; 6th marks dead
  - Stale-claim release every N polls so a worker crash doesn't strand
    jobs as 'claimed' forever

Entry-point: `python -m enrichment_worker` (run with `backend/` on
sys.path, i.e. WORKDIR /app inside the container — see systemd unit at
`deploy/enrichment-worker.service`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import signal
import sys
import time
from contextvars import Token
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Import order matters — `db` + `ai_client` need load_dotenv() to have
# already fired, which happened above.
from db import fetch_all, fetch_one, execute  # noqa: E402
from ai_client import (  # noqa: E402
    BULK_Q2_MODEL,
    BULK_HAIKU_MODEL,
    build_bulk_embedding_text,
    build_template_summary,
    call_haiku_escalation,
    call_q2,
    set_current_endpoint,
    reset_current_endpoint,
)
from embeddings import (  # noqa: E402
    ensure_embedding_table,
    generate_embedding,
    store_company_embedding,
)
from enrichment_queue import (  # noqa: E402
    claim_many,
    ensure_schema as ensure_queue_schema,
    enrichment_enabled,
    mark_done,
    mark_excluded,
    mark_failed,
    meta_flag,
    release_stale,
)
from enrichment_routing import (
    confidence_is_publishable,
    is_fastlane_ebitda,
    is_dormant,
    is_semantic_excluded_form,
    should_escalate,
)  # noqa: E402
from entity_collision import check_entity_collision  # noqa: E402
from scraper import (  # noqa: E402
    duckduckgo_search_website_url,
    scrape_company_site,
)
from semantic_bootstrap import (  # noqa: E402
    ensure_semantic_schema,
    record_worker_heartbeat,
)

# ── Configuration ────────────────────────────────────────────────────

WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "3"))
POLL_INTERVAL_S = float(os.getenv("WORKER_POLL_INTERVAL_S", "2.0"))
IDLE_SLEEP_S = float(os.getenv("WORKER_IDLE_SLEEP_S", "15.0"))
STALE_RELEASE_EVERY_N_POLLS = int(os.getenv("WORKER_STALE_RELEASE_EVERY", "60"))

ENDPOINT_LABEL_PREFIX = "/bulk-enrichment/"


class BudgetGuardUnavailable(Exception):
    """Raised when `daily_spend_usd` can't read the spend log.

    Signals the worker to pause this poll cycle rather than silently
    fall back to "spent $0" and blow through the daily cap during a DB
    outage.
    """
    pass


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def daily_spend_usd() -> float:
    """Sum `cost_usd` from llm_call_log for all bulk-enrichment calls today."""
    try:
        row = fetch_one(
            """
            SELECT COALESCE(SUM(cost_usd), 0)::float AS total
              FROM llm_call_log
             WHERE endpoint LIKE %s
               AND ts >= CURRENT_DATE
            """,
            (ENDPOINT_LABEL_PREFIX + "%",),
        )
        return float(row["total"] or 0.0) if row else 0.0
    except Exception as e:
        logger.exception("daily spend query failed; pausing this cycle")
        # Sanitised message — raw DB error stays in logger.exception output, not in
        # the exception arg that may surface via admin dead-letter views.
        raise BudgetGuardUnavailable("daily spend query failed") from e


def daily_budget_usd() -> float:
    """Admin-configurable daily spend cap. Defaults to $10 per plan.

    Budget ceiling is less critical than actual spend: a DB hiccup reading the
    meta flag should fall back to env/default rather than crash the worker.
    """
    try:
        raw = meta_flag("enrichment_daily_budget")
        if raw is not None:
            return float(raw)
    except Exception:
        logger.exception("meta_flag enrichment_daily_budget failed; using env/default")

    try:
        return float(os.getenv("ENRICHMENT_DAILY_BUDGET_USD", "10"))
    except Exception:
        return 10.0


# ── KBO context assembly ─────────────────────────────────────────────


def _revenue_band(revenue_eur: Optional[float]) -> str:
    if not revenue_eur or revenue_eur <= 0:
        return "unknown"
    r = float(revenue_eur)
    if r >= 100_000_000:
        return "≥100M EUR"
    if r >= 50_000_000:
        return "50-100M EUR"
    if r >= 5_000_000:
        return "5-50M EUR"
    if r >= 500_000:
        return "0.5-5M EUR"
    return "<0.5M EUR"


def _fte_band(fte: Optional[float]) -> str:
    if not fte or fte <= 0:
        return "unknown"
    f = float(fte)
    if f >= 250:
        return "≥250"
    if f >= 50:
        return "50-250"
    if f >= 10:
        return "10-50"
    if f >= 1:
        return "1-10"
    return "<1"


def _load_kbo_context(cbe: str) -> dict:
    """Gather the KBO facts the Q2 prompt needs.

    Pulled from `company_info`, `nace_lookup`, `enterprise`, `financial_
    latest`, `participating_interest`, `shareholder`, `administrator`.
    Keys used by `build_kbo_context_block` / `build_template_summary`.

    Kept read-only — the worker never writes to these tables.
    """
    info = fetch_one(
        """
        SELECT ci.name, ci.city, ci.nace_code,
               nl.description AS nace_description,
               e.juridical_situation,
               e.juridical_form,
               fl.revenue, fl.ebitda, fl.fte_total,
               (SELECT c.value FROM contact c
                  WHERE c.entity_number = ci.enterprise_number
                    AND c.contact_type = 'WEB'
               LIMIT 1) AS kbo_website
          FROM company_info ci
     LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
     LEFT JOIN enterprise e   ON e.enterprise_number = ci.enterprise_number
     LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
         WHERE ci.enterprise_number = %s
        """,
        (cbe,),
    )
    if not info:
        return {"name": "", "hq_city": "", "primary_nace": "",
                "nace_description": "", "juridical_situation": "",
                "juridical_form": "",
                "revenue_band": "unknown", "fte_band": "unknown",
                "majority_shareholders": [], "key_subsidiaries": [],
                "admins_top3": [], "parent": "", "notes": "",
                "kbo_website": None}

    try:
        shareholders = fetch_all(
            """SELECT name, ownership_pct FROM shareholder
                WHERE enterprise_number = %s
                ORDER BY ownership_pct DESC NULLS LAST LIMIT 3""",
            (cbe,),
        )
    except Exception:
        shareholders = []
    try:
        subsidiaries = fetch_all(
            """SELECT name FROM participating_interest
                WHERE enterprise_number = %s
                ORDER BY ownership_pct DESC NULLS LAST LIMIT 5""",
            (cbe,),
        )
    except Exception:
        subsidiaries = []
    try:
        admins = fetch_all(
            """SELECT name FROM administrator
                WHERE enterprise_number = %s AND name IS NOT NULL
             GROUP BY name
                LIMIT 3""",
            (cbe,),
        )
    except Exception:
        admins = []

    parent = ""
    majority = []
    for sh in shareholders:
        name = sh.get("name") or ""
        pct = sh.get("ownership_pct") or 0
        if pct and pct >= 50 and not parent:
            parent = name
        elif name:
            majority.append(f"{name} ({pct:.0f}%)" if pct else name)

    return {
        "name": info.get("name") or "",
        "hq_city": info.get("city") or "",
        "primary_nace": info.get("nace_code") or "",
        "nace_description": info.get("nace_description") or "",
        "juridical_situation": info.get("juridical_situation") or "",
        "juridical_form": info.get("juridical_form") or "",
        "revenue_band": _revenue_band(info.get("revenue")),
        "fte_band": _fte_band(info.get("fte_total")),
        "majority_shareholders": majority[:5],
        "key_subsidiaries": [s.get("name") for s in subsidiaries if s.get("name")],
        "admins_top3": [a.get("name") for a in admins if a.get("name")],
        "parent": parent,
        "notes": "",
        "kbo_website": info.get("kbo_website"),
        "_revenue_eur": info.get("revenue"),
        "_ebitda_eur": info.get("ebitda"),
        "_fte": info.get("fte_total"),
    }


# ── Per-company pipeline ─────────────────────────────────────────────


def _sha256(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest() if text else ""


def _write_bulk_row(
    cbe: str,
    summary: dict,
    website_url: str | None,
    scraped_text: str | None,
) -> None:
    """Upsert `company_enrichment.bulk_*` columns."""
    execute(
        """
        INSERT INTO company_enrichment (enterprise_number, bulk_summary,
                                        bulk_summary_at, bulk_website_hash,
                                        bulk_website_url, bulk_confidence)
        VALUES (%s, %s::jsonb, NOW(), %s, %s, %s)
        ON CONFLICT (enterprise_number) DO UPDATE SET
            bulk_summary      = EXCLUDED.bulk_summary,
            bulk_summary_at   = NOW(),
            bulk_website_hash = EXCLUDED.bulk_website_hash,
            bulk_website_url  = EXCLUDED.bulk_website_url,
            bulk_confidence   = EXCLUDED.bulk_confidence
        """,
        (
            cbe,
            json.dumps(summary, ensure_ascii=False),
            _sha256(scraped_text),
            website_url,
            (summary.get("confidence") or "").strip().lower(),
        ),
    )


_NAME_MATCH_NOISE = {
    "group",
    "holding",
    "consulting",
    "management",
    "services",
    "solutions",
    "association",
    "bank",
    "fund",
    "capital",
    "international",
    "global",
    "europe",
    "european",
    "company",
    "bedrijven",
    "enterprise",
    "industries",
    "industry",
    "medical",
}


def _name_tokens(name: str) -> list[str]:
    tokens = [
        tok for tok in re.findall(r"[a-z0-9]{4,}", (name or "").lower())
        if tok not in _NAME_MATCH_NOISE
    ]
    # Keep order but drop duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _website_likely_matches_company(kbo: dict, website_url: str, scraped_text: str) -> bool:
    """Conservative lexical check to avoid off-topic website summaries.

    We only trust non-KBO-discovered websites when their domain/text
    contain meaningful company-name tokens. This blocks generic SERP
    drift (forums, app stores, encyclopedias) from producing confident
    but wrong Q2 outputs.
    """
    name = (kbo.get("name") or "").strip()
    if not name or not website_url or not scraped_text:
        return False

    tokens = _name_tokens(name)
    if not tokens:
        return False

    parsed = urlparse(website_url)
    host = parsed.netloc.lower().lstrip("www.")
    host_parts = [p for p in host.split(".") if p]
    core = host_parts[-2] if len(host_parts) >= 2 else (host_parts[0] if host_parts else "")
    host_slug = re.sub(r"[^a-z0-9]", "", core)

    text_lower = (scraped_text or "").lower()
    domain_hits = sum(1 for tok in tokens if tok in host_slug)
    text_hits = sum(1 for tok in tokens if tok in text_lower)

    if len(tokens) <= 1:
        return text_hits >= 1 and domain_hits >= 1
    return text_hits >= 2


async def _resolve_website(kbo: dict) -> str | None:
    """KBO contact WEB row wins; fall back to DuckDuckGo discovery."""
    web = (kbo.get("kbo_website") or "").strip()
    if web:
        if not web.startswith("http"):
            web = "https://" + web
        return web

    # Discovery — DDG only, 3s process-global throttle baked into scraper.
    name = (kbo.get("name") or "").strip()
    city = (kbo.get("hq_city") or "").strip()
    if not name:
        return None
    try:
        return await duckduckgo_search_website_url(name, city=city)
    except Exception as e:
        logger.info("DDG discovery failed for %s: %s", name, e)
        return None


async def _enrich_one(cbe: str) -> dict:
    """Run the full per-company flow. Returns a summary-of-outcome dict.

    Never raises — failures are captured and the caller decides whether
    to mark_failed / retry.
    """
    out = {
        "cbe": cbe,
        "ok": False,
        "path": "",      # dormant | template | q2 | q2+haiku
        "confidence": None,
        "website_url": None,
        "scraped_chars": 0,
        "collision_downgrade": False,
        "error": None,
    }

    kbo = _load_kbo_context(cbe)

    # 0. Unknown / branch-only CBE — short-circuit to a no-op done.
    # `_load_kbo_context` returns a sentinel dict with empty name when
    # the CBE isn't in `company_info` (e.g. establishments, branches of
    # foreign entities). No website, no financial signal, no NACE:
    # nothing for Q2 or the template to work with. Skip the embed call
    # too — a "This company is a Belgian company." blurb pollutes the
    # vector space without adding retrieval value.
    if not (kbo.get("name") or "").strip():
        out.update(ok=True, path="skipped_unknown_cbe",
                   confidence="insufficient_information")
        return out

    # 1. Dormant bypass ------------------------------------------------
    if is_semantic_excluded_form(kbo.get("juridical_form")):
        out.update(
            ok=True,
            path="excluded_juridical_form",
            confidence="insufficient_information",
            exclude_reason=f"juridical_form:{kbo.get('juridical_form') or ''}",
        )
        return out

    # 1a. Dormant bypass -----------------------------------------------
    if is_dormant(kbo.get("juridical_situation")):
        summary = build_template_summary(kbo)
        _write_bulk_row(cbe, summary, None, None)
        out.update(ok=True, path="dormant", confidence=summary.get("confidence"))
        # Still embed — templated rows are searchable (confidence floor
        # filters them out of default results, not out of the vector
        # store).
        await _embed_and_store(cbe, summary, kbo)
        return out

    # 1b. Explicit EBITDA fast lane -----------------------------------
    if is_fastlane_ebitda(kbo.get("_ebitda_eur")):
        summary = build_template_summary(kbo)
        _write_bulk_row(cbe, summary, None, None)
        await _embed_and_store(cbe, summary, kbo)
        out.update(
            ok=True,
            path="fastlane_ebitda",
            confidence=summary.get("confidence"),
        )
        return out

    # 2. Website resolve ----------------------------------------------
    website_url = await _resolve_website(kbo)
    out["website_url"] = website_url

    scraped_text = ""
    if website_url:
        try:
            scraped_text, _src = await scrape_company_site(website_url)
        except Exception as e:
            logger.info("scrape_company_site failed for %s: %s", cbe, e)
        # KBO-declared website rows are trusted. Search-discovered URLs
        # must pass a lexical relevance check before Q2 sees the text.
        from_kbo = bool((kbo.get("kbo_website") or "").strip())
        if scraped_text and not from_kbo:
            if not _website_likely_matches_company(kbo, website_url, scraped_text):
                logger.info("website relevance check rejected %s for %s; falling back to template path", website_url, cbe)
                scraped_text = ""
        out["scraped_chars"] = len(scraped_text or "")

    # 3. If we have no scrape and no financial signal, templated fallback
    if not scraped_text:
        summary = build_template_summary(kbo)
        _write_bulk_row(cbe, summary, website_url, scraped_text)
        await _embed_and_store(cbe, summary, kbo)
        out.update(ok=True, path="template", confidence=summary.get("confidence"))
        return out

    # 4. Q2 call ------------------------------------------------------
    q2 = await call_q2(kbo=kbo, scraped_text=scraped_text)
    if not q2.get("ok") or not q2.get("summary"):
        # Q2 failure. Write a template so the row is searchable, mark
        # the job as failed so it is retried; don't poison the queue.
        summary = build_template_summary(kbo)
        _write_bulk_row(cbe, summary, website_url, scraped_text)
        await _embed_and_store(cbe, summary, kbo)
        out.update(ok=False, path="q2_failed",
                   confidence=summary.get("confidence"),
                   error=q2.get("error") or "q2_unknown")
        return out

    summary = q2["summary"]

    # 5. Entity-collision check — downgrade confidence if implausible
    try:
        collision = await check_entity_collision(
            company_name=kbo.get("name") or "",
            kbo_nace_description=kbo.get("nace_description"),
            kbo_hq_city=kbo.get("hq_city"),
            q2_summary=summary,
        )
        if not collision.get("plausible"):
            summary["confidence"] = "low"
            summary["business_description"] = (
                summary.get("business_description", "")
                + " [Entity match with KBO record uncertain — flagged by "
                "plausibility check.]"
            )
            out["collision_downgrade"] = True
    except Exception as e:
        logger.info("collision check skipped for %s: %s", cbe, e)

    # 6. Escalation -------------------------------------------------
    from enrichment_routing import classify_tier

    tier = classify_tier(kbo.get("_revenue_eur"), kbo.get("_fte"))
    escalate, reason = should_escalate(
        tier=tier,
        q2_confidence=summary.get("confidence"),
        kbo_notes=kbo.get("notes"),
    )
    path = "q2"
    if escalate:
        hk = await call_haiku_escalation(
            kbo=kbo, scraped_text=scraped_text, q2_summary=summary,
        )
        if hk.get("ok") and hk.get("summary"):
            summary = hk["summary"]
            path = "q2+haiku"
        else:
            logger.info(
                "Haiku escalation failed for %s (reason=%s): %s",
                cbe, reason, hk.get("error"),
            )

    # 7. Persist + embed --------------------------------------------
    _write_bulk_row(cbe, summary, website_url, scraped_text)
    await _embed_and_store(cbe, summary, kbo)

    out.update(ok=True, path=path, confidence=summary.get("confidence"))
    return out


async def _embed_and_store(cbe: str, summary: dict, kbo: dict) -> None:
    """Compute the embedding text, call the embedder, upsert.

    Uses the Q2-aligned text builder when a real summary exists, and
    falls back to a NACE + city anchor when nothing is available (e.g.
    insufficient_information templates). Keeping the embed step here —
    not inside _enrich_one's branches — so every path lands the same
    row in `company_embedding`.
    """
    try:
        text = build_bulk_embedding_text(summary, kbo)
        if not text or len(text) < 20:
            logger.info("embed skipped for %s: no substantive text", cbe)
            return
        ensure_embedding_table()
        emb = await generate_embedding(text)
        if emb:
            store_company_embedding(cbe, emb)
    except Exception as e:
        # Embedding failure shouldn't sink the whole job — the bulk row
        # is already persisted and can be embedded in a follow-up run.
        logger.warning("embedding persist failed for %s: %s", cbe, e)


# ── Worker loop ──────────────────────────────────────────────────────


class Worker:
    """Tiny supervisor around the concurrent enrich loop."""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._in_flight = 0
        self._poll_count = 0

    def request_stop(self) -> None:
        logger.info("stop requested — draining in-flight jobs")
        self._stop.set()

    def _launch_job(
        self,
        job: dict,
        sem: asyncio.Semaphore,
        tasks: set[asyncio.Task],
    ) -> None:
        """Start one claimed job in the background.

        `_in_flight` increments at launch time so the outer loop can make
        accurate fill decisions without racing the task startup.
        """
        self._in_flight += 1
        record_worker_heartbeat(
            "working",
            f"cbe={job['enterprise_number']}",
        )

        async def _run(j=job):
            token: Token | None = None
            try:
                token = set_current_endpoint(
                    ENDPOINT_LABEL_PREFIX + j["enterprise_number"]
                )
                result = await _enrich_one(j["enterprise_number"])
                if result.get("ok"):
                    if result.get("path") == "excluded_juridical_form":
                        mark_excluded(j["enterprise_number"])
                        logger.info(
                            "excluded cbe=%s path=%s reason=%s",
                            j["enterprise_number"],
                            result["path"],
                            result.get("exclude_reason"),
                        )
                    else:
                        mark_done(j["enterprise_number"])
                        logger.info(
                            "done cbe=%s path=%s conf=%s chars=%d collide=%s",
                            j["enterprise_number"], result["path"],
                            result["confidence"], result["scraped_chars"],
                            result["collision_downgrade"],
                        )
                else:
                    mark_failed(
                        j["enterprise_number"],
                        result.get("error") or "unknown",
                    )
                    logger.info(
                        "failed cbe=%s attempt=%s error=%s",
                        j["enterprise_number"], j["attempts"],
                        result.get("error"),
                    )
                record_worker_heartbeat(
                    "working" if self._in_flight > 1 else "idle",
                    f"last_cbe={j['enterprise_number']}",
                )
            except Exception as e:
                logger.exception("enrich crash cbe=%s", j["enterprise_number"])
                try:
                    mark_failed(j["enterprise_number"], f"crash:{e!r}")
                except Exception:
                    logger.exception("mark_failed itself failed")
                record_worker_heartbeat("error", f"crash:{j['enterprise_number']}")
            finally:
                self._in_flight -= 1
                if token is not None:
                    reset_current_endpoint(token)
                sem.release()

        task = asyncio.create_task(_run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def run(self) -> None:
        """Main loop. Polls, fans out claims, waits for completions."""
        record_worker_heartbeat("starting", "boot")
        ensure_queue_schema()
        ensure_semantic_schema()
        # Warm-up: release any stale claims from a prior crash.
        try:
            n = release_stale(older_than_minutes=30)
            if n:
                logger.info("released %d stale claims on startup", n)
        except Exception:
            logger.exception("initial stale-release failed (non-fatal)")

        sem = asyncio.Semaphore(WORKER_CONCURRENCY)
        tasks: set[asyncio.Task] = set()

        while not self._stop.is_set():
            # Free any completed tasks before computing available worker slots.
            tasks = {task for task in tasks if not task.done()}

            if not enrichment_enabled():
                logger.info("meta.enrichment_enabled=false — sleeping")
                record_worker_heartbeat("paused", "disabled")
                await asyncio.sleep(IDLE_SLEEP_S)
                continue

            try:
                spend = daily_spend_usd()
            except BudgetGuardUnavailable:
                logger.warning("budget guard unavailable, pausing this cycle")
                record_worker_heartbeat("paused", "budget_guard_unavailable")
                await asyncio.sleep(IDLE_SLEEP_S)
                continue
            budget = daily_budget_usd()
            if spend >= budget:
                logger.info(
                    "daily spend $%.3f >= budget $%.2f — sleeping until reset",
                    spend, budget,
                )
                record_worker_heartbeat(
                    "paused",
                    f"budget:{spend:.3f}/{budget:.2f}",
                )
                await asyncio.sleep(IDLE_SLEEP_S)
                continue

            self._poll_count += 1
            if self._poll_count % STALE_RELEASE_EVERY_N_POLLS == 0:
                try:
                    release_stale(older_than_minutes=30)
                except Exception:
                    logger.exception("periodic stale-release failed")

            free_slots = max(0, WORKER_CONCURRENCY - self._in_flight)
            if free_slots <= 0:
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            jobs: list[dict] = []
            try:
                jobs = claim_many(free_slots)
            except Exception:
                logger.exception("claim_many failed")
                record_worker_heartbeat("error", "claim_many_failed")
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            if not jobs:
                # Queue is empty or temporarily exhausted. If work is still
                # running, poll again soon instead of going fully idle.
                record_worker_heartbeat(
                    "working" if self._in_flight > 0 else "idle",
                    "queue_empty" if self._in_flight == 0 else "awaiting_in_flight",
                )
                await asyncio.sleep(POLL_INTERVAL_S if self._in_flight > 0 else IDLE_SLEEP_S)
                continue

            for job in jobs:
                await sem.acquire()
                # Re-check the stop flag between acquire and task create
                # so a SIGTERM landing in that window doesn't leak the
                # semaphore slot. The job stays in 'claimed' status; the
                # next worker boot's startup release_stale(30 min) will
                # return it to the queue.
                if self._stop.is_set():
                    sem.release()
                    break
                self._launch_job(job, sem, tasks)

        # Drain: let in-flight tasks finish before returning.
        if tasks:
            logger.info("waiting for %d in-flight jobs to drain", len(tasks))
            record_worker_heartbeat("draining", f"in_flight={len(tasks)}")
            await asyncio.gather(*tasks, return_exceptions=True)
        record_worker_heartbeat("stopped", "clean_exit")


async def _amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info(
        "enrichment-worker starting: concurrency=%d poll=%.1fs budget=$%.2f",
        WORKER_CONCURRENCY, POLL_INTERVAL_S, daily_budget_usd(),
    )
    worker = Worker()
    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, worker.request_stop)
    except (NotImplementedError, ValueError):
        # Windows-friendly: add_signal_handler isn't supported there,
        # so rely on KeyboardInterrupt bubbling up.
        pass
    await worker.run()
    logger.info("enrichment-worker stopped")


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        logger.info("interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
