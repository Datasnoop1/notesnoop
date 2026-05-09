from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..schemas import PersonMergeRequest, ReviewDecision


router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/people/{person_id}/timeline")
def person_timeline(person_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        person = one(cur, "SELECT * FROM people WHERE id = %s", (person_id,))
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        notes = many(
            cur,
            """
            SELECT n.*, npl.state, npl.confidence, npl.source
            FROM notes n
            JOIN note_people_links npl ON npl.note_id = n.id
            WHERE npl.person_id = %s
            ORDER BY n.created_at DESC
            """,
            (person_id,),
        )
        return {"data": {"person": person, "notes": notes}}


@router.get("/projects/{project_id}/timeline")
def project_timeline(project_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        project = one(cur, "SELECT * FROM projects WHERE id = %s", (project_id,))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        notes = many(
            cur,
            """
            SELECT n.*
            FROM notes n
            JOIN note_projects np ON np.note_id = n.id
            WHERE np.project_id = %s
            ORDER BY n.created_at DESC
            """,
            (project_id,),
        )
        people = many(
            cur,
            """
            SELECT p.*, count(DISTINCT npl.note_id) AS mention_count
            FROM people p
            JOIN note_people_links npl ON npl.person_id = p.id
            JOIN note_projects np ON np.note_id = npl.note_id
            WHERE np.project_id = %s AND npl.state IN ('confirmed','auto_linked')
            GROUP BY p.id
            ORDER BY mention_count DESC, p.name
            """,
            (project_id,),
        )
        return {"data": {"project": project, "notes": notes, "people": people}}


@router.get("/briefs/{kind}/{entity_id}")
def copy_brief(kind: str, entity_id: str, variant: str = "quick", user: CurrentUser = Depends(current_user)):
    if kind not in {"note", "person", "project"}:
        raise HTTPException(status_code=404, detail="Unsupported brief type")
    full = variant == "full"
    with transaction(user.clerk_user_id) as cur:
        if kind == "note":
            note = one(cur, "SELECT * FROM notes WHERE id = %s", (entity_id,))
            if not note:
                raise HTTPException(status_code=404, detail="Note not found")
            people = many(
                cur,
                """
                SELECT p.name
                FROM people p
                JOIN note_people_links npl ON npl.person_id = p.id
                WHERE npl.note_id = %s AND npl.state IN ('confirmed','auto_linked')
                ORDER BY p.name
                """,
                (entity_id,),
            )
            lines = [
                f"# {note['title']}",
                f"Saved: {note['created_at']}",
                f"People: {', '.join(p['name'] for p in people) or 'None confirmed'}",
                f"Flag: {'yes' if _is_flagged(cur, user.clerk_user_id, note_id=entity_id) else 'no'}",
            ]
            if full:
                lines += ["", str(note["body"])[:3500]]
            return {"data": {"markdown": "\n".join(lines)}}

        if kind == "person":
            person = one(cur, "SELECT * FROM people WHERE id = %s", (entity_id,))
            if not person:
                raise HTTPException(status_code=404, detail="Person not found")
            projects = many(
                cur,
                """
                SELECT p.name, count(DISTINCT n.id) AS mention_count
                FROM projects p
                JOIN note_projects np ON np.project_id = p.id
                JOIN notes n ON n.id = np.note_id
                JOIN note_people_links npl ON npl.note_id = n.id
                WHERE npl.person_id = %s
                  AND npl.state IN ('confirmed','auto_linked')
                  AND n.is_personal = FALSE
                GROUP BY p.id
                ORDER BY mention_count DESC, p.name
                LIMIT 5
                """,
                (entity_id,),
            )
            notes = many(
                cur,
                """
                SELECT n.title, n.created_at
                FROM notes n
                JOIN note_people_links npl ON npl.note_id = n.id
                WHERE npl.person_id = %s
                  AND npl.state IN ('confirmed','auto_linked')
                  AND n.is_personal = FALSE
                ORDER BY n.created_at DESC
                LIMIT %s
                """,
                (entity_id, 5 if full else 3),
            )
            private_count = one(
                cur,
                """
                SELECT count(*) AS n
                FROM notes n
                JOIN note_people_links npl ON npl.note_id = n.id
                WHERE npl.person_id = %s AND n.is_personal = TRUE
                """,
                (entity_id,),
            )
            lines = [
                f"# {person['name']}",
                f"Company: {person.get('company') or 'Not set'}",
                f"Top projects: {', '.join(p['name'] for p in projects[:3]) or 'None yet'}",
            ]
            if notes:
                lines += ["Recent notes:", *[f"- {n['created_at']}: {n['title']}" for n in notes]]
            if private_count and private_count["n"]:
                lines.append(f"+ {private_count['n']} notes in private projects")
            return {"data": {"markdown": "\n".join(lines)}}

        project = one(cur, "SELECT * FROM projects WHERE id = %s", (entity_id,))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        people = many(
            cur,
            """
            SELECT p.name, count(DISTINCT npl.note_id) AS mention_count
            FROM people p
            JOIN note_people_links npl ON npl.person_id = p.id
            JOIN note_projects np ON np.note_id = npl.note_id
            WHERE np.project_id = %s AND npl.state IN ('confirmed','auto_linked')
            GROUP BY p.id
            ORDER BY mention_count DESC, p.name
            LIMIT 5
            """,
            (entity_id,),
        )
        notes = many(
            cur,
            """
            SELECT n.title, n.created_at
            FROM notes n
            JOIN note_projects np ON np.note_id = n.id
            WHERE np.project_id = %s
            ORDER BY n.created_at DESC
            LIMIT %s
            """,
            (entity_id, 10 if full else 3),
        )
        lines = [
            f"# {project['name']}",
            f"Top people: {', '.join(p['name'] for p in people[:3]) or 'None confirmed yet'}",
            f"Flagged: {'yes' if _is_flagged(cur, user.clerk_user_id, project_id=entity_id) else 'no'}",
        ]
        if notes:
            lines += ["Recent notes:", *[f"- {n['created_at']}: {n['title']}" for n in notes]]
        return {"data": {"markdown": "\n".join(lines)}}


@router.post("/review-queue/{review_id}/accept")
def accept_review(review_id: str, payload: ReviewDecision, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        review = one(cur, "SELECT * FROM review_queue WHERE id = %s", (review_id,))
        if not review:
            raise HTTPException(status_code=404, detail="Review item not found")
        data = review.get("payload") or {}
        confidence = payload.confidence or data.get("confidence") or 0.75
        if review["entity_kind"] == "person" and data.get("matched_person_id"):
            cur.execute(
                """
                INSERT INTO note_people_links (note_id, person_id, state, confidence, source, source_user_id)
                VALUES (%s, %s, 'confirmed', %s, 'ai', %s)
                ON CONFLICT (note_id, person_id) DO UPDATE SET state = 'confirmed'
                """,
                (review["entity_id"], data["matched_person_id"], confidence, user.clerk_user_id),
            )
        if review["entity_kind"] == "project" and data.get("matched_project_id"):
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(review["entity_id"]),))
            cur.execute(
                "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (review["entity_id"], data["matched_project_id"], user.clerk_user_id),
            )
        cur.execute("UPDATE review_queue SET state = 'accepted' WHERE id = %s", (review_id,))
        cur.execute(
            "INSERT INTO calibration_events (workspace_id, confidence, user_decision) VALUES (%s, %s, 'accepted')",
            (review["workspace_id"], confidence),
        )
        return {"data": {"state": "accepted"}}


@router.post("/review-queue/{review_id}/reject")
def reject_review(review_id: str, payload: ReviewDecision, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        review = one(cur, "SELECT * FROM review_queue WHERE id = %s", (review_id,))
        if not review:
            raise HTTPException(status_code=404, detail="Review item not found")
        data = review.get("payload") or {}
        confidence = payload.confidence or data.get("confidence") or 0.75
        cur.execute("UPDATE review_queue SET state = 'rejected' WHERE id = %s", (review_id,))
        cur.execute(
            "INSERT INTO calibration_events (workspace_id, confidence, user_decision) VALUES (%s, %s, 'rejected')",
            (review["workspace_id"], confidence),
        )
        return {"data": {"state": "rejected"}}


@router.post("/people/{source_person_id}/merge")
def merge_person(source_person_id: str, payload: PersonMergeRequest, user: CurrentUser = Depends(current_user)):
    if source_person_id == payload.target_person_id:
        raise HTTPException(status_code=422, detail="Choose a different target person")
    with transaction(user.clerk_user_id) as cur:
        source = one(cur, "SELECT * FROM people WHERE id = %s", (source_person_id,))
        target = one(cur, "SELECT * FROM people WHERE id = %s", (payload.target_person_id,))
        if not source or not target or source["workspace_id"] != target["workspace_id"]:
            raise HTTPException(status_code=404, detail="Merge people not found")
        allowed = source["created_by"] == user.clerk_user_id or target["created_by"] == user.clerk_user_id
        admin = one(
            cur,
            "SELECT 1 FROM workspace_members WHERE workspace_id = %s AND clerk_user_id = %s AND role = 'admin'",
            (source["workspace_id"], user.clerk_user_id),
        )
        if not allowed and not admin:
            raise HTTPException(status_code=403, detail="Not allowed to merge these people")
        links = many(cur, "SELECT * FROM note_people_links WHERE person_id = %s", (source_person_id,))
        cur.execute(
            """
            INSERT INTO person_merge_undos (workspace_id, source_person_id, target_person_id, source_person, source_links, created_by)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
            RETURNING id
            """,
            (
                source["workspace_id"],
                source_person_id,
                payload.target_person_id,
                json.dumps(_json_safe(source)),
                json.dumps(_json_safe(links)),
                user.clerk_user_id,
            ),
        )
        undo_id = str(cur.fetchone()["id"])
        for link in links:
            cur.execute(
                """
                INSERT INTO note_people_links (note_id, person_id, state, confidence, source, source_user_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (note_id, person_id) DO UPDATE
                  SET state = EXCLUDED.state,
                      confidence = GREATEST(note_people_links.confidence, EXCLUDED.confidence)
                """,
                (
                    link["note_id"],
                    payload.target_person_id,
                    link["state"],
                    link["confidence"],
                    link["source"],
                    link["source_user_id"],
                ),
            )
        cur.execute("DELETE FROM people WHERE id = %s", (source_person_id,))
        return {"data": {"merged": True, "undo_id": undo_id}}


@router.post("/person-merges/{undo_id}/undo")
def undo_person_merge(undo_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        undo = one(
            cur,
            "SELECT * FROM person_merge_undos WHERE id = %s AND undone_at IS NULL AND expires_at > now()",
            (undo_id,),
        )
        if not undo:
            raise HTTPException(status_code=404, detail="Undo window has expired")
        source = undo["source_person"]
        links = undo["source_links"]
        cur.execute(
            """
            INSERT INTO people (id, workspace_id, name, company, details, clerk_user_id, created_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                undo["source_person_id"],
                undo["workspace_id"],
                source["name"],
                source.get("company"),
                source.get("details"),
                source.get("clerk_user_id"),
                source.get("created_by"),
                source.get("created_at"),
            ),
        )
        for link in links:
            cur.execute(
                """
                INSERT INTO note_people_links (note_id, person_id, state, confidence, source, source_user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (note_id, person_id) DO UPDATE SET person_id = EXCLUDED.person_id
                """,
                (
                    link["note_id"],
                    undo["source_person_id"],
                    link["state"],
                    link["confidence"],
                    link["source"],
                    link["source_user_id"],
                    link["created_at"],
                ),
            )
        cur.execute("UPDATE person_merge_undos SET undone_at = now() WHERE id = %s", (undo_id,))
        return {"data": {"undone": True}}


def _is_flagged(cur, user_id: str, note_id: str | None = None, project_id: str | None = None, person_id: str | None = None) -> bool:
    return bool(
        one(
            cur,
            """
            SELECT 1 FROM flags
            WHERE flagged_user_id = %s
              AND note_id IS NOT DISTINCT FROM %s::uuid
              AND project_id IS NOT DISTINCT FROM %s::uuid
              AND person_id IS NOT DISTINCT FROM %s::uuid
            LIMIT 1
            """,
            (user_id, note_id, project_id, person_id),
        )
    )


def _json_safe(value):
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: str(item) if key.endswith("_at") or key.endswith("_id") or key == "id" else item for key, item in value.items()}
    return value
