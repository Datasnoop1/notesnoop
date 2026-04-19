"""Staatsblad extraction orchestration.

Two entry paths:

1. **Regular-API single filing** (daily incremental):
   `extract_one(pub_row, anthropic_client)` downloads the PDF, OCR's it,
   strips boilerplate, calls Haiku 4.5 directly, parses the tool_use
   block, and persists events + body text. Returns the list of persisted
   event dicts (or an empty list if the filing was pure-volmacht).

2. **Batch-API request building** (backfill):
   `build_batch_request(pub_row, pdf_bytes)` returns one
   `MessageCreateParamsNonStreaming` ready to submit to
   `client.messages.batches.create`. Pairs with `parse_batch_result` +
   `persist_events` for the result-processing side.

Both paths share the same preparation pipeline (`prepare_pdf_for_llm`)
and the same persistence path (`persist_events`) so the LLM output is
handled identically whether it came from the batch or regular API.

All DB writes are idempotent — the dedup unique index on
`staatsblad_event (enterprise_number, pub_reference, event_type,
COALESCE(person_name,''), COALESCE(entity_name,''))` plus ON CONFLICT
DO NOTHING makes re-running a filing a no-op.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Iterable

import httpx
import psycopg2.extras

from .ocr_helper import extract_text_with_fallback
from .boilerplate_stripper import aggressive_section
from .prompt_v3 import (
    STAATSBLAD_EXTRACTION_V3_SYSTEM_V5,
    STAATSBLAD_EXTRACTION_V3_USER,
)
from .tool_v3 import STAATSBLAD_TOOL_DEFINITION_V3


log = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────

# Model identifiers.
HAIKU_ANTHROPIC = "claude-haiku-4-5"

# Token caps.  3000 output covers the worst-case multi-event filing seen
# in the pilot (median was 250 tokens output).  8000-char PDF text is
# the pilot's empirically-stable ceiling — longer filings are extremely
# rare (< 2 % of the corpus) and usually get truncated cleanly at a
# paragraph boundary.
MAX_OUTPUT_TOKENS = 3000
PDF_MAX_CHARS = 8000
MAX_PDF_BYTES = 15 * 1024 * 1024  # 15 MB

# Staatsblad ejustice base URL (matches backend/routers/staatsblad.py).
STAATSBLAD_BASE = "https://www.ejustice.just.fgov.be"

# Valid top-level event_type enum values.  Used both for output
# validation (discard events with an out-of-band event_type) and for
# the CHECK constraint in schema.sql.
VALID_EVENT_TYPES = {
    "admin_event",
    "capital_event",
    "share_transfer",
    "ownership_change",
    "ma_event",
    "liquidation_event",
    "corporate_change",
    "other_notable",
}


# ── Dataclass for parsed publications ────────────────────────


@dataclass
class PreparedFiling:
    """The OCR'd, stripped, ready-for-LLM bundle for a single filing."""

    enterprise_number: str
    pub_reference: str
    pub_date: Any          # psycopg2 returns date or str depending on column
    entity_name: str
    pdf_url: str
    body_text: str         # full OCR'd text, pre-strip (for later excerpt reconstruction)
    stripped_text: str     # post aggressive_section, capped at PDF_MAX_CHARS
    source: str            # 'fitz' | 'easyocr' | 'both_empty'


# ── Filing preparation (shared between regular + batch paths) ──


async def _download_pdf(pdf_url: str) -> bytes:
    """Fetch the ejustice PDF.  Streams + caps size to avoid OOM."""
    full = pdf_url if pdf_url.startswith("http") else f"{STAATSBLAD_BASE}{pdf_url}"
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "GET",
            full,
            timeout=45,
            follow_redirects=True,
            headers={"User-Agent": "Datasnoop/1.0 (+https://datasnoop.be)"},
        ) as resp:
            if resp.status_code != 200:
                log.warning("PDF download %s failed: %s", pdf_url, resp.status_code)
                return b""
            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > MAX_PDF_BYTES:
                log.warning(
                    "PDF %s too large (%s bytes)", pdf_url, content_length,
                )
                return b""
            buf = bytearray()
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                buf.extend(chunk)
                if len(buf) > MAX_PDF_BYTES:
                    log.warning("PDF %s exceeded %d mid-stream", pdf_url, MAX_PDF_BYTES)
                    return b""
            return bytes(buf)


async def prepare_filing(
    pub_row: dict,
    pdf_bytes: Optional[bytes] = None,
) -> Optional[PreparedFiling]:
    """Download + OCR + strip a filing, returning a PreparedFiling ready
    for the LLM.  Returns None if the filing is empty or download failed.

    Pass `pdf_bytes` directly to skip the network download (useful in
    unit tests and when re-processing already-cached PDFs).
    """
    cbe = pub_row["enterprise_number"]
    ref = pub_row.get("reference") or pub_row.get("pub_reference")
    pub_date = pub_row.get("pub_date")
    entity_name = pub_row.get("entity_name") or cbe
    pdf_url = pub_row.get("pdf_url") or ""

    if pdf_bytes is None:
        if not pdf_url:
            log.warning("No pdf_url for %s/%s", cbe, ref)
            return None
        pdf_bytes = await _download_pdf(pdf_url)
    if not pdf_bytes:
        return None

    body_text, source = extract_text_with_fallback(pdf_bytes)
    if not body_text:
        log.warning("Empty body for %s/%s", cbe, ref)
        return None

    stripped = aggressive_section(body_text, entity_name=entity_name, cbe=cbe)
    stripped = stripped[:PDF_MAX_CHARS]
    if not stripped.strip():
        log.info("Stripped text empty for %s/%s (source=%s)", cbe, ref, source)
        return None

    return PreparedFiling(
        enterprise_number=cbe,
        pub_reference=ref,
        pub_date=pub_date,
        entity_name=entity_name,
        pdf_url=pdf_url,
        body_text=body_text,
        stripped_text=stripped,
        source=source,
    )


# ── LLM call construction (regular + batch path) ─────────────


def build_messages_payload(prepared: PreparedFiling) -> tuple[list, list, list]:
    """Return (system, messages, tools) ready for Anthropic SDK.

    `system` is a list with one text block carrying `cache_control:
    ephemeral`.  `tools` is a list with one tool, also cache-marked (the
    pilot's phase-cache-verify proved that the LAST tool position is the
    one that actually caches on Haiku 4.5 + OpenRouter).
    """
    user_content = STAATSBLAD_EXTRACTION_V3_USER.format(
        name=prepared.entity_name,
        cbe=prepared.enterprise_number,
        pdf_text=prepared.stripped_text,
    )
    system = [{
        "type": "text",
        "text": STAATSBLAD_EXTRACTION_V3_SYSTEM_V5,
        "cache_control": {"type": "ephemeral"},
    }]
    messages = [{"role": "user", "content": user_content}]
    tools = [{**STAATSBLAD_TOOL_DEFINITION_V3,
              "cache_control": {"type": "ephemeral"}}]
    return system, messages, tools


def build_batch_request(prepared: PreparedFiling) -> dict:
    """Return a single `Request` dict for `client.messages.batches.create`."""
    system, messages, tools = build_messages_payload(prepared)
    return {
        "custom_id": prepared.pub_reference,
        "params": {
            "model": HAIKU_ANTHROPIC,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": messages,
            "tools": tools,
            "tool_choice": {
                "type": "tool",
                "name": STAATSBLAD_TOOL_DEFINITION_V3["name"],
            },
            "temperature": 0.0,
        },
    }


def extract_tool_use_events(msg_content_blocks: Iterable) -> list[dict]:
    """Pull the `events` array out of an Anthropic tool_use response.

    The API may return mixed text + tool_use blocks; we pick the first
    tool_use matching our tool name.  If the model hallucinates a
    different tool name (shouldn't happen with tool_choice=tool, but
    defensively), we return an empty list.
    """
    for block in msg_content_blocks:
        btype = getattr(block, "type", None) or (
            isinstance(block, dict) and block.get("type")
        )
        bname = getattr(block, "name", None) or (
            isinstance(block, dict) and block.get("name")
        )
        binput = getattr(block, "input", None) or (
            isinstance(block, dict) and block.get("input")
        )
        if btype == "tool_use" and bname == STAATSBLAD_TOOL_DEFINITION_V3["name"]:
            return list((binput or {}).get("events") or [])
    return []


# ── Persistence ──────────────────────────────────────────────


def _coerce_date(raw: Any) -> Optional[date]:
    """Best-effort parse of an event-date string.  Returns None on
    anything other than `YYYY-MM-DD` — we'd rather lose a date than
    store a hallucinated one.
    """
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    return None


def _coerce_number(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        # Allow "5.000.000" (Belgian thousands) or "5,000.00"
        s = str(raw).strip().replace(".", "").replace(",", ".")
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def persist_events(
    conn,
    prepared: PreparedFiling,
    events: list[dict],
    extraction_model: str,
) -> int:
    """Write body text + events to Postgres in one transaction.

    Returns the number of event rows inserted (excluding duplicates).
    The caller owns the connection; we use an inner SAVEPOINT-less
    block because we assume autocommit is OFF and the caller commits /
    rolls back.
    """
    cur = conn.cursor()
    try:
        # Persist the body text first so downstream `/events/search` +
        # the AI-insights rewire in Phase 3d have a single source of
        # truth for the raw filing content.
        cur.execute(
            """INSERT INTO staatsblad_publication_text
                   (pub_reference, enterprise_number, body_text, extraction_source)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (pub_reference) DO UPDATE SET
                   body_text = EXCLUDED.body_text,
                   extraction_source = EXCLUDED.extraction_source,
                   extracted_at = NOW()""",
            (
                prepared.pub_reference,
                prepared.enterprise_number,
                prepared.body_text,
                prepared.source,
            ),
        )

        # Resolve pub_date — we fall back to the filing's publication
        # date for event_date when the event itself has no stated date
        # (so "admin_event but no date" still sorts correctly).
        pub_date = prepared.pub_date
        if isinstance(pub_date, str):
            coerced = _coerce_date(pub_date)
            if coerced is None:
                log.warning(
                    "Unparseable pub_date=%r for %s/%s — skipping filing",
                    pub_date, prepared.enterprise_number, prepared.pub_reference,
                )
                return 0
            pub_date = coerced

        inserted = 0
        for ev in events:
            event_type = (ev.get("event_type") or "").strip()
            if event_type not in VALID_EVENT_TYPES:
                log.warning(
                    "Skipping event with bad event_type=%r for %s/%s",
                    event_type, prepared.enterprise_number, prepared.pub_reference,
                )
                continue
            summary = (ev.get("summary") or "").strip()
            if not summary:
                log.warning(
                    "Skipping event with empty summary for %s/%s",
                    prepared.enterprise_number, prepared.pub_reference,
                )
                continue
            # Hard-enforce the 60-char summary cap in case the model
            # slipped past the schema maxLength on a rare call.
            summary = summary[:60]

            # ON CONFLICT target must reference the unique index's
            # expression list directly — `ON CONSTRAINT <index_name>`
            # doesn't work for UNIQUE INDEX (only UNIQUE CONSTRAINT).
            cur.execute(
                """INSERT INTO staatsblad_event (
                       enterprise_number, pub_reference, pub_date,
                       event_type, sub_type, event_date,
                       person_name, person_role, entity_name,
                       amount_eur, amount_shares, summary, extraction_model
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (enterprise_number, pub_reference, event_type,
                                COALESCE(person_name, ''), COALESCE(entity_name, ''))
                   DO NOTHING""",
                (
                    prepared.enterprise_number,
                    prepared.pub_reference,
                    pub_date,
                    event_type,
                    (ev.get("sub_type") or None),
                    _coerce_date(ev.get("date")),
                    (ev.get("person_name") or None),
                    (ev.get("person_role") or None),
                    (ev.get("entity_name") or None),
                    _coerce_number(ev.get("amount_eur")),
                    _coerce_number(ev.get("amount_shares")),
                    summary,
                    extraction_model,
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
        return inserted
    finally:
        cur.close()


def record_progress(
    conn,
    run_id: str,
    pub_reference: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Upsert one checkpoint row.  Idempotent."""
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO staatsblad_backfill_progress
                   (run_id, pub_reference, status, error, updated_at)
               VALUES (%s, %s, %s, %s, NOW())
               ON CONFLICT (run_id, pub_reference) DO UPDATE SET
                   status = EXCLUDED.status,
                   error = EXCLUDED.error,
                   updated_at = NOW()""",
            (run_id, pub_reference, status, error),
        )
    finally:
        cur.close()


# ── Regular-API single-filing path (daily incremental) ───────


async def extract_one(
    pub_row: dict,
    anthropic_client,  # `anthropic.Anthropic` instance
    conn,              # psycopg2 connection
    run_id: str = "incremental",
) -> dict:
    """Process one publication end-to-end via the regular Anthropic API.

    Returns a dict: {"ok": bool, "events_inserted": int, "error": str|None}.
    Commits the connection on success; rolls back on failure.
    """
    result = {"ok": False, "events_inserted": 0, "error": None}
    prepared = await prepare_filing(pub_row)
    if prepared is None:
        result["error"] = "prepare_failed"
        try:
            record_progress(conn, run_id, pub_row.get("reference", "?"), "failed", "prepare_failed")
            conn.commit()
        except Exception:
            conn.rollback()
        return result

    system, messages, tools = build_messages_payload(prepared)
    try:
        msg = anthropic_client.messages.create(
            model=HAIKU_ANTHROPIC,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice={
                "type": "tool",
                "name": STAATSBLAD_TOOL_DEFINITION_V3["name"],
            },
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.0,
        )
    except Exception as e:
        result["error"] = f"api:{type(e).__name__}:{e}"
        try:
            record_progress(conn, run_id, prepared.pub_reference, "failed", result["error"])
            conn.commit()
        except Exception:
            conn.rollback()
        return result

    events = extract_tool_use_events(msg.content)
    try:
        inserted = persist_events(
            conn, prepared, events, extraction_model=HAIKU_ANTHROPIC,
        )
        record_progress(conn, run_id, prepared.pub_reference, "extracted")
        conn.commit()
        result["ok"] = True
        result["events_inserted"] = inserted
    except Exception as e:
        conn.rollback()
        result["error"] = f"persist:{type(e).__name__}:{e}"
        try:
            record_progress(conn, run_id, prepared.pub_reference, "failed", result["error"])
            conn.commit()
        except Exception:
            conn.rollback()
    return result


# ── Cost guard helper ────────────────────────────────────────


def check_anthropic_balance(api_key: str) -> Optional[float]:
    """Return the remaining Anthropic account balance in USD, or None if
    the API doesn't surface the current balance to this key scope.

    Anthropic exposes an organization usage endpoint; not all keys have
    access.  The caller should treat None as "unknown — proceed but
    track spend locally" rather than halt.
    """
    try:
        resp = httpx.get(
            "https://api.anthropic.com/v1/organizations/usage",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Shape varies; try a couple of common keys.
        balance = (
            data.get("remaining_balance_usd")
            or data.get("balance_usd")
            or (data.get("balance") or {}).get("usd")
        )
        return float(balance) if balance is not None else None
    except Exception:
        return None
