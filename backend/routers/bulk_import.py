"""Bulk import router — paste-a-list-of-company-names workflow.

Flow:
1. User pastes a list of names (one per line) or uploads a CSV.
2. POST /api/import/match runs a pg_trgm fuzzy match on the `company_info`
   `name_normalized` column and returns the single best candidate per
   input with a 0–100 score.
3. User selects which matches to accept (pre-checked if score >= 80).
4. POST /api/import/confirm bulk-upserts those CBEs into the user's
   favourites, skipping duplicates.

pg_trgm is already enabled and `company_info.name_normalized` is
already maintained by the existing search code path, so no new DB
dependency is required.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute, normalize_name
from auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/import", tags=["import"])

# Cap the per-request payload so an accidental 100k-line paste doesn't
# turn into 100k trigram queries. 500 is roughly the size of a reasonable
# deal-pipeline import; anything bigger wants an admin-side batch job.
MAX_NAMES_PER_CALL = 500
MAX_NAME_LENGTH = 200


class ImportMatchBody(BaseModel):
    names: List[str]


class ImportMatchRow(BaseModel):
    input_name: str
    best_match_name: str | None
    enterprise_number: str | None
    city: str | None
    score: int   # 0–100


class ImportConfirmBody(BaseModel):
    enterprise_numbers: List[str]


def _normalize_cbe(raw: str) -> str:
    """Strip dots/spaces, left-pad to 10 digits. Returns '' on garbage input."""
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if not digits:
        return ""
    return digits.zfill(10)[:10]


def _match_one(name: str) -> dict:
    """Run pg_trgm on a single input name, return the top candidate or a miss row.

    Uses the GIN-indexed `name_normalized` column via the `%` operator so
    the planner can prune without scanning the 1.9M-row table.
    """
    normalized = normalize_name(name)
    if not normalized:
        return {
            "input_name": name,
            "best_match_name": None,
            "enterprise_number": None,
            "city": None,
            "score": 0,
        }

    rows = fetch_all(
        """
        SELECT ci.enterprise_number, ci.name, ci.city,
               similarity(ci.name_normalized, %s) AS sim
        FROM company_info ci
        WHERE ci.name_normalized IS NOT NULL
          AND ci.name_normalized %% %s
        ORDER BY ci.name_normalized <-> %s
        LIMIT 1
        """,
        (normalized, normalized, normalized),
    )
    if not rows:
        return {
            "input_name": name,
            "best_match_name": None,
            "enterprise_number": None,
            "city": None,
            "score": 0,
        }
    r = rows[0]
    sim = r.get("sim") or 0.0
    return {
        "input_name": name,
        "best_match_name": r.get("name"),
        "enterprise_number": r.get("enterprise_number"),
        "city": r.get("city"),
        "score": int(round(float(sim) * 100)),
    }


@router.post("/match")
async def import_match(body: ImportMatchBody, user=Depends(get_current_user)):
    """Fuzzy-match a list of company names to their best CBE candidate.

    Returns one row per input — with `enterprise_number` null if nothing
    crossed the pg_trgm default threshold (0.3 by default, tuned by the
    `%` operator). Score is the similarity value * 100, rounded to int.
    """
    cleaned: list[str] = []
    for raw in (body.names or []):
        s = (raw or "").strip()
        if not s:
            continue
        if len(s) > MAX_NAME_LENGTH:
            s = s[:MAX_NAME_LENGTH]
        cleaned.append(s)
        if len(cleaned) >= MAX_NAMES_PER_CALL:
            break

    if not cleaned:
        return {"results": [], "input_count": 0, "matched_count": 0}

    try:
        results = [_match_one(n) for n in cleaned]
    except Exception:
        logger.exception("Bulk import match failed")
        raise HTTPException(status_code=500, detail="Match failed")

    matched = sum(1 for r in results if r["enterprise_number"])
    return {
        "results": results,
        "input_count": len(cleaned),
        "matched_count": matched,
    }


@router.post("/confirm", status_code=201)
async def import_confirm(body: ImportConfirmBody, user=Depends(get_current_user)):
    """Bulk-upsert confirmed CBE numbers into the user's favourites.

    Idempotent — duplicates are silently skipped. Returns a count of
    newly-added rows plus the list of CBEs that weren't found in the
    `enterprise` table (so the frontend can flag typos).
    """
    raw_list = body.enterprise_numbers or []
    if not raw_list:
        return {"added": 0, "skipped": 0, "not_found": []}

    # Normalize + dedupe while preserving order
    seen: set[str] = set()
    cbes: list[str] = []
    for raw in raw_list:
        n = _normalize_cbe(str(raw))
        if n and n not in seen:
            seen.add(n)
            cbes.append(n)
        if len(cbes) >= MAX_NAMES_PER_CALL:
            break

    if not cbes:
        return {"added": 0, "skipped": 0, "not_found": []}

    try:
        # Filter to CBEs that actually exist in the enterprise table
        placeholders = ",".join(["%s"] * len(cbes))
        found_rows = fetch_all(
            f"SELECT enterprise_number FROM enterprise WHERE enterprise_number IN ({placeholders})",
            tuple(cbes),
        )
        found = {r["enterprise_number"] for r in found_rows}
        not_found = [c for c in cbes if c not in found]

        added = 0
        skipped = 0
        for cbe in cbes:
            if cbe not in found:
                continue
            existing = fetch_one(
                "SELECT 1 FROM favourite WHERE user_id = %s AND enterprise_number = %s",
                (user["id"], cbe),
            )
            if existing:
                skipped += 1
                continue
            execute(
                """INSERT INTO favourite (user_id, enterprise_number)
                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                (user["id"], cbe),
            )
            added += 1
    except Exception:
        logger.exception("Bulk import confirm failed")
        raise HTTPException(status_code=500, detail="Confirm failed")

    return {
        "added": added,
        "skipped": skipped,
        "not_found": not_found,
    }
