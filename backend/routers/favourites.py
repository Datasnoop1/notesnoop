"""Favourites router — per-user company tracking + projects (grouping) + customers/suppliers."""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute
from auth import get_current_user, optional_user
from ai_client import ai_complete

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/favourites", tags=["favourites"])


# ── Models ─────────────────────────────────────────────────────

class FavouriteCreate(BaseModel):
    enterprise_number: str
    notes: Optional[str] = None


class ProjectCreate(BaseModel):
    name: str


class ProjectMemberAdd(BaseModel):
    enterprise_number: str


def _serialize_row(row: dict) -> dict:
    import decimal
    import datetime
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime.date, datetime.datetime)):
            out[k] = str(v)
        else:
            out[k] = v
    return out


@router.get("")
async def list_favourites(user=Depends(get_current_user)):
    """List favourites for the logged-in user."""
    try:
        rows = fetch_all("""
            SELECT f.enterprise_number, f.added_at, f.notes,
                   COALESCE(ci.name, d.denomination) AS "name",
                   ci.city, ci.nace_code,
                   fl.revenue, fl.ebitda, fl.fte_total,
                   CASE WHEN fl.revenue > 0
                        THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
                   END AS "margin"
            FROM favourite f
            LEFT JOIN company_info ci ON ci.enterprise_number = f.enterprise_number
            LEFT JOIN denomination d ON d.entity_number = f.enterprise_number
                 AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN financial_latest fl ON fl.enterprise_number = f.enterprise_number
            WHERE f.user_id = %s
            ORDER BY f.added_at DESC
        """, (user["id"],))
        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.exception("List favourites failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("", status_code=201)
async def add_favourite(body: FavouriteCreate, user=Depends(get_current_user)):
    """Add a company to the user's favourites."""
    cbe = str(body.enterprise_number).replace(".", "").zfill(10)
    try:
        execute(
            """INSERT INTO favourite (user_id, enterprise_number, notes)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
            (user["id"], cbe, body.notes),
        )
        return {"enterprise_number": cbe, "status": "added"}
    except Exception as e:
        logger.exception("Add favourite failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{cbe}")
async def remove_favourite(cbe: str, user=Depends(get_current_user)):
    """Remove a company from the user's favourites."""
    cbe = cbe.strip().replace(".", "").zfill(10)
    try:
        existing = fetch_one(
            "SELECT 1 FROM favourite WHERE user_id = %s AND enterprise_number = %s",
            (user["id"], cbe),
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"Favourite {cbe} not found")

        execute(
            "DELETE FROM favourite WHERE user_id = %s AND enterprise_number = %s",
            (user["id"], cbe),
        )
        return {"enterprise_number": cbe, "status": "removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Remove favourite failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Favourite Projects (grouping) ──────────────────────────────


def _ensure_project_tables():
    """Compatibility shim for project tables moved to tracked migrations."""


_tables_ensured = False


def _ensure_tables_once():
    global _tables_ensured
    if not _tables_ensured:
        try:
            _ensure_project_tables()
            _tables_ensured = True
        except Exception:
            logger.warning("Could not auto-create project tables — may already exist")
            _tables_ensured = True


@router.get("/projects")
async def list_projects(user=Depends(get_current_user)):
    """List all projects for the logged-in user, with member companies."""
    _ensure_tables_once()
    try:
        projects = fetch_all("""
            SELECT id, name, created_at
            FROM favourite_project
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user["id"],))

        result = []
        for proj in projects:
            members = fetch_all("""
                SELECT fpm.enterprise_number,
                       COALESCE(ci.name, d.denomination) AS "name",
                       ci.city, ci.nace_code,
                       fl.revenue, fl.ebitda, fl.fte_total
                FROM favourite_project_member fpm
                LEFT JOIN company_info ci ON ci.enterprise_number = fpm.enterprise_number
                LEFT JOIN denomination d ON d.entity_number = fpm.enterprise_number
                     AND d.type_of_denomination = '001' AND d.language IN ('2','1')
                LEFT JOIN financial_latest fl ON fl.enterprise_number = fpm.enterprise_number
                WHERE fpm.project_id = %s
            """, (proj["id"],))
            result.append({
                **_serialize_row(proj),
                "members": [_serialize_row(m) for m in members],
            })
        return result
    except Exception as e:
        logger.exception("List projects failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate, user=Depends(get_current_user)):
    """Create a new project."""
    _ensure_tables_once()
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Project name cannot be empty")
    try:
        row = fetch_one(
            "INSERT INTO favourite_project (user_id, name) VALUES (%s, %s) RETURNING id, name, created_at",
            (user["id"], body.name.strip()),
        )
        return {**_serialize_row(row), "members": []}
    except Exception as e:
        logger.exception("Create project failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/projects/{project_id}/add", status_code=201)
async def add_project_member(project_id: int, body: ProjectMemberAdd, user=Depends(get_current_user)):
    """Add a company to a project."""
    _ensure_tables_once()
    cbe = str(body.enterprise_number).replace(".", "").zfill(10)
    try:
        # Verify project belongs to user
        proj = fetch_one(
            "SELECT id FROM favourite_project WHERE id = %s AND user_id = %s",
            (project_id, user["id"]),
        )
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        execute(
            "INSERT INTO favourite_project_member (project_id, enterprise_number) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (project_id, cbe),
        )
        return {"project_id": project_id, "enterprise_number": cbe, "status": "added"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Add project member failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/projects/{project_id}/remove/{cbe}")
async def remove_project_member(project_id: int, cbe: str, user=Depends(get_current_user)):
    """Remove a company from a project."""
    _ensure_tables_once()
    cbe = cbe.strip().replace(".", "").zfill(10)
    try:
        proj = fetch_one(
            "SELECT id FROM favourite_project WHERE id = %s AND user_id = %s",
            (project_id, user["id"]),
        )
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        execute(
            "DELETE FROM favourite_project_member WHERE project_id = %s AND enterprise_number = %s",
            (project_id, cbe),
        )
        return {"project_id": project_id, "enterprise_number": cbe, "status": "removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Remove project member failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, user=Depends(get_current_user)):
    """Delete an entire project and its members."""
    _ensure_tables_once()
    try:
        proj = fetch_one(
            "SELECT id FROM favourite_project WHERE id = %s AND user_id = %s",
            (project_id, user["id"]),
        )
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        execute("DELETE FROM favourite_project WHERE id = %s", (project_id,))
        return {"project_id": project_id, "status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Delete project failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Notifications: new data for favourited companies ──────────────

@router.get("/notifications")
async def get_notifications(user=Depends(get_current_user)):
    """Check for new financial data loaded for user's favourited companies since they last checked."""
    try:
        # Ensure the user has a last_checked timestamp
        last = fetch_one(
            "SELECT checked_at FROM favourite_last_checked WHERE user_id = %s",
            (user["id"],),
        )
        since = last["checked_at"] if last else None

        # Find favourited companies that got new NBB data since last check
        if since:
            rows = fetch_all("""
                SELECT DISTINCT f.enterprise_number,
                       COALESCE(ci.name, f.enterprise_number) AS name,
                       nll.loaded_at,
                       nll.fiscal_year
                FROM favourite f
                JOIN nbb_load_log nll ON nll.enterprise_number = f.enterprise_number
                LEFT JOIN company_info ci ON ci.enterprise_number = f.enterprise_number
                WHERE f.user_id = %s
                  AND nll.loaded_at > %s
                  AND nll.deposit_key NOT LIKE 'NO_FILINGS%%'
                  AND nll.deposit_key != 'PDF_ONLY'
                ORDER BY nll.loaded_at DESC
                LIMIT 50
            """, (user["id"], since))
        else:
            rows = []

        for r in rows:
            if r.get("loaded_at"):
                r["loaded_at"] = str(r["loaded_at"])

        return {"notifications": [_serialize_row(r) for r in rows], "count": len(rows)}
    except Exception as e:
        logger.exception("Notifications check failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/notifications/mark-read")
async def mark_notifications_read(user=Depends(get_current_user)):
    """Mark all notifications as read by updating the last_checked timestamp."""
    try:
        execute("""
            INSERT INTO favourite_last_checked (user_id, checked_at)
            VALUES (%s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET checked_at = NOW()
        """, (user["id"],))
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Mark read failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── People Favourites ─────────────────────────────────────────────


class CbeListUpload(BaseModel):
    enterprise_numbers: List[str]


class PeopleFavouriteCreate(BaseModel):
    person_name: str
    notes: Optional[str] = None


def _ensure_people_fav_table():
    """Compatibility shim for people_favourite moved to tracked migrations."""


@router.get("/people")
async def list_people_favourites(user=Depends(get_current_user)):
    """List favourite people for the logged-in user."""
    try:
        _ensure_people_fav_table()
        rows = fetch_all("""
            SELECT pf.person_name, pf.notes, pf.added_at,
                   COUNT(DISTINCT a.enterprise_number) AS company_count,
                   STRING_AGG(DISTINCT COALESCE(ci.name, a.enterprise_number), ', ' ORDER BY COALESCE(ci.name, a.enterprise_number)) AS companies
            FROM people_favourite pf
            LEFT JOIN administrator_current a ON UPPER(a.name) = UPPER(pf.person_name)
                AND (a.mandate_end IS NULL OR a.mandate_end = '' OR a.mandate_end::date > CURRENT_DATE)
            LEFT JOIN company_info ci ON ci.enterprise_number = a.enterprise_number
            WHERE pf.user_id = %s
            GROUP BY pf.person_name, pf.notes, pf.added_at
            ORDER BY pf.added_at DESC
        """, (user["id"],))
        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.exception("List people favourites failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/people", status_code=201)
async def add_people_favourite(body: PeopleFavouriteCreate, user=Depends(get_current_user)):
    """Add a person to the user's favourites."""
    try:
        _ensure_people_fav_table()
        name = body.person_name.strip()
        # Check case-insensitively to avoid duplicates with different casing
        existing = fetch_one(
            "SELECT person_name FROM people_favourite WHERE user_id = %s AND LOWER(person_name) = LOWER(%s)",
            (user["id"], name),
        )
        if existing:
            return {"person_name": existing["person_name"], "status": "already_exists"}
        execute(
            """INSERT INTO people_favourite (user_id, person_name, notes)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
            (user["id"], name, body.notes),
        )
        return {"person_name": name, "status": "added"}
    except Exception as e:
        logger.exception("Add people favourite failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/people/{person_name}")
async def remove_people_favourite(person_name: str, user=Depends(get_current_user)):
    """Remove a person from the user's favourites."""
    try:
        _ensure_people_fav_table()
        import urllib.parse
        name = urllib.parse.unquote(person_name).strip()
        existing = fetch_one(
            "SELECT person_name FROM people_favourite WHERE user_id = %s AND LOWER(person_name) = LOWER(%s)",
            (user["id"], name),
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"Person '{name}' not found in favourites")

        execute(
            "DELETE FROM people_favourite WHERE user_id = %s AND LOWER(person_name) = LOWER(%s)",
            (user["id"], name),
        )
        return {"person_name": name, "status": "removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Remove people favourite failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Customers & Suppliers ────────────────────────────────────────


def _ensure_customer_supplier_table():
    """Compatibility shim for customer_supplier_list moved to migrations."""


_cs_tables_ensured = False


def _ensure_cs_tables_once():
    global _cs_tables_ensured
    if not _cs_tables_ensured:
        try:
            _ensure_customer_supplier_table()
            _cs_tables_ensured = True
        except Exception:
            logger.warning("Could not auto-create customer_supplier_list table — may already exist")
            _cs_tables_ensured = True


def _list_cs(user_id: str, list_type: str):
    """Shared query for listing customers or suppliers with financials."""
    _ensure_cs_tables_once()
    rows = fetch_all("""
        SELECT * FROM (
            SELECT DISTINCT ON (cs.enterprise_number)
                   cs.enterprise_number, cs.custom_name, cs.notes, cs.added_at,
                   COALESCE(ci.name, d.denomination) AS "name",
                   ci.city,
                   fl.revenue, fl.ebitda, fl.fte_total,
                   CASE WHEN fl.revenue > 0
                        THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
                   END AS "margin_pct"
            FROM customer_supplier_list cs
            LEFT JOIN company_info ci ON ci.enterprise_number = cs.enterprise_number
            LEFT JOIN LATERAL (
                SELECT denomination FROM denomination
                WHERE entity_number = cs.enterprise_number
                  AND type_of_denomination = '001'
                ORDER BY CASE language WHEN '2' THEN 1 WHEN '1' THEN 2 ELSE 3 END
                LIMIT 1
            ) d ON true
            LEFT JOIN financial_latest fl ON fl.enterprise_number = cs.enterprise_number
            WHERE cs.user_id = %s AND cs.list_type = %s
            ORDER BY cs.enterprise_number
        ) sub
        ORDER BY added_at DESC
    """, (user_id, list_type))
    return [_serialize_row(r) for r in rows]


def _upload_cs(user_id: str, list_type: str, enterprise_numbers: List[str]):
    """Bulk insert CBE numbers into customer/supplier list, return match stats."""
    _ensure_cs_tables_once()
    cleaned = []
    for raw in enterprise_numbers:
        cbe = str(raw).strip().replace(".", "").replace(" ", "")
        if cbe:
            cbe = cbe.zfill(10)
            cleaned.append(cbe)

    if not cleaned:
        return {"matched": 0, "not_found": 0, "total": 0, "not_found_cbes": []}

    # Deduplicate
    cleaned = list(dict.fromkeys(cleaned))

    # Check which ones exist in KBO
    placeholders = ",".join(["%s"] * len(cleaned))
    existing = fetch_all(
        f"SELECT enterprise_number FROM enterprise WHERE enterprise_number IN ({placeholders})",
        tuple(cleaned),
    )
    found_set = {r["enterprise_number"] for r in existing}

    inserted = 0
    for cbe in cleaned:
        if cbe in found_set:
            try:
                execute(
                    """INSERT INTO customer_supplier_list (user_id, list_type, enterprise_number)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (user_id, list_type, cbe),
                )
                inserted += 1
            except Exception:
                logger.warning(f"Failed to insert {cbe} into {list_type} list")

    return {
        "matched": len(found_set),
        "not_found": len(cleaned) - len(found_set),
        "total": len(cleaned),
        "not_found_cbes": [c for c in cleaned if c not in found_set],
    }


def _remove_cs(user_id: str, list_type: str, cbe: str):
    """Remove one entry from customer/supplier list."""
    _ensure_cs_tables_once()
    cbe = cbe.strip().replace(".", "").zfill(10)
    existing = fetch_one(
        "SELECT 1 FROM customer_supplier_list WHERE user_id = %s AND list_type = %s AND enterprise_number = %s",
        (user_id, list_type, cbe),
    )
    if not existing:
        raise HTTPException(status_code=404, detail=f"{list_type.title()} {cbe} not found")
    execute(
        "DELETE FROM customer_supplier_list WHERE user_id = %s AND list_type = %s AND enterprise_number = %s",
        (user_id, list_type, cbe),
    )
    return {"enterprise_number": cbe, "status": "removed"}


# Customers

@router.get("/customers")
async def list_customers(user=Depends(get_current_user)):
    """List customer companies for the logged-in user with financials."""
    try:
        return _list_cs(user["id"], "customer")
    except Exception as e:
        logger.exception("List customers failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/customers/upload")
async def upload_customers(body: CbeListUpload, user=Depends(get_current_user)):
    """Bulk upload customer CBE numbers."""
    try:
        return _upload_cs(user["id"], "customer", body.enterprise_numbers)
    except Exception as e:
        logger.exception("Upload customers failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/customers/{cbe}")
async def remove_customer(cbe: str, user=Depends(get_current_user)):
    """Remove a customer from the list."""
    try:
        return _remove_cs(user["id"], "customer", cbe)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Remove customer failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Suggest Similar Customers (AI-powered, Premium) ────────────

@router.post("/customers/suggest-similar")
async def suggest_similar_customers(user=Depends(get_current_user)):
    """Analyze the user's customer list and suggest similar companies using AI."""
    _ensure_cs_tables_once()
    try:
        # 1. Get customer enterprise_numbers
        customer_rows = fetch_all(
            "SELECT enterprise_number FROM customer_supplier_list WHERE user_id = %s AND list_type = 'customer'",
            (user["id"],),
        )
        if not customer_rows:
            return []

        customer_cbes = [r["enterprise_number"] for r in customer_rows]
        placeholders = ",".join(["%s"] * len(customer_cbes))

        # 2. Get NACE codes of customers
        nace_rows = fetch_all(f"""
            SELECT ci.nace_code, COUNT(*) AS cnt
            FROM company_info ci
            WHERE ci.enterprise_number IN ({placeholders})
              AND ci.nace_code IS NOT NULL AND ci.nace_code != ''
            GROUP BY ci.nace_code
            ORDER BY cnt DESC
            LIMIT 10
        """, tuple(customer_cbes))
        nace_codes = [r["nace_code"] for r in nace_rows]
        if not nace_codes:
            return []

        # 3. Get revenue range of customers
        rev_row = fetch_one(f"""
            SELECT MIN(fl.revenue) AS min_rev, MAX(fl.revenue) AS max_rev,
                   AVG(fl.revenue) AS avg_rev
            FROM financial_latest fl
            WHERE fl.enterprise_number IN ({placeholders})
              AND fl.revenue IS NOT NULL AND fl.revenue > 0
        """, tuple(customer_cbes))
        min_rev = float(rev_row["min_rev"]) if rev_row and rev_row["min_rev"] else None
        max_rev = float(rev_row["max_rev"]) if rev_row and rev_row["max_rev"] else None

        # 4. Get common zipcodes/regions of customers
        zip_rows = fetch_all(f"""
            SELECT ci.zipcode, COUNT(*) AS cnt
            FROM company_info ci
            WHERE ci.enterprise_number IN ({placeholders})
              AND ci.zipcode IS NOT NULL AND ci.zipcode != ''
            GROUP BY ci.zipcode
            ORDER BY cnt DESC
            LIMIT 10
        """, tuple(customer_cbes))
        zipcodes = [r["zipcode"] for r in zip_rows]

        # 5. Find similar companies NOT in the customer list
        nace_ph = ",".join(["%s"] * len(nace_codes))
        cust_ph = ",".join(["%s"] * len(customer_cbes))

        # Build revenue filter
        rev_filter = ""
        rev_params: list = []
        if min_rev is not None and max_rev is not None:
            # Expand range by 50% on each side for broader matches
            low = min_rev * 0.5
            high = max_rev * 1.5
            rev_filter = "AND fl.revenue BETWEEN %s AND %s"
            rev_params = [low, high]

        # Region bonus: order by zipcode match first
        zip_case = ""
        zip_params: list = []
        if zipcodes:
            zip_ph = ",".join(["%s"] * len(zipcodes))
            zip_case = f", CASE WHEN ci.zipcode IN ({zip_ph}) THEN 1 ELSE 0 END AS region_match"
            zip_params = zipcodes

        query = f"""
            SELECT ci.enterprise_number,
                   COALESCE(ci.name, d.denomination) AS name,
                   ci.city, ci.nace_code,
                   fl.revenue
                   {zip_case}
            FROM company_info ci
            LEFT JOIN LATERAL (
                SELECT denomination FROM denomination
                WHERE entity_number = ci.enterprise_number
                  AND type_of_denomination = '001'
                ORDER BY CASE language WHEN '2' THEN 1 WHEN '1' THEN 2 ELSE 3 END
                LIMIT 1
            ) d ON true
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
            WHERE ci.nace_code IN ({nace_ph})
              AND ci.enterprise_number NOT IN ({cust_ph})
              AND e.status = '0'
              {rev_filter}
              AND (ci.name IS NOT NULL OR d.denomination IS NOT NULL)
            ORDER BY
                {('region_match DESC, ' if zipcodes else '')}
                fl.revenue DESC NULLS LAST
            LIMIT 40
        """
        params = (*zip_params, *nace_codes, *customer_cbes, *rev_params)
        candidates = fetch_all(query, params)

        if not candidates:
            return []

        # Take top 20
        candidates = candidates[:20]

        # 6. Use AI to generate a short reason for each match
        customer_profile = (
            f"NACE sectors: {', '.join(nace_codes[:5])}. "
            f"Revenue range: {fmtEurBackend(min_rev)} - {fmtEurBackend(max_rev)}. "
            f"Common regions (zipcodes): {', '.join(zipcodes[:5]) if zipcodes else 'various'}."
        )

        candidate_lines = []
        for c in candidates:
            candidate_lines.append(
                f"- {c['name']} (NACE: {c.get('nace_code','?')}, City: {c.get('city','?')}, Revenue: {fmtEurBackend(c.get('revenue'))})"
            )

        prompt = (
            f"A user's customer list has this profile:\n{customer_profile}\n\n"
            f"Here are candidate companies similar to their customers:\n"
            + "\n".join(candidate_lines) +
            "\n\nFor each company, write ONE short sentence (max 15 words) explaining "
            "why it matches the customer profile. Focus on sector, size, or region fit. "
            "Return ONLY a numbered list like:\n1. [reason]\n2. [reason]\n..."
        )

        ai_text = await ai_complete(prompt, system="You are a concise business analyst. Give brief reasons why each company matches a customer profile.")

        # Parse AI reasons
        reasons: list[str] = []
        if ai_text:
            for line in ai_text.strip().split("\n"):
                line = line.strip()
                if line and line[0].isdigit():
                    # Remove "1. " prefix
                    parts = line.split(".", 1)
                    if len(parts) > 1:
                        reasons.append(parts[1].strip())
                    else:
                        reasons.append(line)

        # Build result
        result = []
        for i, c in enumerate(candidates):
            reason = reasons[i] if i < len(reasons) else "Similar sector and company profile"
            result.append({
                "enterprise_number": c["enterprise_number"],
                "name": c.get("name") or c["enterprise_number"],
                "city": c.get("city") or "",
                "revenue": float(c["revenue"]) if c.get("revenue") else None,
                "nace_code": c.get("nace_code") or "",
                "reason": reason,
            })

        return result

    except Exception as e:
        logger.exception("Suggest similar customers failed")
        raise HTTPException(status_code=500, detail="Internal server error")


def fmtEurBackend(val) -> str:
    """Format a numeric value as EUR string for AI prompts."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if abs(v) >= 1_000_000:
            return f"\u20ac{v/1_000_000:.1f}M"
        if abs(v) >= 1_000:
            return f"\u20ac{v/1_000:.0f}K"
        return f"\u20ac{v:.0f}"
    except (ValueError, TypeError):
        return "N/A"


# Suppliers

@router.get("/suppliers")
async def list_suppliers(user=Depends(get_current_user)):
    """List supplier companies for the logged-in user with financials."""
    try:
        return _list_cs(user["id"], "supplier")
    except Exception as e:
        logger.exception("List suppliers failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/suppliers/upload")
async def upload_suppliers(body: CbeListUpload, user=Depends(get_current_user)):
    """Bulk upload supplier CBE numbers."""
    try:
        return _upload_cs(user["id"], "supplier", body.enterprise_numbers)
    except Exception as e:
        logger.exception("Upload suppliers failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/suppliers/{cbe}")
async def remove_supplier(cbe: str, user=Depends(get_current_user)):
    """Remove a supplier from the list."""
    try:
        return _remove_cs(user["id"], "supplier", cbe)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Remove supplier failed")
        raise HTTPException(status_code=500, detail="Internal server error")
