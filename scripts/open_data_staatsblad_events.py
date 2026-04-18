"""Structure staatsblad_publication rows into staatsblad_event entries.

For each staatsblad_publication not yet in staatsblad_event, classify the
pub_type into an event_type (director_appointed, director_resigned,
capital_increase, name_change, legal_form_change, liquidation, merger,
other) and extract the subject_name where possible.

This is a cheap local-only transform — no network calls, just regex
classification. Feeds:
  - "What changed since last visit" banner (broader coverage)
  - Summary-tab corporate events timeline (structured display)
  - Screener "recent governance events" filter (future)

Running nightly:
    0 4 * * * cd /opt/leadpeek && docker exec leadpeek-backend-1 \
        python /app/../scripts/open_data_staatsblad_events.py \
        >> scripts/_watchdog_state/staatsblad_events.log 2>&1
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import execute, fetch_all  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("staatsblad_events")


# Classification — order matters: first match wins.
CLASSIFY = [
    ("director_appointed", re.compile(r"benoeming|nomination|aanstelling|appointment", re.I)),
    ("director_resigned", re.compile(r"ontslag|démission|resignation|einde mandaat", re.I)),
    ("capital_increase", re.compile(r"kapitaalverhoging|augmentation.*capital|capital increase", re.I)),
    ("capital_decrease", re.compile(r"kapitaalvermindering|réduction.*capital|capital decrease", re.I)),
    ("legal_form_change", re.compile(r"omzetting|transformation|legal form change", re.I)),
    ("name_change", re.compile(r"naamswijziging|changement.*dénomination|name change", re.I)),
    ("liquidation", re.compile(r"vereffening|liquidation|dissolution", re.I)),
    ("merger", re.compile(r"fusie|fusion|merger|splitsing|scission", re.I)),
    ("bankruptcy", re.compile(r"faillissement|faillite|bankruptcy", re.I)),
    ("reorganisation", re.compile(r"gerechtelijke reorganisatie|réorganisation judiciaire", re.I)),
]


def classify(pub_type: str) -> str:
    if not pub_type:
        return "other"
    for event_type, rx in CLASSIFY:
        if rx.search(pub_type):
            return event_type
    return "other"


def extract_subject(pub_type: str) -> Optional[str]:
    """Best-effort name extraction. 'BENOEMING VAN X Y' → 'X Y'."""
    if not pub_type:
        return None
    m = re.search(r"(?:benoeming|ontslag|nomination|démission)\s+(?:van|de|d[e'’]|of)\s+([A-Za-zÀ-ÖØ-öø-ÿ'.\-\s]{3,80})", pub_type, re.I)
    if m:
        return m.group(1).strip()
    return None


def run(limit: int = 10000) -> None:
    # Rows in staatsblad_publication that don't have a matching event row yet.
    rows = fetch_all(
        """
        SELECT sp.enterprise_number, sp.reference, sp.pub_date, sp.pub_type, sp.entity_name
        FROM staatsblad_publication sp
        WHERE sp.reference != 'NO_DATA'
          AND NOT EXISTS (
            SELECT 1 FROM staatsblad_event se
            WHERE se.enterprise_number = sp.enterprise_number
              AND se.reference = sp.reference
          )
        ORDER BY sp.pub_date DESC
        LIMIT %s
        """,
        (limit,),
    )
    log.info("classifying %d un-structured staatsblad rows", len(rows))
    by_type: dict[str, int] = {}
    inserted = 0
    for r in rows:
        pub_type = r.get("pub_type") or ""
        event_type = classify(pub_type)
        subject = extract_subject(pub_type) or r.get("entity_name")
        pub_date = r.get("pub_date")
        try:
            execute(
                """
                INSERT INTO staatsblad_event
                    (enterprise_number, reference, pub_date, event_type,
                     subject_name, raw_title)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    r["enterprise_number"],
                    r["reference"],
                    pub_date,
                    event_type,
                    subject,
                    pub_type,
                ),
            )
            inserted += 1
            by_type[event_type] = by_type.get(event_type, 0) + 1
        except Exception as e:
            log.debug("skip %s (%s): %s", r.get("reference"), pub_type[:40], e)

    log.info("staatsblad events done: %d inserted", inserted)
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        log.info("  %-25s %d", t, n)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10000)
    args = ap.parse_args()
    run(args.limit)
