"""Weekly email digest of new data on a user's favourited companies.

Run as a host cron job (or `docker exec leadpeek-backend-1 python ...`).

For each registered user with at least one favourite, this script:
  1. Finds the timestamp of their last sent digest (or 7 days ago for the
     first run).
  2. Looks up new NBB filings and Staatsblad publications since that time
     for any of their favourited companies.
  3. If anything is new, composes a short plain-text + HTML email and
     sends it via SMTP.
  4. Records the run in `user_digest_log` so the next invocation only
     surfaces newer events.

Required env (in `.env.production` on the server):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, PUBLIC_BASE_URL

Defaults to dry-run mode — pass ``--send`` to actually email. ``--user
<email>`` restricts the run to one inbox for testing.
"""

import argparse
import logging
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Make `from db import ...` work when running standalone from /scripts.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from db import fetch_all, fetch_one, execute  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("alert_digest")


SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM", "claude@datasnoop.be")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://datasnoop.be")
DEFAULT_LOOKBACK_DAYS = 7


def _ensure_log_table() -> None:
    """Create user_digest_log if missing — runs once per invocation."""
    execute(
        """
        CREATE TABLE IF NOT EXISTS user_digest_log (
            user_email      TEXT PRIMARY KEY,
            last_sent_at    TIMESTAMP NOT NULL DEFAULT NOW(),
            event_count     INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def _users_with_favourites() -> list[str]:
    rows = fetch_all(
        """
        SELECT DISTINCT u.email
        FROM user_roles u
        JOIN favourite f ON f.user_id = u.email OR f.user_id::text = u.id::text
        WHERE u.email IS NOT NULL
          AND u.email LIKE '%@%'
          AND COALESCE(u.role, 'user') NOT IN ('blocked', 'anon')
        """
    )
    return [r["email"] for r in rows or []]


def _events_for_user(email: str, since: datetime) -> dict:
    """Return new filings + publications for this user's favourites since ``since``."""
    filings = fetch_all(
        """
        SELECT DISTINCT nll.enterprise_number,
               nll.fiscal_year,
               nll.loaded_at,
               COALESCE(ci.name, nll.enterprise_number) AS name
        FROM favourite f
        JOIN nbb_load_log nll ON nll.enterprise_number = f.enterprise_number
        LEFT JOIN company_info ci ON ci.enterprise_number = f.enterprise_number
        WHERE f.user_id = %s
          AND nll.loaded_at > %s
          AND nll.deposit_key != 'NO_FILINGS'
        ORDER BY nll.loaded_at DESC
        LIMIT 200
        """,
        (email, since),
    )
    pubs = fetch_all(
        """
        SELECT DISTINCT sp.enterprise_number,
               sp.pub_date,
               sp.pub_type,
               COALESCE(ci.name, sp.entity_name, sp.enterprise_number) AS name
        FROM favourite f
        JOIN staatsblad_publication sp ON sp.enterprise_number = f.enterprise_number
        LEFT JOIN company_info ci ON ci.enterprise_number = f.enterprise_number
        WHERE f.user_id = %s
          AND sp.loaded_at > %s
        ORDER BY sp.pub_date DESC
        LIMIT 200
        """,
        (email, since),
    )
    return {"filings": filings or [], "publications": pubs or []}


def _build_email(email: str, events: dict) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for the digest email."""
    n_fil = len(events["filings"])
    n_pub = len(events["publications"])
    subject = f"DataSnoop weekly digest — {n_fil + n_pub} new event(s)"

    lines: list[str] = [
        "Here's what's new on your favourited companies this week.",
        "",
    ]
    if n_fil:
        lines.append(f"New NBB filings ({n_fil}):")
        for r in events["filings"][:30]:
            lines.append(
                f"  - {r['name']} (FY{r['fiscal_year']}) "
                f"— {PUBLIC_BASE_URL}/company/{r['enterprise_number']}"
            )
        if n_fil > 30:
            lines.append(f"  ... and {n_fil - 30} more.")
        lines.append("")
    if n_pub:
        lines.append(f"New Staatsblad publications ({n_pub}):")
        for r in events["publications"][:30]:
            lines.append(
                f"  - {r['name']} ({r['pub_date']}) — {r.get('pub_type') or 'publication'} "
                f"— {PUBLIC_BASE_URL}/company/{r['enterprise_number']}"
            )
        if n_pub > 30:
            lines.append(f"  ... and {n_pub - 30} more.")
        lines.append("")
    lines.append("To stop receiving this email, remove your favourites or reply STOP.")

    text_body = "\n".join(lines)

    def _row(name: str, link: str, sub: str) -> str:
        return (
            f'<li style="margin:4px 0"><a href="{link}" style="color:#4f46e5">{name}</a> '
            f'<span style="color:#94a3b8;font-size:12px">{sub}</span></li>'
        )

    html_parts = [
        '<div style="font-family:system-ui,sans-serif;max-width:560px">',
        '<h2 style="font-size:16px;color:#0f172a">DataSnoop weekly digest</h2>',
    ]
    if n_fil:
        html_parts.append('<h3 style="font-size:13px;color:#475569">New NBB filings</h3><ul>')
        for r in events["filings"][:30]:
            html_parts.append(
                _row(
                    str(r["name"]),
                    f"{PUBLIC_BASE_URL}/company/{r['enterprise_number']}",
                    f"FY{r['fiscal_year']}",
                )
            )
        html_parts.append("</ul>")
    if n_pub:
        html_parts.append('<h3 style="font-size:13px;color:#475569">New Staatsblad publications</h3><ul>')
        for r in events["publications"][:30]:
            html_parts.append(
                _row(
                    str(r["name"]),
                    f"{PUBLIC_BASE_URL}/company/{r['enterprise_number']}",
                    f"{r['pub_date']} — {r.get('pub_type') or 'publication'}",
                )
            )
        html_parts.append("</ul>")
    html_parts.append(
        '<p style="font-size:11px;color:#94a3b8;margin-top:18px">'
        "To stop receiving this digest, remove your favourites or reply STOP."
        "</p></div>"
    )
    html_body = "\n".join(html_parts)
    return subject, text_body, html_body


def _send(email: str, subject: str, text_body: str, html_body: str) -> None:
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        raise RuntimeError(
            "SMTP_HOST / SMTP_USER / SMTP_PASS must be set in env to send."
        )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_FROM, [email], msg.as_string())


def _record_sent(email: str, event_count: int) -> None:
    execute(
        """
        INSERT INTO user_digest_log (user_email, last_sent_at, event_count)
        VALUES (%s, NOW(), %s)
        ON CONFLICT (user_email)
          DO UPDATE SET last_sent_at = NOW(), event_count = EXCLUDED.event_count
        """,
        (email, event_count),
    )


def run(send: bool, only_user: str | None) -> None:
    _ensure_log_table()
    users = [only_user] if only_user else _users_with_favourites()
    log.info("Digest run: %d user(s), send=%s", len(users), send)

    fallback_since = datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    for email in users:
        try:
            row = fetch_one(
                "SELECT last_sent_at FROM user_digest_log WHERE user_email = %s",
                (email,),
            )
            since = row["last_sent_at"] if row and row.get("last_sent_at") else fallback_since
            events = _events_for_user(email, since)
            n = len(events["filings"]) + len(events["publications"])
            if n == 0:
                log.info("No new events for %s (since %s)", email, since)
                continue
            subject, text_body, html_body = _build_email(email, events)
            log.info("Digest for %s: %d events", email, n)
            if send:
                _send(email, subject, text_body, html_body)
                _record_sent(email, n)
                log.info("Sent digest to %s", email)
            else:
                log.info("DRY-RUN — subject: %s\n---\n%s\n---", subject, text_body[:600])
        except Exception:
            log.exception("Digest failed for %s", email)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="Actually send emails (default: dry-run)")
    parser.add_argument("--user", help="Restrict to a single email address (for testing)")
    args = parser.parse_args()
    run(send=args.send, only_user=args.user)


if __name__ == "__main__":
    main()
