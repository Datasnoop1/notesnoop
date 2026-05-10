from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..embeddings import embed_text_sync, vector_literal
from ..ollama_client import generate_memory_answer
from ..schemas import FlagRequest, MemoryAskRequest, NoteCreate, NoteLinkPerson, NoteProjectSet, NoteUpdate
from ..services import consume_ai_quota, derive_title, enqueue_ai_if_allowed


router = APIRouter(prefix="/api", tags=["notes"])


def _default_inbox(cur, workspace_id: str, user_id: str) -> str:
    inbox = one(
        cur,
        """
        SELECT id
        FROM projects
        WHERE workspace_id = %s
          AND kind = 'inbox'
          AND (shared = TRUE OR created_by = %s)
        ORDER BY shared ASC, created_at
        LIMIT 1
        """,
        (workspace_id, user_id),
    )
    if not inbox:
        raise HTTPException(status_code=422, detail="Inbox project is missing")
    return str(inbox["id"])


@router.post("/workspaces/{workspace_id}/notes")
def create_note(workspace_id: str, payload: NoteCreate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        project_ids = payload.project_ids or [_default_inbox(cur, workspace_id, user.clerk_user_id)]
        _validate_project_selection(cur, workspace_id, project_ids, confirm_personal_move=True)
        title, derived = derive_title(payload.body, payload.title)
        cur.execute(
            """
            INSERT INTO notes (workspace_id, title, title_is_derived, body, note_kind, occurred_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (workspace_id, title, derived, payload.body, payload.note_kind, payload.occurred_at, user.clerk_user_id),
        )
        note = dict(cur.fetchone())
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(note["id"]),))
        for project_id in project_ids:
            cur.execute(
                """
                INSERT INTO note_projects (note_id, project_id, linked_by)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (note["id"], project_id, user.clerk_user_id),
            )
        cur.execute(
            """
            INSERT INTO note_versions (note_id, version, title, body, edited_by)
            VALUES (%s, 1, %s, %s, %s)
            """,
            (note["id"], title, payload.body, user.clerk_user_id),
        )
        enqueue_ai_if_allowed(cur, workspace_id, str(note["id"]), user.clerk_user_id, project_ids)
        return {"data": get_note_payload(cur, str(note["id"]))}


@router.post("/notes/{note_id}/archive")
def archive_note(note_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        note = one(cur, "SELECT id FROM notes WHERE id = %s", (note_id,))
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        cur.execute(
            "UPDATE notes SET archived_at = now(), updated_at = now() WHERE id = %s",
            (note_id,),
        )
        return {"data": {"id": note_id, "archived": True}}


@router.post("/notes/{note_id}/restore")
def restore_note(note_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        note = one(cur, "SELECT id FROM notes WHERE id = %s", (note_id,))
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        cur.execute(
            "UPDATE notes SET archived_at = NULL, updated_at = now() WHERE id = %s",
            (note_id,),
        )
        return {"data": {"id": note_id, "archived": False}}


@router.patch("/notes/{note_id}")
def update_note(note_id: str, payload: NoteUpdate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        note = one(cur, "SELECT * FROM notes WHERE id = %s", (note_id,))
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        next_body = payload.body if payload.body is not None else note["body"]
        title_was_sent = "title" in payload.model_fields_set
        if title_was_sent:
            next_title, title_is_derived = derive_title(next_body, payload.title)
        elif note["title_is_derived"]:
            next_title, title_is_derived = derive_title(next_body, None)
        else:
            next_title = note["title"]
            title_is_derived = bool(note["title_is_derived"])
        next_kind = payload.note_kind if payload.note_kind is not None else note.get("note_kind", "note")
        occurred_was_sent = "occurred_at" in payload.model_fields_set
        next_occurred_at = payload.occurred_at if occurred_was_sent else note.get("occurred_at")
        if (
            next_body == note["body"]
            and next_title == note["title"]
            and next_kind == note.get("note_kind", "note")
            and next_occurred_at == note.get("occurred_at")
        ):
            return {"data": get_note_payload(cur, note_id)}
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (note_id,))
        cur.execute(
            """
            UPDATE notes
            SET title = %s,
                title_is_derived = %s,
                body = %s,
                note_kind = %s,
                occurred_at = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (next_title, title_is_derived, next_body, next_kind, next_occurred_at, note_id),
        )
        cur.execute(
            """
            INSERT INTO note_versions (note_id, version, title, body, edited_by)
            SELECT %s,
                   COALESCE(max(version), 0) + 1,
                   %s,
                   %s,
                   %s
            FROM note_versions
            WHERE note_id = %s
            """,
            (note_id, next_title, next_body, user.clerk_user_id, note_id),
        )
        return {"data": get_note_payload(cur, note_id)}


@router.get("/notes/{note_id}/versions")
def note_versions(note_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        note = one(cur, "SELECT id FROM notes WHERE id = %s", (note_id,))
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        return {
            "data": many(
                cur,
                """
                SELECT id, note_id, version, title, body, edited_by, created_at
                FROM note_versions
                WHERE note_id = %s
                ORDER BY version DESC
                """,
                (note_id,),
            )
        }


@router.put("/notes/{note_id}/projects")
def set_note_projects(note_id: str, payload: NoteProjectSet, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        note = one(cur, "SELECT * FROM notes WHERE id = %s", (note_id,))
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        projects = _validate_project_selection(
            cur,
            str(note["workspace_id"]),
            payload.project_ids,
            confirm_personal_move=payload.confirm_personal_move,
            current_is_personal=bool(note["is_personal"]),
        )
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (note_id,))
        cur.execute("DELETE FROM note_projects WHERE note_id = %s AND project_id <> ALL(%s::uuid[])", (note_id, payload.project_ids))
        for project in projects:
            cur.execute(
                """
                INSERT INTO note_projects (note_id, project_id, linked_by)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (note_id, project["id"], user.clerk_user_id),
            )
        return {"data": get_note_payload(cur, note_id)}


@router.get("/workspaces/{workspace_id}/triage")
def triage_inbox(workspace_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        rows = many(
            cur,
            """
            SELECT n.id,
                   n.title,
                   left(coalesce(n.body, ''), 280) AS body_preview,
                   n.note_kind,
                   n.ai_processing_status,
                   n.created_at,
                   n.raw_email_metadata,
                   coalesce(json_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.name, 'kind', p.kind, 'color_hex', p.color_hex))
                            FILTER (WHERE p.id IS NOT NULL), '[]') AS projects
            FROM notes n
            LEFT JOIN note_projects np ON np.note_id = n.id
            LEFT JOIN projects p ON p.id = np.project_id
            WHERE n.workspace_id = %s
              AND n.ai_processing_status IN ('unprocessed','skipped')
              AND coalesce(n.archived_at, NULL) IS NULL
            GROUP BY n.id
            ORDER BY n.created_at DESC
            LIMIT 50
            """,
            (workspace_id,),
        )
        return {"data": rows, "meta": {"count": len(rows)}}


@router.post("/workspaces/{workspace_id}/triage/process")
def triage_process(workspace_id: str, payload: dict, user: CurrentUser = Depends(current_user)):
    note_ids = payload.get("note_ids") or []
    if not isinstance(note_ids, list) or not note_ids:
        raise HTTPException(status_code=422, detail="note_ids required")
    queued: list[str] = []
    skipped: list[dict] = []
    with transaction(user.clerk_user_id) as cur:
        rows = many(
            cur,
            """
            SELECT id, is_personal, ai_processing_status
            FROM notes
            WHERE workspace_id = %s
              AND id = ANY(%s::uuid[])
            """,
            (workspace_id, note_ids),
        )
        ok, retry_after = consume_ai_quota(cur, workspace_id, user.clerk_user_id)
        if not ok:
            raise HTTPException(status_code=429, detail="AI rate limit exceeded", headers={"Retry-After": str(retry_after)})
        for row in rows:
            note_id = str(row["id"])
            if row["is_personal"]:
                skipped.append({"id": note_id, "reason": "personal"})
                continue
            cur.execute(
                """
                INSERT INTO ai_jobs (workspace_id, kind, note_id, target_user_id, priority, idempotency_key)
                VALUES (%s, 'reprocess', %s, %s, 10, %s)
                ON CONFLICT (idempotency_key) DO UPDATE
                  SET state = 'queued', attempts = 0, last_error = NULL, completed_at = NULL
                """,
                (workspace_id, note_id, user.clerk_user_id, f"note:{note_id}:reprocess"),
            )
            cur.execute(
                "UPDATE notes SET ai_processing_status = 'processing', ai_processing_error = NULL WHERE id = %s",
                (note_id,),
            )
            queued.append(note_id)
        return {"data": {"queued": queued, "skipped": skipped}, "meta": {"count": len(queued)}}


@router.post("/workspaces/{workspace_id}/triage/archive")
def triage_archive(workspace_id: str, payload: dict, user: CurrentUser = Depends(current_user)):
    note_ids = payload.get("note_ids") or []
    if not isinstance(note_ids, list) or not note_ids:
        raise HTTPException(status_code=422, detail="note_ids required")
    archived: list[str] = []
    with transaction(user.clerk_user_id) as cur:
        rows = many(
            cur,
            "SELECT id FROM notes WHERE workspace_id = %s AND id = ANY(%s::uuid[])",
            (workspace_id, note_ids),
        )
        for row in rows:
            note_id = str(row["id"])
            cur.execute(
                "UPDATE notes SET archived_at = now(), updated_at = now() WHERE id = %s",
                (note_id,),
            )
            archived.append(note_id)
    return {"data": {"archived": archived}, "meta": {"count": len(archived)}}


@router.get("/workspaces/{workspace_id}/notes")
def list_notes(workspace_id: str, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        params: list = [workspace_id]
        where = "n.workspace_id = %s"
        if project_id:
            params.append(project_id)
            where += " AND EXISTS (SELECT 1 FROM note_projects np WHERE np.note_id = n.id AND np.project_id = %s)"
        return {
            "data": many(
                cur,
                f"""
                SELECT n.*,
                       coalesce(json_agg(DISTINCT p.*) FILTER (WHERE p.id IS NOT NULL), '[]') AS projects
                FROM notes n
                LEFT JOIN note_projects np ON np.note_id = n.id
                LEFT JOIN projects p ON p.id = np.project_id
                WHERE {where}
                GROUP BY n.id
                ORDER BY coalesce(n.occurred_at, n.created_at) DESC
                LIMIT 100
                """,
                tuple(params),
            )
        }


@router.get("/notes/{note_id}")
def get_note(note_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        payload = get_note_payload(cur, note_id)
        if not payload:
            raise HTTPException(status_code=404, detail="Note not found")
        cur.execute(
            """
            INSERT INTO recently_accessed (clerk_user_id, note_id, accessed_at)
            VALUES (%s, %s, now())
            ON CONFLICT (clerk_user_id, note_id) DO UPDATE SET accessed_at = EXCLUDED.accessed_at
            """,
            (user.clerk_user_id, note_id),
        )
        cur.execute(
            """
            INSERT INTO note_viewers (note_id, viewer_user_id, workspace_id, last_active)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (note_id, viewer_user_id) DO UPDATE SET last_active = EXCLUDED.last_active
            """,
            (note_id, user.clerk_user_id, payload["workspace_id"]),
        )
        return {"data": payload}


@router.post("/notes/{note_id}/people")
def link_person(note_id: str, payload: NoteLinkPerson, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        note = one(cur, "SELECT * FROM notes WHERE id = %s", (note_id,))
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        person = one(
            cur,
            "SELECT * FROM people WHERE id = %s AND workspace_id = %s",
            (payload.person_id, note["workspace_id"]),
        )
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        if _should_route_collaborator_person_suggestion(cur, note_id, note, user.clerk_user_id, payload.source):
            confidence = payload.confidence or 0.75
            existing = one(
                cur,
                """
                SELECT id
                FROM review_queue
                WHERE workspace_id = %s
                  AND target_user_id = %s
                  AND entity_kind = 'person'
                  AND entity_id = %s
                  AND state = 'open'
                  AND payload->>'person_id' = %s
                LIMIT 1
                """,
                (note["workspace_id"], note["created_by"], note_id, payload.person_id),
            )
            if not existing:
                cur.execute(
                    """
                    INSERT INTO review_queue (workspace_id, target_user_id, entity_kind, entity_id, reason, payload)
                    VALUES (%s, %s, 'person', %s, 'collaborator_suggestion', %s::jsonb)
                    """,
                    (
                        note["workspace_id"],
                        note["created_by"],
                        note_id,
                        json.dumps(
                            {
                                "name": person["name"],
                                "person_id": payload.person_id,
                                "confidence": confidence,
                                "suggested_by": user.clerk_user_id,
                            }
                        ),
                    ),
                )
            linked_note = get_note_payload(cur, note_id) or {}
            linked_note["collaborator_suggestion"] = True
            return {"data": linked_note}

        cur.execute(
            """
            INSERT INTO note_people_links (note_id, person_id, state, confidence, source, source_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (note_id, person_id) DO UPDATE
              SET state = EXCLUDED.state,
                  confidence = EXCLUDED.confidence,
                  source = EXCLUDED.source,
                  source_user_id = EXCLUDED.source_user_id
            """,
            (note_id, payload.person_id, payload.state, payload.confidence, payload.source, user.clerk_user_id),
        )
        return {"data": get_note_payload(cur, note_id)}


@router.post("/notes/{note_id}/process-with-ai")
def process_with_ai(note_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        note = one(cur, "SELECT * FROM notes WHERE id = %s", (note_id,))
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        if note["is_personal"]:
            raise HTTPException(status_code=422, detail="Personal notes are never sent to AI")
        ok, retry_after = consume_ai_quota(cur, str(note["workspace_id"]), user.clerk_user_id)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail="AI rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        cur.execute(
            """
            INSERT INTO ai_jobs (workspace_id, kind, note_id, target_user_id, priority, idempotency_key)
            VALUES (%s, 'reprocess', %s, %s, 10, %s)
            ON CONFLICT (idempotency_key) DO UPDATE
              SET state = 'queued', attempts = 0, last_error = NULL, completed_at = NULL
            """,
            (note["workspace_id"], note_id, user.clerk_user_id, f"note:{note_id}:reprocess"),
        )
        cur.execute("UPDATE notes SET ai_processing_status = 'processing', ai_processing_error = NULL WHERE id = %s", (note_id,))
        return {"data": {"queued": True, "note_id": note_id}}


@router.post("/flags")
def toggle_flag(payload: FlagRequest, user: CurrentUser = Depends(current_user)):
    selected = [payload.note_id, payload.project_id, payload.person_id]
    if sum(1 for value in selected if value) != 1:
        raise HTTPException(status_code=422, detail="Exactly one flag target is required")
    with transaction(user.clerk_user_id) as cur:
        workspace = one(
            cur,
            """
            SELECT workspace_id FROM notes WHERE id = %s
            UNION ALL
            SELECT workspace_id FROM projects WHERE id = %s
            UNION ALL
            SELECT workspace_id FROM people WHERE id = %s
            LIMIT 1
            """,
            (payload.note_id, payload.project_id, payload.person_id),
        )
        if not workspace:
            raise HTTPException(status_code=404, detail="Flag target not found")
        existing = one(
            cur,
            """
            SELECT id FROM flags
            WHERE flagged_user_id = %s
              AND note_id IS NOT DISTINCT FROM %s::uuid
              AND project_id IS NOT DISTINCT FROM %s::uuid
              AND person_id IS NOT DISTINCT FROM %s::uuid
            """,
            (user.clerk_user_id, payload.note_id, payload.project_id, payload.person_id),
        )
        if existing:
            cur.execute("DELETE FROM flags WHERE id = %s", (existing["id"],))
            return {"data": {"flagged": False}}
        cur.execute(
            """
            INSERT INTO flags (flagged_user_id, workspace_id, note_id, project_id, person_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (user.clerk_user_id, workspace["workspace_id"], payload.note_id, payload.project_id, payload.person_id),
        )
        return {"data": {"flagged": True, "flag": dict(cur.fetchone())}}


@router.get("/workspaces/{workspace_id}/home")
def home(workspace_id: str, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        if project_id:
            project = one(cur, "SELECT id FROM projects WHERE id = %s AND workspace_id = %s", (project_id, workspace_id))
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
        pending_review = many(
            cur,
            """
            SELECT *
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
            ORDER BY rq.created_at DESC
            LIMIT 5
            """,
            (workspace_id, user.clerk_user_id, project_id, project_id),
        )
        recent_projects = many(
            cur,
            """
            SELECT p.*,
                   max(coalesce(n.occurred_at, n.created_at)) AS last_note_at,
                   count(DISTINCT n.id) AS mention_count,
                   count(DISTINCT t.id) FILTER (WHERE t.status IN ('todo','doing','blocked')) AS open_task_count,
                   count(DISTINCT t.id) FILTER (WHERE t.status = 'blocked') AS blocked_task_count
            FROM projects p
            LEFT JOIN note_projects np ON np.project_id = p.id
            LEFT JOIN notes n ON n.id = np.note_id
            LEFT JOIN task_projects tp ON tp.project_id = p.id
            LEFT JOIN tasks t ON t.id = tp.task_id
            WHERE p.workspace_id = %s
              AND (%s::uuid IS NULL OR p.id = %s::uuid)
              AND coalesce(p.status, 'active') = 'active'
            GROUP BY p.id
            ORDER BY coalesce(max(coalesce(n.occurred_at, n.created_at)), p.created_at) DESC
            LIMIT 5
            """,
            (workspace_id, project_id, project_id),
        )
        recent_people = many(
            cur,
            """
            SELECT p.*, max(coalesce(n.occurred_at, n.created_at)) AS last_note_at, count(npl.note_id) AS mention_count
            FROM people p
            LEFT JOIN note_people_links npl ON npl.person_id = p.id AND npl.state IN ('confirmed','auto_linked')
            LEFT JOIN notes n ON n.id = npl.note_id
            WHERE p.workspace_id = %s
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1
                  FROM note_people_links pnpl
                  JOIN note_projects pnp ON pnp.note_id = pnpl.note_id
                  WHERE pnpl.person_id = p.id
                    AND pnpl.state IN ('confirmed','auto_linked')
                    AND pnp.project_id = %s::uuid
                )
              )
            GROUP BY p.id
            ORDER BY coalesce(max(coalesce(n.occurred_at, n.created_at)), p.created_at) DESC
            LIMIT 5
            """,
            (workspace_id, project_id, project_id),
        )
        open_tasks = many(
            cur,
            """
            SELECT t.*,
                   coalesce(jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.name, 'color_hex', p.color_hex))
                     FILTER (WHERE p.id IS NOT NULL), '[]'::jsonb) AS projects,
                   coalesce(jsonb_agg(DISTINCT jsonb_build_object('id', pe.id, 'name', pe.name, 'company', pe.company, 'role', pe.role))
                     FILTER (WHERE pe.id IS NOT NULL), '[]'::jsonb) AS people,
                   min(p.name) AS project_name,
                   min(pe.name) AS assignee_name
            FROM tasks t
            LEFT JOIN task_projects tp ON tp.task_id = t.id
            LEFT JOIN projects p ON p.id = tp.project_id
            LEFT JOIN task_people tpe ON tpe.task_id = t.id AND tpe.relation = 'assignee'
            LEFT JOIN people pe ON pe.id = tpe.person_id
            WHERE t.workspace_id = %s
              AND t.status IN ('todo','doing','blocked')
              AND (%s::uuid IS NULL OR tp.project_id = %s::uuid)
            GROUP BY t.id
            ORDER BY
              CASE t.status
                WHEN 'blocked' THEN 1
                WHEN 'doing' THEN 2
                WHEN 'todo' THEN 3
                ELSE 4
              END,
              t.due_at NULLS LAST,
              t.priority,
              t.created_at DESC
            LIMIT 8
            """,
            (workspace_id, project_id, project_id),
        )
        reminders = many(
            cur,
            """
            SELECT t.*,
                   tr.id AS reminder_id,
                   tr.remind_at,
                   tr.state AS reminder_state,
                   tr.snoozed_until,
                   coalesce(tr.snoozed_until, tr.remind_at) AS attention_at,
                   coalesce(jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.name, 'color_hex', p.color_hex))
                     FILTER (WHERE p.id IS NOT NULL), '[]'::jsonb) AS projects,
                   coalesce(jsonb_agg(DISTINCT jsonb_build_object('id', pe.id, 'name', pe.name, 'company', pe.company, 'role', pe.role))
                     FILTER (WHERE pe.id IS NOT NULL), '[]'::jsonb) AS people,
                   min(p.name) AS project_name,
                   min(pe.name) AS assignee_name
            FROM task_reminders tr
            JOIN tasks t ON t.id = tr.task_id
            LEFT JOIN task_projects tp ON tp.task_id = t.id
            LEFT JOIN projects p ON p.id = tp.project_id
            LEFT JOIN task_people tpe ON tpe.task_id = t.id AND tpe.relation = 'assignee'
            LEFT JOIN people pe ON pe.id = tpe.person_id
            WHERE tr.workspace_id = %s
              AND tr.state IN ('pending','snoozed')
              AND t.status IN ('todo','doing','blocked')
              AND (%s::uuid IS NULL OR tp.project_id = %s::uuid)
            GROUP BY t.id, tr.id
            ORDER BY
              CASE WHEN coalesce(tr.snoozed_until, tr.remind_at) <= now() THEN 0 ELSE 1 END,
              coalesce(tr.snoozed_until, tr.remind_at),
              t.priority,
              t.created_at DESC
            LIMIT 8
            """,
            (workspace_id, project_id, project_id),
        )
        meetings_calls = many(
            cur,
            """
            SELECT *
            FROM (
              SELECT m.id,
                     NULL::uuid AS note_id,
                     m.source_note_id,
                     m.title,
                     m.summary AS subtitle,
                     'meeting'::text AS note_kind,
                     coalesce(m.occurred_at, m.created_at) AS occurred_at,
                     min(p.name) AS project_name
              FROM meetings m
              LEFT JOIN meeting_projects mp ON mp.meeting_id = m.id
              LEFT JOIN projects p ON p.id = mp.project_id
              WHERE m.workspace_id = %s
                AND (%s::uuid IS NULL OR mp.project_id = %s::uuid)
              GROUP BY m.id
              UNION ALL
              SELECT n.id,
                     n.id AS note_id,
                     n.id AS source_note_id,
                     n.title,
                     left(n.body, 240) AS subtitle,
                     n.note_kind,
                     coalesce(n.occurred_at, n.created_at) AS occurred_at,
                     min(p.name) AS project_name
              FROM notes n
              LEFT JOIN note_projects np ON np.note_id = n.id
              LEFT JOIN projects p ON p.id = np.project_id
              WHERE n.workspace_id = %s
                AND n.note_kind IN ('meeting','call')
                AND (%s::uuid IS NULL OR np.project_id = %s::uuid)
              GROUP BY n.id
            ) memory
            ORDER BY occurred_at DESC
            LIMIT 8
            """,
            (workspace_id, project_id, project_id, workspace_id, project_id, project_id),
        )
        reports_briefs = many(
            cur,
            """
            SELECT *
            FROM (
              SELECT r.id,
                     NULL::uuid AS note_id,
                     r.source_note_id,
                     r.title,
                     left(coalesce(r.body, ''), 240) AS subtitle,
                     r.status,
                     r.created_at,
                     min(p.name) AS project_name
              FROM reports r
              LEFT JOIN report_projects rp ON rp.report_id = r.id
              LEFT JOIN projects p ON p.id = rp.project_id
              WHERE r.workspace_id = %s
                AND (%s::uuid IS NULL OR rp.project_id = %s::uuid)
              GROUP BY r.id
              UNION ALL
              SELECT n.id,
                     n.id AS note_id,
                     n.id AS source_note_id,
                     n.title,
                     left(n.body, 240) AS subtitle,
                     'note'::text AS status,
                     coalesce(n.occurred_at, n.created_at) AS created_at,
                     min(p.name) AS project_name
              FROM notes n
              LEFT JOIN note_projects np ON np.note_id = n.id
              LEFT JOIN projects p ON p.id = np.project_id
              WHERE n.workspace_id = %s
                AND n.note_kind = 'report'
                AND (%s::uuid IS NULL OR np.project_id = %s::uuid)
              GROUP BY n.id
            ) reports
            ORDER BY created_at DESC
            LIMIT 8
            """,
            (workspace_id, project_id, project_id, workspace_id, project_id, project_id),
        )
        workflows = many(
            cur,
            """
            SELECT w.*,
                   count(DISTINCT wt.task_id) AS task_count,
                   count(DISTINCT wt.task_id) FILTER (WHERE t.status IN ('todo','doing','blocked')) AS open_task_count,
                   min(p.name) AS project_name
            FROM workflows w
            LEFT JOIN workflow_projects wp ON wp.workflow_id = w.id
            LEFT JOIN projects p ON p.id = wp.project_id
            LEFT JOIN workflow_tasks wt ON wt.workflow_id = w.id
            LEFT JOIN tasks t ON t.id = wt.task_id
            WHERE w.workspace_id = %s
              AND (%s::uuid IS NULL OR wp.project_id = %s::uuid)
              AND w.status IN ('draft','active','paused')
            GROUP BY w.id
            ORDER BY
              CASE w.status WHEN 'active' THEN 1 WHEN 'draft' THEN 2 WHEN 'paused' THEN 3 ELSE 4 END,
              w.updated_at DESC
            LIMIT 6
            """,
            (workspace_id, project_id, project_id),
        )
        companies = many(
            cur,
            """
            SELECT c.*,
                   count(DISTINCT cp.person_id) AS people_count,
                   count(DISTINCT cpr.project_id) AS project_count,
                   count(DISTINCT cn.note_id) AS note_count,
                   max(coalesce(n.occurred_at, n.created_at)) AS last_note_at
            FROM companies c
            LEFT JOIN company_people cp ON cp.company_id = c.id
            LEFT JOIN company_projects cpr ON cpr.company_id = c.id
            LEFT JOIN company_notes cn ON cn.company_id = c.id
            LEFT JOIN notes n ON n.id = cn.note_id
            WHERE c.workspace_id = %s
              AND (%s::uuid IS NULL OR cpr.project_id = %s::uuid)
            GROUP BY c.id
            ORDER BY coalesce(max(coalesce(n.occurred_at, n.created_at)), c.created_at) DESC
            LIMIT 6
            """,
            (workspace_id, project_id, project_id),
        )
        project_intelligence = many(
            cur,
            """
            SELECT p.id,
                   p.id AS project_id,
                   p.name AS title,
                   count(DISTINCT n.id) AS memory_count,
                   count(DISTINCT n.id) FILTER (WHERE n.note_kind IN ('meeting','call')) AS meeting_count,
                   count(DISTINCT t.id) FILTER (WHERE t.status IN ('todo','doing','blocked')) AS open_task_count,
                   max(coalesce(n.occurred_at, n.created_at)) AS last_note_at,
                   CASE
                     WHEN count(DISTINCT t.id) FILTER (WHERE t.status = 'blocked') > 0
                       THEN (count(DISTINCT t.id) FILTER (WHERE t.status = 'blocked'))::text || ' blocked task(s)'
                     WHEN count(DISTINCT t.id) FILTER (WHERE t.status IN ('todo','doing')) > 0
                       THEN (count(DISTINCT t.id) FILTER (WHERE t.status IN ('todo','doing')))::text || ' open loop(s)'
                     WHEN count(DISTINCT n.id) > 0
                       THEN (count(DISTINCT n.id))::text || ' captured memory item(s)'
                     ELSE 'Waiting for enough project memory'
                   END AS subtitle
            FROM projects p
            LEFT JOIN note_projects np ON np.project_id = p.id
            LEFT JOIN notes n ON n.id = np.note_id
            LEFT JOIN task_projects tp ON tp.project_id = p.id
            LEFT JOIN tasks t ON t.id = tp.task_id
            WHERE p.workspace_id = %s
              AND p.kind <> 'personal'
              AND (%s::uuid IS NULL OR p.id = %s::uuid)
            GROUP BY p.id
            ORDER BY count(DISTINCT t.id) FILTER (WHERE t.status IN ('todo','doing','blocked')) DESC,
                     max(coalesce(n.occurred_at, n.created_at)) DESC NULLS LAST,
                     p.created_at DESC
            LIMIT 6
            """,
            (workspace_id, project_id, project_id),
        )
        pipeline_row = one(
            cur,
            """
            WITH scoped AS (
              SELECT n.id,
                     n.ai_processing_status,
                     EXISTS (
                       SELECT 1 FROM review_queue rq
                       WHERE rq.entity_id = n.id
                         AND rq.workspace_id = n.workspace_id
                         AND rq.state = 'open'
                     ) AS has_open_review
              FROM notes n
              WHERE n.workspace_id = %s
                AND (
                  %s::uuid IS NULL
                  OR EXISTS (
                    SELECT 1 FROM note_projects np
                    WHERE np.note_id = n.id AND np.project_id = %s::uuid
                  )
                )
            )
            SELECT
              count(*) FILTER (
                WHERE ai_processing_status IN ('unprocessed','skipped')
                  AND NOT has_open_review
              ) AS received,
              count(*) FILTER (WHERE ai_processing_status = 'processing') AS processing,
              count(*) FILTER (
                WHERE has_open_review
              ) AS needs_review,
              count(*) FILTER (
                WHERE ai_processing_status = 'processed' AND NOT has_open_review
              ) AS accepted,
              count(*) FILTER (WHERE ai_processing_status = 'failed') AS failed
            FROM scoped
            """,
            (workspace_id, project_id, project_id),
        )
        pipeline_counts = {
            "received": int((pipeline_row or {}).get("received") or 0),
            "processing": int((pipeline_row or {}).get("processing") or 0),
            "needs_review": int((pipeline_row or {}).get("needs_review") or 0),
            "accepted": int((pipeline_row or {}).get("accepted") or 0),
            "failed": int((pipeline_row or {}).get("failed") or 0),
        }
        pipeline_recent_failed = many(
            cur,
            """
            SELECT id, title, note_kind, ai_processing_error, created_at
            FROM notes n
            WHERE n.workspace_id = %s
              AND n.ai_processing_status = 'failed'
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1 FROM note_projects np
                  WHERE np.note_id = n.id AND np.project_id = %s::uuid
                )
              )
            ORDER BY n.created_at DESC
            LIMIT 3
            """,
            (workspace_id, project_id, project_id),
        )
        loose_notes_without_project = many(
            cur,
            """
            SELECT n.id, n.title, n.note_kind, n.created_at
            FROM notes n
            WHERE n.workspace_id = %s
              AND NOT EXISTS (
                SELECT 1 FROM note_projects np
                WHERE np.note_id = n.id
                  AND EXISTS (
                    SELECT 1 FROM projects p
                    WHERE p.id = np.project_id AND p.kind <> 'inbox'
                  )
              )
              AND n.created_at > now() - interval '30 days'
            ORDER BY n.created_at DESC
            LIMIT 5
            """,
            (workspace_id,),
        )
        loose_tasks_without_owner = many(
            cur,
            """
            SELECT t.id, t.title, t.status, t.due_at, t.created_at
            FROM tasks t
            WHERE t.workspace_id = %s
              AND t.status IN ('todo','doing','blocked')
              AND NOT EXISTS (
                SELECT 1 FROM task_people tp
                WHERE tp.task_id = t.id AND tp.relation = 'assignee'
              )
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1 FROM task_projects tpr
                  WHERE tpr.task_id = t.id AND tpr.project_id = %s::uuid
                )
              )
            ORDER BY t.created_at DESC
            LIMIT 5
            """,
            (workspace_id, project_id, project_id),
        )
        loose_people_without_company = many(
            cur,
            """
            SELECT p.id, p.name, p.created_at
            FROM people p
            WHERE p.workspace_id = %s
              AND NOT EXISTS (
                SELECT 1 FROM company_people cp
                WHERE cp.person_id = p.id
              )
              AND EXISTS (
                SELECT 1 FROM note_people_links npl
                WHERE npl.person_id = p.id
                  AND npl.state IN ('confirmed','auto_linked')
              )
            ORDER BY p.created_at DESC
            LIMIT 5
            """,
            (workspace_id,),
        )
        loose_stale_reviews_row = one(
            cur,
            """
            SELECT count(*) AS count
            FROM review_queue rq
            WHERE rq.workspace_id = %s
              AND rq.target_user_id = %s
              AND rq.state = 'open'
              AND rq.created_at < now() - interval '7 days'
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1 FROM note_projects np
                  WHERE np.note_id = rq.entity_id AND np.project_id = %s::uuid
                )
              )
            """,
            (workspace_id, user.clerk_user_id, project_id, project_id),
        )
        loose_ends = {
            "notes_without_project": loose_notes_without_project,
            "tasks_without_owner": loose_tasks_without_owner,
            "people_without_company": loose_people_without_company,
            "stale_reviews_count": int((loose_stale_reviews_row or {}).get("count") or 0),
        }
        today_row = one(
            cur,
            """
            SELECT
              (SELECT count(*) FROM notes n
                 WHERE n.workspace_id = %s
                   AND n.created_at >= date_trunc('day', now())
                   AND (
                     %s::uuid IS NULL
                     OR EXISTS (SELECT 1 FROM note_projects np WHERE np.note_id = n.id AND np.project_id = %s::uuid)
                   )
              ) AS new_notes,
              (SELECT count(*) FROM tasks t
                 WHERE t.workspace_id = %s
                   AND t.status = 'done'
                   AND t.updated_at >= date_trunc('day', now())
                   AND (
                     %s::uuid IS NULL
                     OR EXISTS (SELECT 1 FROM task_projects tp WHERE tp.task_id = t.id AND tp.project_id = %s::uuid)
                   )
              ) AS tasks_done,
              (SELECT count(*) FROM calibration_events ce
                 WHERE ce.workspace_id = %s
                   AND ce.user_decision = 'accepted'
                   AND ce.created_at >= date_trunc('day', now())
              ) AS reviews_accepted
            """,
            (
                workspace_id, project_id, project_id,
                workspace_id, project_id, project_id,
                workspace_id,
            ),
        )
        today_counts = {
            "new_notes": int((today_row or {}).get("new_notes") or 0),
            "tasks_done": int((today_row or {}).get("tasks_done") or 0),
            "reviews_accepted": int((today_row or {}).get("reviews_accepted") or 0),
        }
        pipeline_recent_received = many(
            cur,
            """
            SELECT id, title, note_kind, ai_processing_status, created_at
            FROM notes n
            WHERE n.workspace_id = %s
              AND n.ai_processing_status IN ('unprocessed','skipped')
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1 FROM note_projects np
                  WHERE np.note_id = n.id AND np.project_id = %s::uuid
                )
              )
            ORDER BY n.created_at DESC
            LIMIT 3
            """,
            (workspace_id, project_id, project_id),
        )
        return {
            "data": {
                "pending_review": pending_review,
                "recent_projects": recent_projects,
                "recent_people": recent_people,
                "flagged": many(
                    cur,
                    """
                    SELECT f.*,
                           CASE
                             WHEN f.note_id IS NOT NULL THEN 'note'
                             WHEN f.project_id IS NOT NULL THEN 'project'
                             ELSE 'person'
                           END AS target_kind,
                           coalesce(n.title, p.name, pe.name) AS label
                    FROM flags f
                    LEFT JOIN notes n ON n.id = f.note_id
                    LEFT JOIN projects p ON p.id = f.project_id
                    LEFT JOIN people pe ON pe.id = f.person_id
                    WHERE f.workspace_id = %s
                      AND (
                        %s::uuid IS NULL
                        OR f.project_id = %s::uuid
                        OR EXISTS (
                          SELECT 1
                          FROM note_projects fnp
                          WHERE fnp.note_id = f.note_id
                            AND fnp.project_id = %s::uuid
                        )
                        OR EXISTS (
                          SELECT 1
                          FROM note_people_links fp
                          JOIN note_projects fpp ON fpp.note_id = fp.note_id
                          WHERE fp.person_id = f.person_id
                            AND fp.state IN ('confirmed','auto_linked')
                            AND fpp.project_id = %s::uuid
                        )
                      )
                    ORDER BY f.flagged_at DESC
                    LIMIT 5
                    """,
                    (workspace_id, project_id, project_id, project_id, project_id),
                ),
                "recent_notes": many(
                    cur,
                    """
                    SELECT *
                    FROM notes n
                    WHERE n.workspace_id = %s
                      AND n.archived_at IS NULL
                      AND (
                        %s::uuid IS NULL
                        OR EXISTS (
                          SELECT 1
                          FROM note_projects np
                          WHERE np.note_id = n.id
                            AND np.project_id = %s::uuid
                        )
                      )
                    ORDER BY coalesce(occurred_at, created_at) DESC
                    LIMIT 5
                    """,
                    (workspace_id, project_id, project_id),
                ),
                "open_tasks": open_tasks,
                "reminders": reminders,
                "meetings_calls": meetings_calls,
                "reports_briefs": reports_briefs,
                "workflows": workflows,
                "companies": companies,
                "project_intelligence": project_intelligence,
                "pipeline_counts": pipeline_counts,
                "pipeline_recent_failed": pipeline_recent_failed,
                "pipeline_recent_received": pipeline_recent_received,
                "loose_ends": loose_ends,
                "today_counts": today_counts,
            }
        }


@router.get("/workspaces/{workspace_id}/search")
def search(
    workspace_id: str,
    q: str = "",
    project_id: str | None = None,
    person_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    flagged_only: bool = False,
    user: CurrentUser = Depends(current_user),
):
    query = q.strip()
    query_embedding = None
    if len(query) >= 3:
        try:
            query_embedding = embed_text_sync(query)
        except Exception:
            query_embedding = None
    with transaction(user.clerk_user_id) as cur:
        where_sql, where_params = _search_where(
            workspace_id,
            user.clerk_user_id,
            project_id,
            person_id,
            date_from,
            date_to,
            flagged_only,
        )
        if not query:
            rows = many(
                cur,
                f"""
                SELECT n.*
                FROM recently_accessed ra
                JOIN notes n ON n.id = ra.note_id
                WHERE ra.clerk_user_id = %s
                  AND {where_sql}
                ORDER BY ra.accessed_at DESC
                LIMIT 20
                """,
                (user.clerk_user_id, *where_params),
            )
            meta = {"semantic_enabled": False, "semantic_excluded": 0, "memory_results": []}
        else:
            keyword_rows = many(
                cur,
                f"""
                SELECT *, 'keyword' AS search_source, ts_rank(search_vector, plainto_tsquery('english', %s)) AS search_score
                FROM notes n
                WHERE {where_sql}
                  AND n.search_vector @@ plainto_tsquery('english', %s)
                ORDER BY search_score DESC, created_at DESC
                LIMIT 50
                """,
                (query, *where_params, query),
            )
            semantic_rows = []
            if query_embedding:
                literal = vector_literal(query_embedding.vector)
                semantic_rows = many(
                    cur,
                    f"""
                    SELECT n.*,
                           'semantic' AS search_source,
                           (1 - (e.embedding <=> %s::vector)) AS search_score
                    FROM embeddings e
                    JOIN notes n ON n.id = e.note_id
                    WHERE {where_sql}
                      AND e.model_version = %s
                    ORDER BY e.embedding <=> %s::vector
                    LIMIT 50
                    """,
                    (literal, *where_params, query_embedding.model, literal),
                )
            rows = _merge_search_rows(keyword_rows, semantic_rows)
            excluded = one(
                cur,
                f"""
                SELECT count(*) AS count
                FROM notes n
                WHERE {where_sql}
                  AND NOT EXISTS (
                    SELECT 1
                    FROM embeddings e
                    WHERE e.note_id = n.id
                  )
                """,
                tuple(where_params),
            )
            meta = {
                "semantic_enabled": bool(query_embedding),
                "semantic_excluded": int(excluded["count"] if excluded else 0),
                "memory_results": _memory_search_results(cur, workspace_id, query, project_id, person_id),
                "filters": {
                    "project_id": project_id,
                    "person_id": person_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "flagged_only": flagged_only,
                },
            }
        return {"data": rows, "meta": meta}


@router.post("/workspaces/{workspace_id}/ask")
def ask_memory(workspace_id: str, payload: MemoryAskRequest, user: CurrentUser = Depends(current_user)):
    query = payload.query.strip()
    query_embedding = None
    try:
        query_embedding = embed_text_sync(query)
    except Exception:
        query_embedding = None
    with transaction(user.clerk_user_id) as cur:
        where_sql, where_params = _search_where(
            workspace_id,
            user.clerk_user_id,
            payload.project_id,
            payload.person_id,
            payload.date_from,
            payload.date_to,
            False,
        )
        keyword_rows = many(
            cur,
            f"""
            SELECT *, 'keyword' AS search_source, ts_rank(search_vector, plainto_tsquery('english', %s)) AS search_score
            FROM notes n
            WHERE {where_sql}
              AND n.search_vector @@ plainto_tsquery('english', %s)
            ORDER BY search_score DESC, created_at DESC
            LIMIT 12
            """,
            (query, *where_params, query),
        )
        semantic_rows = []
        if query_embedding:
            literal = vector_literal(query_embedding.vector)
            semantic_rows = many(
                cur,
                f"""
                SELECT n.*,
                       'semantic' AS search_source,
                       (1 - (e.embedding <=> %s::vector)) AS search_score
                FROM embeddings e
                JOIN notes n ON n.id = e.note_id
                WHERE {where_sql}
                  AND e.model_version = %s
                ORDER BY e.embedding <=> %s::vector
                LIMIT 12
                """,
                (literal, *where_params, query_embedding.model, literal),
            )
        notes = _merge_search_rows(keyword_rows, semantic_rows)[:12]
        memory_results = _merge_memory_results(
            _memory_search_results(cur, workspace_id, query, payload.project_id, payload.person_id),
            _memory_context_results(cur, workspace_id, payload.project_id, payload.person_id),
        )[:18]
        context = {
            "workspace_id": workspace_id,
            "project_id": payload.project_id,
            "person_id": payload.person_id,
            "semantic_enabled": bool(query_embedding),
        }
    answer = asyncio.run(generate_memory_answer(query, notes, memory_results, context))
    return {"data": answer}


def _memory_search_results(cur, workspace_id: str, query: str, project_id: str | None, person_id: str | None) -> list[dict]:
    terms = _memory_query_terms(query)
    project_filter = "%s::uuid IS NULL OR EXISTS (SELECT 1 FROM {link_table} link WHERE link.{id_column} = item.id AND link.project_id = %s::uuid)"
    person_filter = "%s::uuid IS NULL OR EXISTS (SELECT 1 FROM {link_table} link WHERE link.{id_column} = item.id AND link.person_id = %s::uuid)"
    searches = [
        (
            "task",
            "tasks",
            "title",
            "concat_ws(' - ', status, description)",
            "created_at",
            project_filter.format(link_table="task_projects", id_column="task_id"),
            person_filter.format(link_table="task_people", id_column="task_id"),
        ),
        (
            "meeting",
            "meetings",
            "title",
            "summary",
            "coalesce(occurred_at, created_at)",
            project_filter.format(link_table="meeting_projects", id_column="meeting_id"),
            person_filter.format(link_table="meeting_people", id_column="meeting_id"),
        ),
        (
            "report",
            "reports",
            "title",
            "body",
            "created_at",
            project_filter.format(link_table="report_projects", id_column="report_id"),
            person_filter.format(link_table="report_people", id_column="report_id"),
        ),
        (
            "workflow",
            "workflows",
            "name",
            "description",
            "updated_at",
            project_filter.format(link_table="workflow_projects", id_column="workflow_id"),
            person_filter.format(link_table="workflow_people", id_column="workflow_id"),
        ),
        (
            "company",
            "companies",
            "name",
            "coalesce(domain, description)",
            "updated_at",
            project_filter.format(link_table="company_projects", id_column="company_id"),
            person_filter.format(link_table="company_people", id_column="company_id"),
        ),
    ]
    results: list[dict] = []
    for kind, table, title_column, subtitle_column, sort_column, project_sql, person_sql in searches:
        match_sql = _memory_match_sql("item", title_column=title_column, subtitle_column=subtitle_column, term_count=len(terms))
        match_params = [f"%{term}%" for term in terms for _ in range(2)]
        rows = many(
            cur,
            f"""
            SELECT %s AS kind,
                   item.id,
                   item.{title_column} AS title,
                   left(coalesce({subtitle_column}, ''), 260) AS subtitle,
                   {sort_column} AS sort_at
            FROM {table} item
            WHERE item.workspace_id = %s
              AND ({match_sql})
              AND ({project_sql})
              AND ({person_sql})
            ORDER BY {sort_column} DESC
            LIMIT 8
            """,
            (kind, workspace_id, *match_params, project_id, project_id, person_id, person_id),
        )
        results.extend(rows)

    if not person_id:
        person_match_sql = _memory_match_sql("p", title_column="name", subtitle_column="concat_ws(' ', company, role, email)", term_count=len(terms))
        person_match_params = [f"%{term}%" for term in terms for _ in range(2)]
        results.extend(
            many(
                cur,
                f"""
                SELECT 'person' AS kind,
                       p.id,
                       p.name AS title,
                       left(concat_ws(' - ', p.role, p.company, p.email), 260) AS subtitle,
                       p.created_at AS sort_at
                FROM people p
                WHERE p.workspace_id = %s
                  AND ({person_match_sql})
                  AND (
                    %s::uuid IS NULL
                    OR EXISTS (
                      SELECT 1
                      FROM note_people_links npl
                      JOIN note_projects np ON np.note_id = npl.note_id
                      WHERE npl.person_id = p.id
                        AND np.project_id = %s::uuid
                    )
                  )
                ORDER BY p.created_at DESC
                LIMIT 8
                """,
                (workspace_id, *person_match_params, project_id, project_id),
            )
        )

    project_match_sql = _memory_match_sql("p", title_column="name", subtitle_column="kind", term_count=len(terms))
    project_match_params = [f"%{term}%" for term in terms for _ in range(2)]
    results.extend(
        many(
            cur,
            f"""
            SELECT 'project' AS kind,
                   p.id,
                   p.name AS title,
                   p.kind AS subtitle,
                   p.created_at AS sort_at
            FROM projects p
            WHERE p.workspace_id = %s
              AND p.kind <> 'personal'
              AND ({project_match_sql})
              AND (%s::uuid IS NULL OR p.id = %s::uuid)
            ORDER BY p.created_at DESC
            LIMIT 8
            """,
            (workspace_id, *project_match_params, project_id, project_id),
        )
    )
    results.sort(key=lambda row: str(row.get("sort_at") or ""), reverse=True)
    return results[:30]


def _memory_query_terms(query: str) -> list[str]:
    stop_words = {
        "a", "an", "and", "are", "about", "for", "from", "has", "have", "is", "me", "of", "on", "or",
        "show", "tell", "the", "to", "what", "which", "who", "with",
    }
    terms = []
    for term in "".join(char.lower() if char.isalnum() else " " for char in query).split():
        if len(term) < 3 or term in stop_words:
            continue
        if term not in terms:
            terms.append(term)
    return terms or [query.strip()]


def _memory_match_sql(alias: str, title_column: str, subtitle_column: str, term_count: int) -> str:
    checks = [
        f"({alias}.{title_column} ILIKE %s OR coalesce({subtitle_column}, '') ILIKE %s)"
        for _ in range(term_count)
    ]
    return " OR ".join(checks) if checks else "TRUE"


def _merge_memory_results(primary: list[dict], fallback: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for row in [*primary, *fallback]:
        key = (str(row.get("kind") or ""), str(row.get("id") or ""))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _memory_context_results(cur, workspace_id: str, project_id: str | None, person_id: str | None) -> list[dict]:
    if not project_id and not person_id:
        return []
    project_filter = "%s::uuid IS NULL OR EXISTS (SELECT 1 FROM {link_table} link WHERE link.{id_column} = item.id AND link.project_id = %s::uuid)"
    person_filter = "%s::uuid IS NULL OR EXISTS (SELECT 1 FROM {link_table} link WHERE link.{id_column} = item.id AND link.person_id = %s::uuid)"
    searches = [
        ("task", "tasks", "title", "concat_ws(' - ', status, description)", "coalesce(due_at, created_at)", project_filter.format(link_table="task_projects", id_column="task_id"), person_filter.format(link_table="task_people", id_column="task_id")),
        ("meeting", "meetings", "title", "summary", "coalesce(occurred_at, created_at)", project_filter.format(link_table="meeting_projects", id_column="meeting_id"), person_filter.format(link_table="meeting_people", id_column="meeting_id")),
        ("report", "reports", "title", "body", "created_at", project_filter.format(link_table="report_projects", id_column="report_id"), person_filter.format(link_table="report_people", id_column="report_id")),
        ("workflow", "workflows", "name", "description", "updated_at", project_filter.format(link_table="workflow_projects", id_column="workflow_id"), person_filter.format(link_table="workflow_people", id_column="workflow_id")),
        ("company", "companies", "name", "coalesce(domain, description)", "updated_at", project_filter.format(link_table="company_projects", id_column="company_id"), person_filter.format(link_table="company_people", id_column="company_id")),
    ]
    results: list[dict] = []
    for kind, table, title_column, subtitle_column, sort_column, project_sql, person_sql in searches:
        rows = many(
            cur,
            f"""
            SELECT %s AS kind,
                   item.id,
                   item.{title_column} AS title,
                   left(coalesce({subtitle_column}, ''), 260) AS subtitle,
                   {sort_column} AS sort_at
            FROM {table} item
            WHERE item.workspace_id = %s
              AND ({project_sql})
              AND ({person_sql})
            ORDER BY {sort_column} DESC
            LIMIT 6
            """,
            (kind, workspace_id, project_id, project_id, person_id, person_id),
        )
        results.extend(rows)
    results.sort(key=lambda row: str(row.get("sort_at") or ""), reverse=True)
    return results[:20]


def _search_where(
    workspace_id: str,
    user_id: str,
    project_id: str | None,
    person_id: str | None,
    date_from: str | None,
    date_to: str | None,
    flagged_only: bool,
) -> tuple[str, list]:
    clauses = ["n.workspace_id = %s"]
    params: list = [workspace_id]
    if project_id:
        clauses.append("EXISTS (SELECT 1 FROM note_projects np WHERE np.note_id = n.id AND np.project_id = %s)")
        params.append(project_id)
    if person_id:
        clauses.append(
            """
            EXISTS (
              SELECT 1
              FROM note_people_links npl
              WHERE npl.note_id = n.id
                AND npl.person_id = %s
                AND npl.state IN ('confirmed','auto_linked')
            )
            """
        )
        params.append(person_id)
    if date_from:
        clauses.append("coalesce(n.occurred_at, n.created_at) >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        clauses.append("coalesce(n.occurred_at, n.created_at) < (%s::date + interval '1 day')")
        params.append(date_to)
    if flagged_only:
        clauses.append(
            """
            EXISTS (
              SELECT 1
              FROM flags f
              WHERE f.note_id = n.id
                AND f.flagged_user_id = %s
            )
            """
        )
        params.append(user_id)
    return " AND ".join(clauses), params


def _merge_search_rows(keyword_rows: list[dict], semantic_rows: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for row in keyword_rows:
        by_id[str(row["id"])] = row
    for row in semantic_rows:
        key = str(row["id"])
        if key in by_id:
            by_id[key]["search_source"] = "keyword+semantic"
            by_id[key]["search_score"] = max(float(by_id[key].get("search_score") or 0), float(row.get("search_score") or 0))
        else:
            by_id[key] = row
    return sorted(
        by_id.values(),
        key=lambda row: (float(row.get("search_score") or 0), row.get("created_at")),
        reverse=True,
    )[:50]


def _should_route_collaborator_person_suggestion(cur, note_id: str, note: dict, user_id: str, source: str) -> bool:
    if note["created_by"] == user_id and source != "collaborator_suggestion":
        return False
    return bool(
        one(
            cur,
            """
            SELECT 1
            FROM note_projects np
            JOIN projects p ON p.id = np.project_id
            JOIN project_members pm ON pm.project_id = p.id
            WHERE np.note_id = %s
              AND p.shared = TRUE
              AND pm.clerk_user_id = %s
            LIMIT 1
            """,
            (note_id, user_id),
        )
    )


def get_note_payload(cur, note_id: str) -> dict | None:
    note = one(cur, "SELECT * FROM notes WHERE id = %s", (note_id,))
    if not note:
        return None
    note["projects"] = many(
        cur,
        """
        SELECT p.*
        FROM projects p
        JOIN note_projects np ON np.project_id = p.id
        WHERE np.note_id = %s
        ORDER BY p.kind, p.name
        """,
        (note_id,),
    )
    note["people"] = many(
        cur,
        """
        SELECT p.*, npl.state, npl.confidence, npl.source
        FROM people p
        JOIN note_people_links npl ON npl.person_id = p.id
        WHERE npl.note_id = %s
        ORDER BY p.name
        """,
        (note_id,),
    )
    note["versions"] = many(
        cur,
        """
        SELECT version, created_at, edited_by
        FROM note_versions
        WHERE note_id = %s
        ORDER BY version DESC
        LIMIT 5
        """,
        (note_id,),
    )
    note["review_suggestions"] = many(
        cur,
        """
        SELECT rq.id,
               rq.entity_kind,
               rq.reason,
               rq.payload,
               rq.created_at
        FROM review_queue rq
        WHERE rq.entity_id = %s
          AND rq.state = 'open'
        ORDER BY rq.created_at DESC
        LIMIT 20
        """,
        (note_id,),
    )
    note["memory_links"] = _linked_memory_payload(cur, note_id)
    note["project_nudge"] = _project_nudge(cur, note)
    return note


def _linked_memory_payload(cur, note_id: str) -> list[dict]:
    return many(
        cur,
        """
        SELECT *
        FROM (
          SELECT 'task' AS kind,
                 'tasks' AS section_id,
                 t.id,
                 t.title,
                 t.description AS subtitle,
                 t.status,
                 t.due_at AS event_at,
                 t.created_at
          FROM tasks t
          JOIN task_notes tn ON tn.task_id = t.id
          WHERE tn.note_id = %s
          UNION ALL
          SELECT 'meeting' AS kind,
                 'meetings' AS section_id,
                 m.id,
                 m.title,
                 m.summary AS subtitle,
                 NULL::text AS status,
                 coalesce(m.occurred_at, m.created_at) AS event_at,
                 m.created_at
          FROM meetings m
          JOIN meeting_notes mn ON mn.meeting_id = m.id
          WHERE mn.note_id = %s
          UNION ALL
          SELECT 'report' AS kind,
                 'reports' AS section_id,
                 r.id,
                 r.title,
                 r.body AS subtitle,
                 r.status,
                 r.created_at AS event_at,
                 r.created_at
          FROM reports r
          JOIN report_notes rn ON rn.report_id = r.id
          WHERE rn.note_id = %s
          UNION ALL
          SELECT 'workflow' AS kind,
                 'workflows' AS section_id,
                 w.id,
                 w.name AS title,
                 w.description AS subtitle,
                 w.status,
                 w.updated_at AS event_at,
                 w.created_at
          FROM workflows w
          JOIN workflow_notes wn ON wn.workflow_id = w.id
          WHERE wn.note_id = %s
          UNION ALL
          SELECT 'company' AS kind,
                 'companies' AS section_id,
                 c.id,
                 c.name AS title,
                 coalesce(c.domain, c.description) AS subtitle,
                 NULL::text AS status,
                 c.updated_at AS event_at,
                 c.created_at
          FROM companies c
          JOIN company_notes cn ON cn.company_id = c.id
          WHERE cn.note_id = %s
        ) linked
        ORDER BY event_at DESC NULLS LAST, created_at DESC
        LIMIT 40
        """,
        (note_id, note_id, note_id, note_id, note_id),
    )


def _validate_project_selection(
    cur,
    workspace_id: str,
    project_ids: list[str],
    confirm_personal_move: bool,
    current_is_personal: bool = False,
) -> list[dict]:
    unique_ids = list(dict.fromkeys(project_ids))
    if len(unique_ids) != len(project_ids):
        project_ids[:] = unique_ids
    projects = many(
        cur,
        """
        SELECT id, kind, name
        FROM projects
        WHERE workspace_id = %s AND id = ANY(%s::uuid[])
        """,
        (workspace_id, project_ids),
    )
    if len(projects) != len(project_ids):
        raise HTTPException(status_code=422, detail="One or more projects are unavailable")
    has_personal = any(project["kind"] == "personal" for project in projects)
    if has_personal and len(projects) > 1:
        raise HTTPException(status_code=422, detail="Personal notes cannot be linked to other projects")
    if current_is_personal and not has_personal and not confirm_personal_move:
        raise HTTPException(status_code=409, detail="Moving a Personal note requires explicit confirmation")
    return projects


def _project_nudge(cur, note: dict) -> dict:
    linked_ids = {str(project["id"]) for project in note.get("projects", [])}
    linked_kinds = {project["kind"] for project in note.get("projects", [])}
    text = f"{note.get('title') or ''}\n{note.get('body') or ''}".lower()
    candidates = []
    for project in many(
        cur,
        """
        SELECT id, name, kind, color_hex
        FROM projects
        WHERE workspace_id = %s AND kind = 'user'
        ORDER BY created_at
        """,
        (note["workspace_id"],),
    ):
        if str(project["id"]) not in linked_ids and project["name"].lower() in text:
            candidates.append(project)
    return {
        "inbox_only": linked_kinds == {"inbox"},
        "matched_projects": candidates[:3],
        "can_create_project": linked_kinds == {"inbox"} and bool(str(note.get("body") or "").strip()),
    }
