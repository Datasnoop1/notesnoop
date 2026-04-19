"""Nightly health report — checks each automated process and emails a digest.

Runs via cron at 06:00 UTC (see scripts/install_crons.sh). For each job we
operate in production, asks one question: did it produce measurable output
in the last 24h? If no → RED; if yes → GREEN.

Philosophy: the NBB key watchdog only checks whether auth works, not whether
the pipeline actually ingests rows. Today's bug (2026-04-10 → 2026-04-19,
zero filings loaded for 9 nights while the watchdog reported GREEN) is why
this exists. Detection is by *outcome*, not by *liveness*.

The email includes per-RED diagnostic blobs and a copy-paste-ready prompt
the operator can hand to Claude for follow-up. That's tier-3-lite; a
fully autonomous remediation tier (scheduled remote Claude Code agent) can
be layered on later.

Required env (read from the backend container's environment):
  DATABASE_URL          (for DB queries)
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
  SMTP_ALERT_TO         (recipient for the digest)

Usage:
  python scripts/nightly_health_report.py          # dry-run, prints to stdout
  python scripts/nightly_health_report.py --send   # send the email
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import smtplib
import ssl
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Callable

# Make backend/db importable (same pattern as other scripts).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import fetch_one, fetch_all  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("health_report")


# ---------------------------------------------------------------------------
# Where logs live on the Hetzner host. The cron-mounted path is
# /opt/leadpeek/scripts/_watchdog_state/, but the backend container sees that
# as /app/scripts/_watchdog_state/ via the docker-compose mount. We try both.
# ---------------------------------------------------------------------------
_LOG_DIRS = [
    Path("/app/scripts/_watchdog_state"),
    Path("/opt/leadpeek/scripts/_watchdog_state"),
]


def _read_log(name: str, max_lines: int = 500) -> str:
    """Return the last ``max_lines`` lines of one of the watchdog logs."""
    for d in _LOG_DIRS:
        p = d / name
        if p.exists():
            try:
                with p.open("r", errors="replace") as f:
                    lines = f.readlines()
                return "".join(lines[-max_lines:])
            except Exception as e:
                log.warning("read %s failed: %s", p, e)
    # /var/log/nbb_batch.log is outside the watchdog dir (pre-existing cron).
    fallback = Path("/var/log") / name
    if fallback.exists():
        try:
            with fallback.open("r", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-max_lines:])
        except Exception:
            pass
    return ""


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    name: str
    status: str  # "GREEN" | "RED" | "SKIP"
    summary: str  # one-line for the digest
    detail: str = ""  # multi-line for the red-section debug block
    claude_prompt: str = ""  # pre-written prompt for the operator to hand to Claude


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def check_nbb_daily() -> CheckResult:
    """NBB daily batch pipeline (01:00 cron): yesterday's extract should have produced rows.

    We read the `meta.nbb_batch_{yesterday}` marker and the row count in
    financial_data. A silent-skip regression (today's bug) would present as
    `meta = "N filings, 0 rubrics"` or `0 filings` — both RED.
    """
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    row = fetch_one(
        "SELECT value FROM meta WHERE variable = %s",
        (f"nbb_batch_{yesterday}",),
    )
    if not row:
        return CheckResult(
            name="NBB daily pipeline",
            status="RED",
            summary=f"no meta row for {yesterday} — cron may not have run",
            detail=(
                "Log file /var/log/nbb_batch.log lives on the host and is not "
                "visible to this container — ssh in to inspect it directly."
            ),
            claude_prompt=(
                f"The NBB daily pipeline has no completion marker for {yesterday}. "
                "SSH to the Hetzner host and tail /var/log/nbb_batch.log, confirm the "
                "01:00 cron fired, and investigate any error. If NBB_EXTRACT_KEY was "
                "rotated, the watchdog should handle it — verify the rotation log too."
            ),
        )
    value = row["value"]
    m = re.match(r"(\d+)\s+filings,\s+(\d+)\s+rubrics", value)
    if not m:
        return CheckResult(
            name="NBB daily pipeline",
            status="RED",
            summary=f"unparseable meta value for {yesterday}: {value!r}",
            detail=value,
        )
    filings, rubrics = int(m.group(1)), int(m.group(2))
    if filings == 0 or rubrics == 0:
        return CheckResult(
            name="NBB daily pipeline",
            status="RED",
            summary=f"{filings} filings loaded / {rubrics} rubrics for {yesterday}",
            detail=(
                "Host log at /var/log/nbb_batch.log is not visible to this container. "
                "SSH in to see the per-filing skip/error counts."
            ),
            claude_prompt=(
                f"The NBB daily pipeline ran for {yesterday} but loaded 0 rows. "
                "Fetch one filing from the ZIP at "
                f"https://ws.cbso.nbb.be/extracts/batch/{yesterday}/accountingData "
                "and inspect its JSON shape against backend/nbb_batch_pipeline.py's "
                "parse_filing(). If NBB changed the schema again, patch the parser and "
                "re-run the backfill. See the 2026-04-19 incident for the pattern."
            ),
        )
    return CheckResult(
        name="NBB daily pipeline",
        status="GREEN",
        summary=f"{filings:,} filings, {rubrics:,} rubrics for {yesterday}",
    )


def check_nbb_backload() -> CheckResult:
    """NBB nightly backload (02:00 cron): should load >0 rows on most nights."""
    tail = _read_log("nightly.log", 60)
    # Look for the most recent "Backload done ... N loaded ... N rubrics"
    m = None
    for line in reversed(tail.splitlines()):
        m2 = re.search(
            r"Backload done in \d+s:\s+(\d+)\s+calls,\s+(\d+)\s+loaded,\s+(\d+)\s+rubrics",
            line,
        )
        if m2:
            m = m2
            break
    if not m:
        return CheckResult(
            name="NBB nightly backload",
            status="RED",
            summary="no completion line in nightly.log",
            detail=tail[-1500:] or "(no log found)",
        )
    calls, loaded, rubrics = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if loaded == 0 and calls >= 50:
        return CheckResult(
            name="NBB nightly backload",
            status="RED",
            summary=f"{calls:,} calls, 0 loaded — burning budget for nothing",
            detail=tail[-2000:],
            claude_prompt=(
                "The NBB nightly backload spent its call budget but loaded zero rows. "
                "Either the per-company API shape changed (check "
                "scripts/nbb_nightly_backload.py store_filing) or every candidate "
                "already has complete coverage. Pick one candidate CBE and trace the "
                "flow manually against https://ws.cbso.nbb.be/authentic/legalEntity/{cbe}/references."
            ),
        )
    return CheckResult(
        name="NBB nightly backload",
        status="GREEN",
        summary=f"{calls:,} calls, {loaded:,} loaded, {rubrics:,} rubrics",
    )


def check_nbb_watchdog() -> CheckResult:
    """NBB key watchdog (*/15 cron): >95% GREEN probes in the last 24h."""
    tail = _read_log("watchdog.log", 200)
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    last96 = lines[-96:]
    if not last96:
        return CheckResult(
            name="NBB key watchdog",
            status="RED",
            summary="no watchdog probes logged",
            detail=tail[-1000:],
        )
    green = sum(1 for ln in last96 if "GREEN" in ln)
    total = len(last96)
    pct = (green / total) * 100 if total else 0
    if pct < 90:
        return CheckResult(
            name="NBB key watchdog",
            status="RED",
            summary=f"{green}/{total} GREEN ({pct:.0f}%) — auth instability",
            detail="\n".join(last96[-20:]),
            claude_prompt=(
                "NBB key watchdog is below 90% green. Check scripts/nbb_watchdog.sh "
                "log, confirm auto-rotation is working, and verify both prod + staging "
                "containers were force-recreated after the last rotation."
            ),
        )
    return CheckResult(
        name="NBB key watchdog",
        status="GREEN",
        summary=f"{green}/{total} probes GREEN ({pct:.0f}%)",
    )


def check_staatsblad_events() -> CheckResult:
    """Staatsblad batch classifier (every 2 days) + nightly embed job.

    Log file is shared between staatsblad_batch_every_2d.py (runs every 2 days
    at 04:00) and staatsblad_embed.py (runs daily at 05:45). Both write to
    staatsblad_events.log. We're green if either emitted a completion line
    in the past 48h (batch cadence) plus the log mtime is within 26h (daily
    embed should run every night).
    """
    import os as _os

    tail = _read_log("staatsblad_events.log", 120)

    # Completion format depends on which cron is actually installed:
    #   - open_data_staatsblad_events.py (legacy classifier, daily)
    #       "staatsblad events done: N inserted"
    #   - staatsblad_batch_every_2d.py (newer, every 2 days)
    #       "Batch cycle complete.  filings=N  events=M"
    #   - staatsblad_embed.py (daily embedder)
    #       "Embedded N events."
    m_classify = None
    m_batch = None
    m_embed = None
    for line in reversed(tail.splitlines()):
        if m_classify is None:
            mc = re.search(r"staatsblad events done:\s+(\d+)\s+inserted", line)
            if mc:
                m_classify = mc
        if m_batch is None:
            mb = re.search(r"Batch cycle complete\.\s+filings=(\d+)\s+events=(\d+)", line)
            if mb:
                m_batch = mb
        if m_embed is None:
            me = re.search(r"Embedded (\d+) events", line)
            if me:
                m_embed = me
        if m_classify and m_batch and m_embed:
            break

    # Freshness: the daily embed should touch the log inside 26h.
    stale = False
    mtime_age_h = None
    for d in _LOG_DIRS:
        p = d / "staatsblad_events.log"
        if p.exists():
            try:
                mtime_age_h = (datetime.now().timestamp() - p.stat().st_mtime) / 3600
                stale = mtime_age_h > 26
            except Exception:
                pass
            break

    if m_classify or m_batch or m_embed:
        bits = []
        if m_classify:
            bits.append(f"classify: {m_classify.group(1)} inserted")
        if m_batch:
            bits.append(f"batch: filings={m_batch.group(1)} events={m_batch.group(2)}")
        if m_embed:
            bits.append(f"embed: {m_embed.group(1)} events")
        if mtime_age_h is not None:
            bits.append(f"last-write {mtime_age_h:.1f}h ago")
        status = "RED" if stale else "GREEN"
        return CheckResult(
            name="Staatsblad classify + embed",
            status=status,
            summary="; ".join(bits),
            detail=tail[-1500:] if status == "RED" else "",
            claude_prompt=(
                "Staatsblad job log is stale (>26h). The daily classify/embed cron "
                "should have touched it. Check scripts/_watchdog_state/staatsblad_events.log "
                "and verify the cron entries."
            ) if status == "RED" else "",
        )
    return CheckResult(
        name="Staatsblad classify + embed",
        status="RED",
        summary="no completion line from any staatsblad job",
        detail=tail[-1200:] or "(log empty or missing)",
    )


def check_regsol() -> CheckResult:
    """Regsol insolvency scraper (03:30)."""
    tail = _read_log("regsol.log", 60)
    if "ZENROWS_API_KEY not set" in tail:
        return CheckResult(
            name="Regsol scraper",
            status="RED",
            summary="ZENROWS_API_KEY missing — no scrapes happening",
            detail=tail[-800:],
            claude_prompt=(
                "Regsol scrape is failing because ZENROWS_API_KEY is not set on the "
                "Hetzner host. The operator needs to put the key in /opt/leadpeek/.env "
                "and .env.production, then force-recreate the backend container."
            ),
        )
    if not tail.strip():
        return CheckResult(
            name="Regsol scraper",
            status="RED",
            summary="regsol.log empty — cron may not have fired",
            detail="",
        )
    # Green if most recent line doesn't contain ERROR/FAIL
    last = tail.splitlines()[-1] if tail.splitlines() else ""
    if "ERROR" in last.upper() or "FAIL" in last.upper():
        return CheckResult(
            name="Regsol scraper",
            status="RED",
            summary="error on last run",
            detail=tail[-1500:],
        )
    return CheckResult(name="Regsol scraper", status="GREEN", summary="last run clean")


def check_log_has_recent_success(
    name: str, log_filename: str, success_regex: str, red_prompt: str = ""
) -> CheckResult:
    """Generic: the log's most recent line should match `success_regex`."""
    tail = _read_log(log_filename, 40)
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    if not lines:
        return CheckResult(
            name=name,
            status="RED",
            summary=f"{log_filename} empty or missing",
            claude_prompt=red_prompt,
        )
    last = lines[-1]
    if re.search(success_regex, last, re.IGNORECASE):
        return CheckResult(name=name, status="GREEN", summary=last[-120:])
    if re.search(r"ERROR|FAIL|EXCEPTION", last, re.IGNORECASE):
        return CheckResult(
            name=name,
            status="RED",
            summary=last[-120:],
            detail="\n".join(lines[-15:]),
            claude_prompt=red_prompt,
        )
    return CheckResult(
        name=name,
        status="GREEN",
        summary=last[-120:],
    )


# ---------------------------------------------------------------------------
# Orchestration + email
# ---------------------------------------------------------------------------
def _run_all_checks() -> list[CheckResult]:
    """Each check returns in a second or two — no external I/O beyond the local
    Postgres and reading watchdog log tails. KBO daily/full are not yet
    covered here; they log to /var/log/{kbo_update,datapeak_daily}.log on
    the host which isn't mounted into this container. Add a host volume for
    those logs later to extend the report.
    """
    checks: list[Callable[[], CheckResult]] = [
        check_nbb_watchdog,
        check_nbb_daily,
        check_nbb_backload,
        check_staatsblad_events,
        check_regsol,
        lambda: check_log_has_recent_success(
            "TED procurement",
            "ted.log",
            r"done|awards|loaded",
            red_prompt="TED procurement job failed — check /app/scripts/_watchdog_state/ted.log.",
        ),
        lambda: check_log_has_recent_success(
            "Invoice ingest",
            "invoices.log",
            r"done|processed|invoices|no new",
            red_prompt="Invoice ingest errored — check the IMAP creds and log.",
        ),
        lambda: check_log_has_recent_success(
            "Valuation commentary",
            "valuation_commentary.log",
            r"done|generated|complete",
            red_prompt="Valuation commentary job failed — check OpenRouter quota / key.",
        ),
    ]
    results = []
    for c in checks:
        try:
            results.append(c())
        except Exception as e:
            results.append(
                CheckResult(
                    name=getattr(c, "__name__", "unknown"),
                    status="RED",
                    summary=f"check raised {type(e).__name__}: {e}",
                )
            )
    return results


def _format_digest(results: list[CheckResult]) -> tuple[str, str]:
    """Return (subject, plain_text_body)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reds = [r for r in results if r.status == "RED"]
    subj = (
        f"[DataSnoop] Nightly health — {len(reds)} red / {len(results)} jobs"
        if reds else f"[DataSnoop] Nightly health — all green ({len(results)} jobs)"
    )

    lines = [
        f"DataSnoop nightly health — {now}",
        "=" * 60,
        "",
    ]
    tick = {"GREEN": "[OK]  ", "RED": "[!!]  ", "SKIP": "[--]  "}
    for r in results:
        lines.append(f"{tick.get(r.status, '[??]  ')}{r.name:<25s} {r.summary}")

    if reds:
        lines += ["", "-" * 60, "Red-item detail + Claude-ready prompts", "-" * 60, ""]
        for r in reds:
            lines += [f"### {r.name}", f"  {r.summary}"]
            if r.detail:
                lines += ["", "  Last relevant log:", ""]
                for ln in r.detail.rstrip().splitlines():
                    lines.append(f"    {ln}")
            if r.claude_prompt:
                lines += ["", "  To investigate, paste into Claude Code:", ""]
                lines.append(f"    {r.claude_prompt}")
            lines.append("")
    else:
        lines += ["", "All monitored jobs produced output in the last 24h."]

    lines += [
        "",
        "-" * 60,
        "Generated by scripts/nightly_health_report.py. Edit the check "
        "list there to add or remove monitored jobs.",
    ]
    return subj, "\n".join(lines)


def _send_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_PASS")
    sender = os.getenv("SMTP_FROM", "claude@datasnoop.be")
    to = os.getenv("SMTP_ALERT_TO") or sender
    if not (host and user and pwd and to):
        raise RuntimeError("SMTP_HOST / SMTP_USER / SMTP_PASS / SMTP_ALERT_TO must be set.")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"DataSnoop Watchdog <{sender}>"
    msg["To"] = to
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.ehlo("datasnoop-backend")
        s.starttls(context=ctx)
        s.ehlo("datasnoop-backend")
        s.login(user, pwd)
        s.sendmail(sender, [to], msg.as_string())
    log.info("digest sent to %s", to)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Actually send the email.")
    parser.add_argument("--json", action="store_true", help="Also print JSON status.")
    args = parser.parse_args()

    results = _run_all_checks()
    subject, body = _format_digest(results)

    print(body)
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps([r.__dict__ for r in results], indent=2))

    if args.send:
        try:
            _send_email(subject, body)
        except Exception as e:
            log.error("send failed: %s — digest already printed to stdout above", e)
            # Don't mask the digest's own RED/GREEN exit code with SMTP noise.
    else:
        log.info("dry-run — not sending. Pass --send to email.")

    reds = sum(1 for r in results if r.status == "RED")
    return 1 if reds else 0


if __name__ == "__main__":
    sys.exit(main())
