"""Favourites router — per-user company tracking + projects (grouping)."""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute
from auth import get_current_user, optional_user

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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


# ── Favourite Projects (grouping) ──────────────────────────────


def _ensure_project_tables():
    """Create project tables if they do not exist (idempotent)."""
    execute("""
        CREATE TABLE IF NOT EXISTS favourite_project (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS favourite_project_member (
            project_id INTEGER REFERENCES favourite_project(id) ON DELETE CASCADE,
            enterprise_number TEXT NOT NULL,
            PRIMARY KEY (project_id, enterprise_number)
        )
    """)


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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


# ── Notifications: new data for favourited companies ──────────────

@router.get("/notifications")
async def get_notifications(user=Depends(get_current_user)):
    """Check for new financial data loaded for user's favourited companies since they last checked."""
    try:
        # Ensure the user has a last_checked timestamp
        execute("""
            CREATE TABLE IF NOT EXISTS favourite_last_checked (
                user_id TEXT PRIMARY KEY,
                checked_at TIMESTAMP DEFAULT NOW()
            )
        """)
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
                  AND nll.deposit_key != 'NO_FILINGS'
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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))
