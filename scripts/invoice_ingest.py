"""Invoice ingester — reads invoice@datasnoop.be inbox and stores rows in
platform_invoice for the admin P&L page.

Connects via IMAP (Stalwart mail server on the Hetzner host — same creds
scheme as SMTP, using INVOICE_IMAP_HOST/USER/PASS env vars). Parses the
email body + any PDF attachment with best-effort regex for total amount,
invoice date, vendor. Saves the raw body for audit.

Deduplicates by RFC822 Message-ID, so re-running is safe.

Run via cron nightly:
    0 4 * * * cd /opt/leadpeek && docker exec leadpeek-backend-1 \
        python /app/../scripts/invoice_ingest.py \
        >> scripts/_watchdog_state/invoices.log 2>&1

Best-effort parser — any ambiguous invoice (multiple totals in the body,
foreign currency, attachment with no text layer) is still stored but
marked confirmed=false. Operator reviews in admin UI.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import ssl
import sys
from datetime import datetime
from email.message import Message
from io import BytesIO
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import execute, fetch_one  # type: ignore
from invoice_classifier import classify_invoice  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("invoice_ingest")


IMAP_HOST = os.getenv("INVOICE_IMAP_HOST", os.getenv("SMTP_HOST", "host.docker.internal"))
IMAP_PORT = int(os.getenv("INVOICE_IMAP_PORT", "993"))
IMAP_USER = os.getenv("INVOICE_IMAP_USER", "invoice@datasnoop.be")
IMAP_PASS = os.getenv("INVOICE_IMAP_PASS", "")
IMAP_MAILBOX = os.getenv("INVOICE_IMAP_MAILBOX", "INBOX")
# How many recent messages to scan per run
SCAN_LIMIT = int(os.getenv("INVOICE_SCAN_LIMIT", "100"))


# Amount regex: handles €1.234,56 / EUR 1,234.56 / 1234.56 EUR / 1 234,56 €
# Priority order: labeled totals first, then any currency-marked number.
_AMT_LABELS = [
    r"total\s+(?:incl\.?|inclusive)?[^\d]{0,12}",
    r"amount\s+due[^\d]{0,12}",
    r"grand\s+total[^\d]{0,12}",
    r"invoice\s+total[^\d]{0,12}",
    r"te\s+betalen[^\d]{0,12}",           # nl: "to pay"
    r"totaal\s+(?:incl\.?\s+btw)?[^\d]{0,12}",
    r"montant\s+(?:total|du|TTC)[^\d]{0,12}",
    r"total\s+TTC[^\d]{0,12}",
]
_AMT_NUMBER = r"(\d{1,3}(?:[\s.,]\d{3})*(?:[.,]\d{2}))"
_AMT_CURRENCY = r"(?:\s*(?:€|EUR|eur))"
_AMOUNT_RX = re.compile(
    rf"(?:{'|'.join(_AMT_LABELS)}).*?{_AMT_NUMBER}{_AMT_CURRENCY}?",
    re.IGNORECASE | re.DOTALL,
)
_FALLBACK_RX = re.compile(rf"{_AMT_NUMBER}{_AMT_CURRENCY}", re.IGNORECASE)

_DATE_RX = re.compile(
    r"(?:invoice\s+date|date\s+d[e'’]\s+facture|factuurdatum|facturation)[^\d]{0,20}"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def parse_amount(text: str) -> Optional[int]:
    """Return cents as int, or None if nothing parses convincingly."""
    if not text:
        return None
    m = _AMOUNT_RX.search(text)
    if not m:
        m = _FALLBACK_RX.search(text)
    if not m:
        return None
    raw = m.group(1)
    # Normalise: "1.234,56" → "1234.56", "1,234.56" → "1234.56"
    raw = raw.strip().replace(" ", "")
    if "," in raw and "." in raw:
        # Assume the last separator is decimal; strip the other as thousands
        last = max(raw.rfind(","), raw.rfind("."))
        dec_sep = raw[last]
        if dec_sep == ",":
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        # European — comma decimal
        raw = raw.replace(".", "").replace(",", ".")
    # else pure dots — assume decimal or no separator
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(round(value * 100))


def parse_date(text: str) -> Optional[str]:
    """Return ISO date string or None."""
    if not text:
        return None
    m = _DATE_RX.search(text)
    if not m:
        return None
    raw = m.group(1)
    # Try common formats
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
                "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_pdf_text(payload: bytes) -> str:
    """Best-effort PDF text extraction. Returns empty string on failure."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            return ""
    try:
        reader = PdfReader(BytesIO(payload))
        out = []
        for p in reader.pages[:5]:  # cap at 5 pages — invoices are short
            try:
                out.append(p.extract_text() or "")
            except Exception:
                continue
        return "\n".join(out)
    except Exception:
        return ""


def get_body(msg: Message) -> tuple[str, list[tuple[str, bytes]]]:
    """Return (text_body, pdf_attachments).

    pdf_attachments is a list of (filename, bytes) — one per PDF attachment.
    A single email can bundle several invoices; we process each PDF as its
    own invoice row so the operator doesn't have to forward them one at a
    time.
    """
    text_parts: list[str] = []
    pdfs: list[tuple[str, bytes]] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    text_parts.append(part.get_payload(decode=True).decode("utf-8", errors="replace"))
                except Exception:
                    continue
            elif ctype == "text/html" and "attachment" not in disp and not text_parts:
                try:
                    html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    text_parts.append(re.sub(r"<[^>]+>", " ", html))
                except Exception:
                    continue
            elif ctype == "application/pdf":
                try:
                    fname = part.get_filename() or f"attachment-{len(pdfs)+1}.pdf"
                    data = part.get_payload(decode=True)
                    if data:
                        pdfs.append((fname, data))
                except Exception:
                    continue
    else:
        try:
            text_parts.append(msg.get_payload(decode=True).decode("utf-8", errors="replace"))
        except Exception:
            pass
    return "\n\n".join(text_parts).strip(), pdfs


def already_stored(message_id: str) -> bool:
    """True if we've already ingested at least one row for this email."""
    if not message_id:
        return False
    return fetch_one(
        "SELECT 1 FROM platform_invoice WHERE message_id LIKE %s",
        (f"{message_id}%",),
    ) is not None


def _clean(s: str) -> str:
    """Strip NUL bytes (Postgres rejects them) + collapse runs of control
    chars. Invoice PDFs often surface NULs between extracted glyphs."""
    if not s:
        return s
    s = s.replace("\x00", "")
    # Drop other C0 controls except \t \n \r
    return "".join(ch for ch in s if ch in "\t\n\r" or ord(ch) >= 0x20)


def store(message_id: str, sender: str, subject: str, invoice_date: Optional[str],
          amount_cents: Optional[int], raw_body: str) -> None:
    """Store a single invoice row. For multi-PDF emails the caller passes
    a synthesised Message-ID suffix (e.g. '<orig>#pdf-2') so each PDF
    gets its own row without fighting the UNIQUE constraint.

    Also classifies the invoice via OpenRouter (vendor + category) if the
    API key is configured. Classification failure is non-fatal: the row
    gets NULL vendor/category and the admin backfill endpoint can retry.
    """
    classification = classify_invoice(sender, subject, raw_body)
    vendor = classification.get("vendor")
    category = classification.get("category")
    execute(
        """
        INSERT INTO platform_invoice
            (message_id, sender, subject, invoice_date, amount_cents,
             raw_body, vendor, category)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (message_id) DO NOTHING
        """,
        (_clean(message_id), _clean(sender), _clean(subject),
         invoice_date, amount_cents, _clean(raw_body)[:50000],
         _clean(vendor) if vendor else None,
         category),
    )


def run() -> None:
    if not IMAP_PASS:
        log.error("INVOICE_IMAP_PASS not set — aborting")
        sys.exit(2)

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    log.info("Connecting to IMAP %s:%d as %s", IMAP_HOST, IMAP_PORT, IMAP_USER)
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx) as imap:
        imap.login(IMAP_USER, IMAP_PASS)
        imap.select(IMAP_MAILBOX, readonly=True)
        typ, data = imap.search(None, "ALL")
        if typ != "OK":
            log.error("IMAP search failed: %s", data)
            return
        all_ids = (data[0] or b"").split()
        recent_ids = all_ids[-SCAN_LIMIT:] if len(all_ids) > SCAN_LIMIT else all_ids
        log.info("Scanning %d most recent messages", len(recent_ids))

        new_count = 0
        for mid in recent_ids:
            typ, msg_data = imap.fetch(mid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            message_id = (msg.get("Message-ID") or "").strip().strip("<>")
            if not message_id:
                continue
            if already_stored(message_id):
                continue

            sender = (msg.get("From") or "").strip()
            subject = (msg.get("Subject") or "").strip()

            body_text, pdfs = get_body(msg)

            # Multi-invoice handling: one row per PDF attachment. Falls
            # back to a body-only row when the email has no PDF (e.g. the
            # invoice is inline text).
            if pdfs:
                for idx, (fname, pdf_bytes) in enumerate(pdfs, start=1):
                    pdf_text = extract_pdf_text(pdf_bytes) or ""
                    scan = pdf_text + "\n" + body_text
                    amt = parse_amount(scan)
                    inv_date = parse_date(scan)
                    row_mid = message_id if len(pdfs) == 1 else f"{message_id}#pdf-{idx}"
                    row_subject = subject if len(pdfs) == 1 else f"{subject} — {fname}"
                    store(row_mid, sender, row_subject, inv_date, amt,
                          (pdf_text[:25000] + "\n\n" + body_text[:10000]))
                    new_count += 1
                    log.info("stored (pdf %d/%d): %s | %s | %s cents",
                             idx, len(pdfs), sender[:40], fname[:40],
                             amt if amt is not None else "?")
            else:
                amount_cents = parse_amount(body_text)
                invoice_date = parse_date(body_text)
                store(message_id, sender, subject, invoice_date, amount_cents, body_text)
                new_count += 1
                log.info("stored: %s | %s | %s cents",
                         sender[:40], subject[:50],
                         amount_cents if amount_cents is not None else "?")

        log.info("invoice_ingest done: %d new", new_count)


if __name__ == "__main__":
    run()
