from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..schemas import FlagRequest, NoteCreate, NoteLinkPerson
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
        title, derived = derive_title(payload.body, payload.title)
        cur.execute(
            """
            INSERT INTO notes (workspace_id, title, title_is_derived, body, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (workspace_id, title, derived, payload.body, user.clerk_user_id),
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
                ORDER BY n.created_at DESC
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
        return {"data": payload}


@router.post("/notes/{note_id}/people")
def link_person(note_id: str, payload: NoteLinkPerson, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
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
        cur.execute("UPDATE notes SET ai_processing_status = 'processing' WHERE id = %s", (note_id,))
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
def home(workspace_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        return {
            "data": {
                "pending_review": many(
                    cur,
                    "SELECT * FROM review_queue WHERE workspace_id = %s AND state = 'open' ORDER BY created_at DESC LIMIT 5",
                    (workspace_id,),
                ),
                "recent_projects": many(
                    cur,
                    """
                    SELECT p.*, max(n.created_at) AS last_note_at
                    FROM projects p
                    LEFT JOIN note_projects np ON np.project_id = p.id
                    LEFT JOIN notes n ON n.id = np.note_id
                    WHERE p.workspace_id = %s
                    GROUP BY p.id
                    ORDER BY coalesce(max(n.created_at), p.created_at) DESC
                    LIMIT 5
                    """,
                    (workspace_id,),
                ),
                "recent_people": many(
                    cur,
                    """
                    SELECT p.*, max(n.created_at) AS last_note_at, count(npl.note_id) AS mention_count
                    FROM people p
                    LEFT JOIN note_people_links npl ON npl.person_id = p.id AND npl.state IN ('confirmed','auto_linked')
                    LEFT JOIN notes n ON n.id = npl.note_id
                    WHERE p.workspace_id = %s
                    GROUP BY p.id
                    ORDER BY coalesce(max(n.created_at), p.created_at) DESC
                    LIMIT 5
                    """,
                    (workspace_id,),
                ),
                "flagged": many(
                    cur,
                    "SELECT * FROM flags WHERE workspace_id = %s ORDER BY flagged_at DESC LIMIT 5",
                    (workspace_id,),
                ),
                "recent_notes": many(
                    cur,
                    "SELECT * FROM notes WHERE workspace_id = %s ORDER BY created_at DESC LIMIT 5",
                    (workspace_id,),
                ),
            }
        }


@router.get("/workspaces/{workspace_id}/search")
def search(workspace_id: str, q: str = "", user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        if not q.strip():
            rows = many(
                cur,
                """
                SELECT n.*
                FROM recently_accessed ra
                JOIN notes n ON n.id = ra.note_id
                WHERE ra.clerk_user_id = %s AND n.workspace_id = %s
                ORDER BY ra.accessed_at DESC
                LIMIT 20
                """,
                (user.clerk_user_id, workspace_id),
            )
        else:
            rows = many(
                cur,
                """
                SELECT *
                FROM notes
                WHERE workspace_id = %s
                  AND search_vector @@ plainto_tsquery('english', %s)
                ORDER BY ts_rank(search_vector, plainto_tsquery('english', %s)) DESC, created_at DESC
                LIMIT 50
                """,
                (workspace_id, q, q),
            )
        return {"data": rows}


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
    return note
