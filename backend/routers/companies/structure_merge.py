"""Pure merge helpers for company administrator data.

These helpers intentionally avoid FastAPI/DB imports so we can unit-test
the "NBB filing snapshot + later Staatsblad updates" logic in isolation.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Any, Mapping


def normalize_admin_name(raw: str | None) -> str:
    """Normalise a person/entity name for cross-source matching."""
    if not raw:
        return ""
    value = unicodedata.normalize("NFKD", raw)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower()
    value = value.replace("\u2019", " ")
    value = re.sub(r"[.,()/'\"`]", " ", value)
    value = re.sub(
        r"\b(?:mr|mrs|mme|m|mister|madame|monsieur|dhr|mevr|mevrouw|de heer)\b",
        "",
        value,
    )
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _parse_iso_date(raw: Any) -> dt.date | None:
    """Best-effort ISO-like date parser.

    Handles ``YYYY-MM-DD`` and timestamps whose first 10 chars are an ISO
    date. Returns ``None`` for blanks / unparsable values.
    """
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if len(text) < 10:
        return None
    candidate = text[:10]
    try:
        return dt.date.fromisoformat(candidate)
    except ValueError:
        return None


def _seed_as_of(row: dict[str, Any]) -> str | None:
    deposit_date = row.get("deposit_date")
    parsed_deposit_date = _parse_iso_date(deposit_date)
    if parsed_deposit_date is not None:
        return parsed_deposit_date.isoformat()

    fiscal_year = row.get("fiscal_year")
    if fiscal_year in (None, ""):
        return None
    text = str(fiscal_year)
    if len(text) >= 4 and text[:4].isdigit():
        return f"{text[:4]}-12-31"
    return None


def _event_effective_date(event: dict[str, Any]) -> dt.date | None:
    """Use the actual event date when present, otherwise publication date."""
    return _parse_iso_date(event.get("event_date")) or _parse_iso_date(event.get("pub_date"))


def merge_admins_with_staatsblad(
    nbb_rows: list[dict[str, Any]],
    staatsblad_events: list[dict[str, Any]],
    *,
    role_labels: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge the latest NBB filing snapshot with later Staatsblad events.

    NBB is the baseline snapshot. Staatsblad should only *update* that
    snapshot with events that happened after the NBB filing's effective
    date. Replaying older Staatsblad history on top of a newer NBB board
    incorrectly removes still-current directors, which is the regression
    this helper guards against.
    """
    role_labels = role_labels or {}
    current: dict[str, dict[str, Any]] = {}
    nbb_snapshot_date: dt.date | None = None

    for row in nbb_rows:
        key = (normalize_admin_name(row.get("name") or ""), row.get("role") or "")
        current_key = "|".join(key)
        if not current_key.strip("|"):
            continue

        as_of = _seed_as_of(row)
        parsed_as_of = _parse_iso_date(as_of)
        if parsed_as_of and (nbb_snapshot_date is None or parsed_as_of > nbb_snapshot_date):
            nbb_snapshot_date = parsed_as_of

        current[current_key] = {
            **row,
            "role_label": role_labels.get(row.get("role") or "", row.get("role") or ""),
            "source": "nbb",
            "as_of": as_of,
        }

    ordered_events = sorted(
        staatsblad_events,
        key=lambda event: (
            str(event.get("pub_date") or ""),
            int(event.get("id") or 0),
        ),
    )

    for event in ordered_events:
        if event.get("event_type") != "admin_event":
            continue

        effective_date = _event_effective_date(event)
        if (
            nbb_snapshot_date is not None
            and effective_date is not None
            and effective_date <= nbb_snapshot_date
        ):
            # Older history is already reflected in the fresher NBB filing.
            continue

        sub_type = (event.get("sub_type") or "").lower()
        name = event.get("person_name") or event.get("entity_name") or ""
        role = event.get("person_role") or ""
        normalized_name = normalize_admin_name(name)
        if not normalized_name:
            continue

        current_key = "|".join((normalized_name, role))

        if sub_type in ("appointment", "reappointment", "renewal"):
            existing = current.get(current_key)
            if existing is None:
                current[current_key] = {
                    "name": name,
                    "role": role,
                    "role_label": role,
                    "person_type": "natural" if event.get("person_name") else "legal",
                    "identifier": None,
                    "mandate_start": str(event.get("event_date") or event.get("pub_date") or ""),
                    "mandate_end": None,
                    "representative_name": None,
                    "fiscal_year": None,
                    "deposit_key": f"sb_{event.get('pub_reference')}",
                    "source": "staatsblad",
                    "as_of": str(event.get("pub_date") or ""),
                    "pub_reference": event.get("pub_reference"),
                    "summary": event.get("summary"),
                }
            else:
                existing.update(
                    {
                        "mandate_start": str(
                            event.get("event_date")
                            or event.get("pub_date")
                            or existing.get("mandate_start")
                            or ""
                        ),
                        "mandate_end": None,
                        "deposit_key": f"sb_{event.get('pub_reference')}",
                        "source": "merged",
                        "as_of": str(event.get("pub_date") or ""),
                        "pub_reference": event.get("pub_reference"),
                        "summary": event.get("summary"),
                    }
                )
        elif sub_type in ("resignation", "end", "termination"):
            resigned = False
            for existing_key in list(current.keys()):
                existing_name = existing_key.split("|", 1)[0]
                if existing_name == normalized_name:
                    current[existing_key]["mandate_end"] = str(
                        event.get("event_date") or event.get("pub_date") or ""
                    )
                    current[existing_key]["as_of"] = str(event.get("pub_date") or "")
                    current[existing_key]["source"] = (
                        "merged"
                        if current[existing_key].get("source") == "nbb"
                        else "staatsblad"
                    )
                    resigned = True
            if not resigned:
                continue

    # Keep all admins — including those whose mandate has ended. The
    # /structure endpoint surfaces both Current and Past sections in the
    # admin sub-tab; filtering past admins here would hide directors of
    # companies that haven't yet filed a refresh (common for non-filing
    # subsidiaries — see 0878290854 FOREST AVENUE & C°). Callers that
    # specifically need a "currently active only" view (e.g. the spiderweb
    # via fetch_current_admins_for_batch) post-filter on mandate_end.
    current_state: list[dict[str, Any]] = list(current.values())
    current_state.sort(key=lambda row: (row.get("name") or "", row.get("role") or ""))

    timeline: list[dict[str, Any]] = []
    for event in reversed(ordered_events):
        if event.get("event_type") != "admin_event":
            continue
        timeline.append(
            {
                "pub_date": str(event.get("pub_date") or ""),
                "pub_reference": event.get("pub_reference"),
                "sub_type": event.get("sub_type"),
                "event_date": str(event.get("event_date") or "") if event.get("event_date") else None,
                "person_name": event.get("person_name"),
                "person_role": event.get("person_role"),
                "entity_name": event.get("entity_name"),
                "summary": event.get("summary"),
            }
        )

    return current_state, timeline
