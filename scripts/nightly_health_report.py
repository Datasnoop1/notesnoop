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
    """NBB nightly backload (02:00 cron).

    Productive work = loaded rows OR no-filings sentinels OR pdf-only marks.
    A run with high calls but zero productive work means something's broken.
    A run where the candidate pool is exhausted (low calls) is GREEN.
    """
    tail = _read_log("nightly.log", 80)
    m_rich = None     # new log line with no-filings counter
    m_legacy = None   # older log line without no-filings
    for line in reversed(tail.splitlines()):
        mr = re.search(
            r"Backload done in \d+s:\s+(\d+)\s+calls,\s+(\d+)\s+loaded,\s+(\d+)\s+rubrics,\s+(\d+)\s+pdf-only,\s+(\d+)\s+no-filings,\s+(\d+)\s+errors",
            line,
        )
        if mr:
            m_rich = mr
            break
        ml = re.search(
            r"Backload done in \d+s:\s+(\d+)\s+calls,\s+(\d+)\s+loaded,\s+(\d+)\s+rubrics",
            line,
        )
        if ml and not m_legacy:
            m_legacy = ml
    if not (m_rich or m_legacy):
        return CheckResult(
            name="NBB nightly backload",
            status="RED",
            summary="no completion line in nightly.log",
            detail=tail[-1500:] or "(no log found)",
        )
    if m_rich:
        calls, loaded, rubrics, pdf_only, no_fil, errs = (int(m_rich.group(i)) for i in range(1, 7))
        productive = loaded + no_fil + pdf_only
        if calls >= 100 and productive == 0:
            return CheckResult(
                name="NBB nightly backload",
                status="RED",
                summary=f"{calls:,} calls, 0 productive (no loads, no sentinels)",
                detail=tail[-2000:],
                claude_prompt=(
                    "The NBB nightly backload made API calls but neither loaded rows "
                    "nor wrote NO_FILINGS sentinels — indicates a code path where "
                    "every candidate's top ref exists in nbb_load_log already, or the "
                    "per-company API shape changed. Pick one candidate CBE and trace "
                    "the flow manually."
                ),
            )
        return CheckResult(
            name="NBB nightly backload",
            status="GREEN",
            summary=f"{calls:,} calls → {loaded:,} loaded, {rubrics:,} rubrics, "
                    f"{no_fil:,} no-filings, {pdf_only:,} pdf-only",
        )
    # legacy log line (pre-2026-04-20); kept so the morning after deploy still parses.
    calls, loaded, rubrics = int(m_legacy.group(1)), int(m_legacy.group(2)), int(m_legacy.group(3))
    if loaded == 0 and calls >= 50:
        return CheckResult(
            name="NBB nightly backload",
            status="RED",
            summary=f"{calls:,} calls, 0 loaded (legacy log format)",
            detail=tail[-2000:],
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


def check_kbo_daily() -> CheckResult:
    """KBO daily updater (06:00 cron, scripts/kbo_update.sh).

    Looks at two signals:
      1. The wrapper log (kbo_update.log) should contain a success marker
         line written within the last 25h. Either "KBO daily update complete"
         (full success including ANALYZE) or "No new updates available"
         (KBO portal genuinely had no new ZIPs — also a clean exit).
      2. The kbo_extract_log table's max applied_at should not be older
         than 35 days (KBO publishes monthly + interim weekday updates;
         a >35 day gap means we're missing the next monthly drop).

    Combining both lets us distinguish "wrapper running fine, KBO is just
    quiet" from "wrapper hasn't run in days" or "wrapper runs but never
    applies anything useful".
    """
    tail = _read_log("kbo_update.log", 200)
    lines = [ln for ln in tail.splitlines() if ln.strip()]

    # 1) Wrapper completion marker.
    success_pat = re.compile(
        r"KBO daily update complete|No new updates available", re.IGNORECASE
    )
    error_pat = re.compile(r"ERROR.*KBO daily update failed", re.IGNORECASE)
    last_success_ts = None
    last_error_line = None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=25)

    for ln in reversed(lines):
        if last_success_ts is None and success_pat.search(ln):
            mts = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", ln)
            if mts:
                try:
                    last_success_ts = datetime.fromisoformat(
                        mts.group(1).replace("Z", "+00:00")
                    )
                except ValueError:
                    pass
        if last_error_line is None and error_pat.search(ln):
            last_error_line = ln
        if last_success_ts and last_error_line:
            break

    wrapper_ok = last_success_ts is not None and last_success_ts >= cutoff

    # 2) Database staleness: how old is the latest applied KBO extract?
    # `applied_at` is stored as TEXT (not TIMESTAMP) — parse defensively.
    extract_age_days = None
    try:
        row = fetch_one(
            "SELECT MAX(applied_at) AS last_applied FROM kbo_extract_log"
        )
        last_applied_raw = row["last_applied"] if row else None
        if last_applied_raw:
            last_applied = None
            if isinstance(last_applied_raw, datetime):
                last_applied = last_applied_raw
            else:
                # Common KBO formats: "YYYY-MM-DD HH:MM:SS" and ISO 8601.
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        last_applied = datetime.strptime(str(last_applied_raw), fmt)
                        break
                    except ValueError:
                        continue
                if last_applied is None:
                    try:
                        last_applied = datetime.fromisoformat(
                            str(last_applied_raw).replace("Z", "+00:00")
                        )
                    except ValueError:
                        log.warning(
                            "could not parse kbo_extract_log.applied_at=%r",
                            last_applied_raw,
                        )
            if last_applied is not None:
                if last_applied.tzinfo is None:
                    last_applied = last_applied.replace(tzinfo=timezone.utc)
                extract_age_days = (
                    datetime.now(timezone.utc) - last_applied
                ).total_seconds() / 86400
    except Exception as e:
        log.warning("kbo_extract_log query failed: %s", e)

    # Decision
    if wrapper_ok and (extract_age_days is None or extract_age_days < 35):
        bits = []
        if last_success_ts:
            bits.append(f"wrapper OK at {last_success_ts.strftime('%H:%MZ')}")
        if extract_age_days is not None:
            bits.append(f"latest extract {extract_age_days:.0f}d old")
        return CheckResult(
            name="KBO daily updater",
            status="GREEN",
            summary=" / ".join(bits) or "wrapper success marker present",
        )

    # RED — figure out which signal failed.
    failure_summaries = []
    if not wrapper_ok:
        if last_error_line:
            failure_summaries.append(
                f"wrapper failing — last error: {last_error_line[-100:]}"
            )
        elif last_success_ts:
            age_h = (datetime.now(timezone.utc) - last_success_ts).total_seconds() / 3600
            failure_summaries.append(
                f"wrapper success marker is {age_h:.0f}h old (need <25h)"
            )
        else:
            failure_summaries.append("no wrapper success marker found in log")
    if extract_age_days is not None and extract_age_days >= 35:
        failure_summaries.append(
            f"kbo_extract_log latest applied is {extract_age_days:.0f}d old"
        )
    return CheckResult(
        name="KBO daily updater",
        status="RED",
        summary="; ".join(failure_summaries) or "unknown failure",
        detail=tail[-2000:],
        claude_prompt=(
            "KBO daily updater is failing or stale. Check "
            "/opt/leadpeek/scripts/_watchdog_state/kbo_update.log for the "
            "most recent run, then run `bash /opt/leadpeek/scripts/kbo_update.sh` "
            "manually to reproduce. Common cause: wrapper points at the wrong "
            "Python path inside the backend container — the script lives at "
            "/app/kbo_daily_update.py, not /app/backend/..."
        ),
    )


# Patterns that indicate a cron run failed or partially failed. Looked up
# in any *.log file under _watchdog_state/ that was modified in the last
# 25h, so a wrapper exiting non-zero will be caught even if no per-cron
# check function exists yet. Chosen to be specific enough to avoid
# matching transient warnings: each pattern needs context that suggests a
# whole-process-failure rather than a recoverable per-record issue.
_CRON_FAILURE_PATTERNS = [
    re.compile(r"ERROR.*failed with exit\s+\d+", re.IGNORECASE),
    re.compile(r"failed with exit code\s+\d+", re.IGNORECASE),
    re.compile(r"can't open file '.+': \[Errno 2\]"),
    re.compile(r"ModuleNotFoundError|ImportError"),
    re.compile(r"Traceback \(most recent call last\):"),
]

# Logs the watchdog produces but which already have dedicated check
# functions above. Skip them here to avoid double-reporting.
_CRON_LOG_SKIP = {
    "watchdog.log",          # check_nbb_watchdog
    "nightly.log",           # check_nbb_backload
    "staatsblad_events.log", # check_staatsblad_events
    "kbo_update.log",        # check_kbo_daily
    "regsol.log",            # intentionally not monitored — Zenrows retired
    "health_report.log",     # this script's own log; self-reference noise
    "ted.log",               # check_log_has_recent_success below
    "invoices.log",          # check_log_has_recent_success below
    "valuation_commentary.log",  # check_log_has_recent_success below
    "cron.log",              # NBB watchdog dispatcher; same data as watchdog.log
}


def check_cron_log_failures() -> CheckResult:
    """Catch-all: scan every *.log under _watchdog_state/ that's been written
    in the last 25h and look for failure markers. This is the safety net for
    any cron we haven't written a dedicated check for — and the early-warning
    line for new crons added in the future. Logs that already have a
    dedicated check are skipped to avoid duplicate alerts.
    """
    cutoff_ts = datetime.now().timestamp() - 25 * 3600
    findings: list[str] = []
    scanned = 0
    for d in _LOG_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.log")):
            if p.name in _CRON_LOG_SKIP:
                continue
            try:
                if p.stat().st_mtime < cutoff_ts:
                    continue
            except OSError:
                continue
            scanned += 1
            try:
                with p.open("r", errors="replace") as f:
                    # Read at most the last 500 lines per file — enough for
                    # daily crons, cheap on huge logs.
                    lines = f.readlines()[-500:]
            except Exception as e:
                findings.append(f"{p.name}: read failed ({e})")
                continue
            for ln in lines:
                if any(pat.search(ln) for pat in _CRON_FAILURE_PATTERNS):
                    snippet = ln.rstrip()[:160]
                    findings.append(f"{p.name}: {snippet}")
                    break  # one finding per log is enough for the digest
        # Once we've scanned a directory that exists, don't double-scan its
        # symlinked twin (the two _LOG_DIRS often resolve to the same place).
        break

    if not findings:
        return CheckResult(
            name="Cron log scan",
            status="GREEN",
            summary=f"{scanned} active log(s), no failure markers",
        )
    return CheckResult(
        name="Cron log scan",
        status="RED",
        summary=f"{len(findings)} cron log(s) showing failure markers",
        detail="\n".join(findings),
        claude_prompt=(
            "One or more cron logs under /opt/leadpeek/scripts/_watchdog_state/ "
            "contain failure markers from the last 24h. Inspect each named "
            "log, identify the failing job, and fix or silence accordingly. "
            "If a cron has been intentionally retired, add its log filename "
            "to _CRON_LOG_SKIP in scripts/nightly_health_report.py."
        ),
    )


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
    Postgres and reading watchdog log tails. The catch-all `check_cron_log_failures`
    scans every other *.log under _watchdog_state/ for failure markers, so
    new crons get baseline monitoring even before a dedicated check is written.

    Note: check_regsol was retired 2026-05-03 — Zenrows is not coming back,
    so the cron is silenced and we don't want false alarms. Re-add when a
    replacement scraper ships.
    """
    checks: list[Callable[[], CheckResult]] = [
        check_nbb_watchdog,
        check_nbb_daily,
        check_nbb_backload,
        check_kbo_daily,
        check_staatsblad_events,
        check_cron_log_failures,
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
