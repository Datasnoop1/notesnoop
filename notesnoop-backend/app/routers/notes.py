from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..embeddings import embed_text_sync, vector_literal
from ..schemas import FlagRequest, NoteCreate, NoteLinkPerson, NoteProjectSet, NoteUpdate
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
        if next_body == note["body"] and next_title == note["title"]:
            return {"data": get_note_payload(cur, note_id)}
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (note_id,))
        cur.execute(
            """
            UPDATE notes
            SET title = %s,
                title_is_derived = %s,
                body = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (next_title, title_is_derived, next_body, note_id),
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
    if query:
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
            meta = {"semantic_enabled": False, "semantic_excluded": 0}
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
                "filters": {
                    "project_id": project_id,
                    "person_id": person_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "flagged_only": flagged_only,
                },
            }
        return {"data": rows, "meta": meta}


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
        clauses.append("n.created_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        clauses.append("n.created_at < (%s::date + interval '1 day')")
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
    note["project_nudge"] = _project_nudge(cur, note)
    return note


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
