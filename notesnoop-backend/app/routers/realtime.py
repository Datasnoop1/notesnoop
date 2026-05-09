from __future__ import annotations

import asyncio
import json
import select
from contextlib import suppress
from typing import Any

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..auth import CurrentUser, current_user
from ..config import get_settings
from ..db import many, one, transaction


router = APIRouter(prefix="/api", tags=["realtime"])


@router.get("/review-queue/count")
def review_queue_count(workspace_id: str | None = None, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        resolved_workspace_id = _resolve_workspace_id(cur, user.clerk_user_id, workspace_id)
        if project_id:
            project = one(cur, "SELECT id FROM projects WHERE id = %s AND workspace_id = %s", (project_id, resolved_workspace_id))
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
        row = one(
            cur,
            """
            SELECT count(*) AS count
            FROM review_queue rq
            WHERE rq.workspace_id = %s
              AND rq.target_user_id = %s
              AND rq.state = 'open'
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1
                  FROM note_projects np
                  WHERE np.note_id = rq.entity_id
                    AND np.project_id = %s::uuid
                )
              )
            """,
            (resolved_workspace_id, user.clerk_user_id, project_id, project_id),
        )
        return {"data": {"workspace_id": resolved_workspace_id, "count": int(row["count"] if row else 0)}}


@router.get("/workspaces/{workspace_id}/review-queue")
def list_review_queue(
    workspace_id: str,
    project_id: str | None = None,
    limit: int = 25,
    offset: int = 0,
    user: CurrentUser = Depends(current_user),
):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
        if project_id:
            project = one(cur, "SELECT id FROM projects WHERE id = %s AND workspace_id = %s", (project_id, workspace_id))
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
        rows = many(
            cur,
            """
            SELECT rq.*,
                   n.title AS source_note_title,
                   left(n.body, 320) AS source_snippet,
                   n.note_kind AS source_note_kind,
                   coalesce(n.occurred_at, n.created_at) AS source_at,
                   coalesce(
                     jsonb_agg(
                       DISTINCT jsonb_build_object('id', p.id, 'name', p.name, 'color_hex', p.color_hex)
                     ) FILTER (WHERE p.id IS NOT NULL),
                     '[]'::jsonb
                   ) AS projects
            FROM review_queue rq
            LEFT JOIN notes n ON n.id = rq.entity_id
            LEFT JOIN note_projects np ON np.note_id = n.id
            LEFT JOIN projects p ON p.id = np.project_id
            WHERE rq.workspace_id = %s
              AND rq.target_user_id = %s
              AND rq.state = 'open'
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1
                  FROM note_projects scoped_np
                  WHERE scoped_np.note_id = rq.entity_id
                    AND scoped_np.project_id = %s::uuid
                )
              )
            GROUP BY rq.id, n.id
            ORDER BY rq.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (workspace_id, user.clerk_user_id, project_id, project_id, limit, offset),
        )
        total = one(
            cur,
            """
            SELECT count(*) AS count
            FROM review_queue rq
            WHERE rq.workspace_id = %s
              AND rq.target_user_id = %s
              AND rq.state = 'open'
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1
                  FROM note_projects scoped_np
                  WHERE scoped_np.note_id = rq.entity_id
                    AND scoped_np.project_id = %s::uuid
                )
              )
            """,
            (workspace_id, user.clerk_user_id, project_id, project_id),
        )
        return {"data": rows, "meta": {"count": int(total["count"] if total else 0), "limit": limit, "offset": offset}}


@router.get("/collaborator-activity/{workspace_id}")
def collaborator_activity(workspace_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
        rows = many(
            cur,
            """
            SELECT np.project_id,
                   p.name AS project_name,
                   count(DISTINCT nv.viewer_user_id) AS active_viewer_count,
                   max(nv.last_active) AS last_active_at,
                   coalesce(
                     json_agg(
                       DISTINCT jsonb_build_object(
                         'user_id', nv.viewer_user_id,
                         'display_name', coalesce(up.display_name, nv.viewer_user_id)
                       )
                     ) FILTER (WHERE nv.viewer_user_id IS NOT NULL),
                     '[]'
                   ) AS viewers
            FROM note_viewers nv
            JOIN notes n ON n.id = nv.note_id
            JOIN note_projects np ON np.note_id = n.id
            JOIN projects p ON p.id = np.project_id
            LEFT JOIN user_profiles up ON up.clerk_user_id = nv.viewer_user_id
            WHERE nv.workspace_id = %s
              AND nv.viewer_user_id <> %s
              AND nv.last_active > now() - interval '2 minutes'
              AND p.kind <> 'personal'
            GROUP BY np.project_id, p.name
            ORDER BY max(nv.last_active) DESC
            """,
            (workspace_id, user.clerk_user_id),
        )
        return {"data": rows}


@router.get("/events/{workspace_id}")
async def events(workspace_id: str, request: Request, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
    return StreamingResponse(
        _event_stream(workspace_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _resolve_workspace_id(cur, user_id: str, workspace_id: str | None) -> str:
    if workspace_id:
        _ensure_workspace_access(cur, workspace_id)
        return workspace_id
    row = one(
        cur,
        """
        SELECT workspace_id
        FROM workspace_members
        WHERE clerk_user_id = %s
        ORDER BY joined_at
        LIMIT 1
        """,
        (user_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return str(row["workspace_id"])


def _ensure_workspace_access(cur, workspace_id: str) -> None:
    workspace = one(cur, "SELECT id FROM workspaces WHERE id = %s", (workspace_id,))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")


async def _event_stream(workspace_id: str, request: Request):
    conn = psycopg2.connect(
        get_settings().database_url,
        connect_timeout=10,
        application_name="notesnoop:sse",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("LISTEN notesnoop_events")
        yield _sse("connected", {"workspace_id": workspace_id})
        while not await request.is_disconnected():
            payload = await asyncio.to_thread(_wait_for_notification, conn, 25.0)
            if payload is None:
                yield _sse("ping", {"workspace_id": workspace_id})
                continue
            if payload.get("workspace_id") != workspace_id:
                continue
            event_name = str(payload.get("event") or "message")
            yield _sse(event_name, payload)
    finally:
        with suppress(Exception):
            conn.close()


def _wait_for_notification(conn, timeout_s: float) -> dict[str, Any] | None:
    if select.select([conn], [], [], timeout_s) == ([], [], []):
        return None
    conn.poll()
    if not conn.notifies:
        return None
    notify = conn.notifies.pop(0)
    try:
        payload = json.loads(notify.payload)
    except json.JSONDecodeError:
        return {"event": "message", "payload": notify.payload}
    if isinstance(payload, dict):
        return payload
    return None


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
