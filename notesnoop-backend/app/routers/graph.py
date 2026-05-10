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
            SELECT n.*,
                   npl.state,
                   npl.confidence,
                   npl.source,
                   coalesce(json_agg(DISTINCT p.*) FILTER (WHERE p.id IS NOT NULL), '[]') AS projects
            FROM notes n
            JOIN note_people_links npl ON npl.note_id = n.id
            LEFT JOIN note_projects np ON np.note_id = n.id
            LEFT JOIN projects p ON p.id = np.project_id
            WHERE npl.person_id = %s
            GROUP BY n.id, npl.state, npl.confidence, npl.source
            ORDER BY coalesce(n.occurred_at, n.created_at) DESC
            """,
            (person_id,),
        )
        projects = many(
            cur,
            """
            SELECT p.*, count(DISTINCT n.id) AS mention_count, max(coalesce(n.occurred_at, n.created_at)) AS last_note_at
            FROM projects p
            JOIN note_projects np ON np.project_id = p.id
            JOIN notes n ON n.id = np.note_id
            JOIN note_people_links npl ON npl.note_id = n.id
            WHERE npl.person_id = %s
              AND npl.state IN ('confirmed','auto_linked')
              AND p.kind <> 'personal'
            GROUP BY p.id
            ORDER BY mention_count DESC, p.name
            LIMIT 10
            """,
            (person_id,),
        )
        tasks = many(
            cur,
            """
            SELECT t.*,
                   min(p.name) AS project_name
            FROM tasks t
            JOIN task_people tp ON tp.task_id = t.id
            LEFT JOIN task_projects tpr ON tpr.task_id = t.id
            LEFT JOIN projects p ON p.id = tpr.project_id
            WHERE tp.person_id = %s
              AND t.status <> 'archived'
            GROUP BY t.id
            ORDER BY
              CASE t.status WHEN 'blocked' THEN 1 WHEN 'doing' THEN 2 WHEN 'todo' THEN 3 WHEN 'done' THEN 4 ELSE 5 END,
              t.due_at NULLS LAST,
              t.created_at DESC
            LIMIT 10
            """,
            (person_id,),
        )
        meetings = many(
            cur,
            """
            SELECT m.*,
                   min(p.name) AS project_name
            FROM meetings m
            JOIN meeting_people mp ON mp.meeting_id = m.id
            LEFT JOIN meeting_projects mpr ON mpr.meeting_id = m.id
            LEFT JOIN projects p ON p.id = mpr.project_id
            WHERE mp.person_id = %s
            GROUP BY m.id
            ORDER BY coalesce(m.occurred_at, m.created_at) DESC
            LIMIT 10
            """,
            (person_id,),
        )
        reports = many(
            cur,
            """
            SELECT r.*,
                   min(p.name) AS project_name
            FROM reports r
            JOIN report_people rp ON rp.report_id = r.id
            LEFT JOIN report_projects rpr ON rpr.report_id = r.id
            LEFT JOIN projects p ON p.id = rpr.project_id
            WHERE rp.person_id = %s
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT 10
            """,
            (person_id,),
        )
        companies = many(
            cur,
            """
            SELECT c.*, cp.role
            FROM companies c
            JOIN company_people cp ON cp.company_id = c.id
            WHERE cp.person_id = %s
            ORDER BY c.name
            LIMIT 10
            """,
            (person_id,),
        )
        events = _timeline_events(notes=notes, tasks=tasks, meetings=meetings, reports=reports)
        profile = _person_memory_profile(person, notes, projects, tasks, meetings, reports, companies)
        return {
            "data": {
                "person": person,
                "profile": profile,
                "events": events,
                "notes": notes,
                "projects": projects,
                "tasks": tasks,
                "meetings": meetings,
                "reports": reports,
                "companies": companies,
            }
        }


@router.get("/projects/{project_id}/timeline")
def project_timeline(project_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        project = one(cur, "SELECT * FROM projects WHERE id = %s", (project_id,))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        notes = many(
            cur,
            """
            SELECT n.*,
                   coalesce(json_agg(DISTINCT jsonb_build_object(
                     'id', pe.id,
                     'name', pe.name,
                     'state', npl.state,
                     'confidence', npl.confidence
                   )) FILTER (WHERE pe.id IS NOT NULL), '[]') AS people
            FROM notes n
            JOIN note_projects np ON np.note_id = n.id
            LEFT JOIN note_people_links npl ON npl.note_id = n.id
            LEFT JOIN people pe ON pe.id = npl.person_id
            WHERE np.project_id = %s
            GROUP BY n.id
            ORDER BY coalesce(n.occurred_at, n.created_at) DESC
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
        members = many(
            cur,
            """
            SELECT up.clerk_user_id, up.display_name, up.email, pm.joined_at
            FROM project_members pm
            JOIN user_profiles up ON up.clerk_user_id = pm.clerk_user_id
            WHERE pm.project_id = %s
            ORDER BY pm.joined_at
            """,
            (project_id,),
        )
        invites = many(
            cur,
            """
            SELECT id, email, display_name, status, invited_by, accepted_by, accepted_at, created_at
            FROM project_invites
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT 25
            """,
            (project_id,),
        )
        tasks = many(
            cur,
            """
            SELECT t.*,
                   min(pe.name) AS assignee_name
            FROM tasks t
            JOIN task_projects tp ON tp.task_id = t.id
            LEFT JOIN task_people tpe ON tpe.task_id = t.id AND tpe.relation = 'assignee'
            LEFT JOIN people pe ON pe.id = tpe.person_id
            WHERE tp.project_id = %s
              AND t.status <> 'archived'
            GROUP BY t.id
            ORDER BY
              CASE t.status WHEN 'blocked' THEN 1 WHEN 'doing' THEN 2 WHEN 'todo' THEN 3 WHEN 'done' THEN 4 ELSE 5 END,
              t.due_at NULLS LAST,
              t.created_at DESC
            LIMIT 15
            """,
            (project_id,),
        )
        meetings = many(
            cur,
            """
            SELECT m.*
            FROM meetings m
            JOIN meeting_projects mp ON mp.meeting_id = m.id
            WHERE mp.project_id = %s
            ORDER BY coalesce(m.occurred_at, m.created_at) DESC
            LIMIT 10
            """,
            (project_id,),
        )
        reports = many(
            cur,
            """
            SELECT r.*
            FROM reports r
            JOIN report_projects rp ON rp.report_id = r.id
            WHERE rp.project_id = %s
            ORDER BY r.created_at DESC
            LIMIT 10
            """,
            (project_id,),
        )
        workflows = many(
            cur,
            """
            SELECT w.*,
                   count(DISTINCT wt.task_id) AS task_count
            FROM workflows w
            JOIN workflow_projects wp ON wp.workflow_id = w.id
            LEFT JOIN workflow_tasks wt ON wt.workflow_id = w.id
            WHERE wp.project_id = %s
            GROUP BY w.id
            ORDER BY w.updated_at DESC
            LIMIT 10
            """,
            (project_id,),
        )
        companies = many(
            cur,
            """
            SELECT c.*
            FROM companies c
            JOIN company_projects cp ON cp.company_id = c.id
            WHERE cp.project_id = %s
            ORDER BY c.name
            LIMIT 10
            """,
            (project_id,),
        )
        events = _timeline_events(notes=notes, tasks=tasks, meetings=meetings, reports=reports, workflows=workflows)
        profile = _project_memory_profile(project, notes, people, members, tasks, meetings, reports, workflows, companies)
        return {
            "data": {
                "project": project,
                "profile": profile,
                "events": events,
                "notes": notes,
                "people": people,
                "members": members,
                "invites": invites,
                "tasks": tasks,
                "meetings": meetings,
                "reports": reports,
                "workflows": workflows,
                "companies": companies,
            }
        }


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
                ORDER BY coalesce(n.occurred_at, n.created_at) DESC
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
            ORDER BY coalesce(n.occurred_at, n.created_at) DESC
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
        review = one(cur, "SELECT * FROM review_queue WHERE id = %s AND state = 'open'", (review_id,))
        if not review:
            existing = one(cur, "SELECT state FROM review_queue WHERE id = %s", (review_id,))
            if existing:
                raise HTTPException(status_code=409, detail="Review item is already decided")
            raise HTTPException(status_code=404, detail="Review item not found")
        data = review.get("payload") or {}
        confidence = payload.confidence or data.get("confidence") or 0.75
        person_id = data.get("matched_person_id") or data.get("person_id")
        if review["entity_kind"] == "person" and not person_id:
            person_id = _create_review_person(cur, review, data, user.clerk_user_id)
            if person_id:
                data = {**data, "matched_person_id": str(person_id)}
                _update_review_payload(cur, review_id, data)
        if review["entity_kind"] == "person" and person_id:
            source = "collaborator_suggestion" if review["reason"] == "collaborator_suggestion" else "ai"
            linked_by = data.get("suggested_by") or user.clerk_user_id
            cur.execute(
                """
                INSERT INTO note_people_links (note_id, person_id, state, confidence, source, source_user_id)
                VALUES (%s, %s, 'confirmed', %s, %s, %s)
                ON CONFLICT (note_id, person_id) DO UPDATE
                  SET state = 'confirmed',
                      confidence = EXCLUDED.confidence,
                      source = EXCLUDED.source,
                      source_user_id = EXCLUDED.source_user_id
                """,
                (review["entity_id"], person_id, confidence, source, linked_by),
            )
            _reconcile_note_memory_links(
                cur,
                str(review["entity_id"]),
                str(review["workspace_id"]),
                linked_by,
                person_id=str(person_id),
            )
        project_id = data.get("matched_project_id")
        if review["entity_kind"] == "project" and not project_id:
            project_id = _create_review_project(cur, review, data, user.clerk_user_id)
            if project_id:
                data = {**data, "matched_project_id": str(project_id)}
                _update_review_payload(cur, review_id, data)
        if review["entity_kind"] == "project" and project_id:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(review["entity_id"]),))
            cur.execute(
                "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (review["entity_id"], project_id, user.clerk_user_id),
            )
            _reconcile_note_memory_links(
                cur,
                str(review["entity_id"]),
                str(review["workspace_id"]),
                user.clerk_user_id,
                project_id=str(project_id),
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
        review = one(cur, "SELECT * FROM review_queue WHERE id = %s AND state = 'open'", (review_id,))
        if not review:
            existing = one(cur, "SELECT state FROM review_queue WHERE id = %s", (review_id,))
            if existing:
                raise HTTPException(status_code=409, detail="Review item is already decided")
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
        source_note_ids = [link["note_id"] for link in links]
        target_links = many(
            cur,
            "SELECT * FROM note_people_links WHERE person_id = %s AND note_id = ANY(%s::uuid[])",
            (payload.target_person_id, source_note_ids),
        )
        cur.execute(
            """
            INSERT INTO person_merge_undos (
              workspace_id,
              source_person_id,
              target_person_id,
              source_person,
              source_links,
              target_links,
              created_by
            )
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
            RETURNING id
            """,
            (
                source["workspace_id"],
                source_person_id,
                payload.target_person_id,
                json.dumps(_json_safe(source)),
                json.dumps(_json_safe(links)),
                json.dumps(_json_safe(target_links)),
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
        cur.execute(
            """
            UPDATE review_queue
            SET payload = jsonb_set(payload, '{matched_person_id}', to_jsonb(%s::text), true)
            WHERE workspace_id = %s
              AND entity_kind = 'person'
              AND payload->>'matched_person_id' = %s
            """,
            (payload.target_person_id, source["workspace_id"], source_person_id),
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
        target_links = undo.get("target_links") or []
        source_note_ids = [link["note_id"] for link in links]
        if source_note_ids:
            cur.execute(
                "DELETE FROM note_people_links WHERE person_id = %s AND note_id = ANY(%s::uuid[])",
                (undo["target_person_id"], source_note_ids),
            )
        for link in target_links:
            cur.execute(
                """
                INSERT INTO note_people_links (note_id, person_id, state, confidence, source, source_user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (note_id, person_id) DO UPDATE
                  SET state = EXCLUDED.state,
                      confidence = EXCLUDED.confidence,
                      source = EXCLUDED.source,
                      source_user_id = EXCLUDED.source_user_id
                """,
                (
                    link["note_id"],
                    undo["target_person_id"],
                    link["state"],
                    link["confidence"],
                    link["source"],
                    link["source_user_id"],
                    link["created_at"],
                ),
            )
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
                ON CONFLICT (note_id, person_id) DO UPDATE
                  SET state = EXCLUDED.state,
                      confidence = EXCLUDED.confidence,
                      source = EXCLUDED.source,
                      source_user_id = EXCLUDED.source_user_id
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
        if source_note_ids:
            cur.execute(
                """
                UPDATE review_queue
                SET payload = jsonb_set(payload, '{matched_person_id}', to_jsonb(%s::text), true)
                WHERE workspace_id = %s
                  AND entity_kind = 'person'
                  AND entity_id = ANY(%s::uuid[])
                  AND payload->>'matched_person_id' = %s
                """,
                (undo["source_person_id"], undo["workspace_id"], source_note_ids, undo["target_person_id"]),
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


def _person_memory_profile(
    person: dict,
    notes: list[dict],
    projects: list[dict],
    tasks: list[dict],
    meetings: list[dict],
    reports: list[dict],
    companies: list[dict],
) -> dict:
    open_tasks = [task for task in tasks if task.get("status") not in {"done", "archived"}]
    blocked_tasks = [task for task in open_tasks if task.get("status") == "blocked"]
    due_tasks = sorted(
        [task for task in open_tasks if task.get("due_at")],
        key=lambda task: task.get("due_at"),
    )
    last_touch = _latest_timestamp([*notes, *meetings, *reports], "occurred_at", "created_at")
    return {
        "headline": f"{person.get('name')} memory",
        "last_touch_at": last_touch,
        "open_loop_count": len(open_tasks),
        "blocked_count": len(blocked_tasks),
        "project_count": len(projects),
        "meeting_count": len(meetings),
        "report_count": len(reports),
        "companies": [company.get("name") for company in companies[:4] if company.get("name")],
        "next_action": due_tasks[0].get("title") if due_tasks else (open_tasks[0].get("title") if open_tasks else None),
        "top_projects": [project.get("name") for project in projects[:4] if project.get("name")],
    }


def _project_memory_profile(
    project: dict,
    notes: list[dict],
    people: list[dict],
    members: list[dict],
    tasks: list[dict],
    meetings: list[dict],
    reports: list[dict],
    workflows: list[dict],
    companies: list[dict],
) -> dict:
    open_tasks = [task for task in tasks if task.get("status") not in {"done", "archived"}]
    blocked_tasks = [task for task in open_tasks if task.get("status") == "blocked"]
    last_touch = _latest_timestamp([*notes, *meetings, *reports], "occurred_at", "created_at")
    return {
        "headline": f"{project.get('name')} project memory",
        "last_touch_at": last_touch,
        "memory_count": len(notes) + len(tasks) + len(meetings) + len(reports) + len(workflows),
        "open_loop_count": len(open_tasks),
        "blocked_count": len(blocked_tasks),
        "people_count": len(people),
        "member_count": len(members),
        "meeting_count": len(meetings),
        "report_count": len(reports),
        "workflow_count": len(workflows),
        "companies": [company.get("name") for company in companies[:4] if company.get("name")],
        "next_action": open_tasks[0].get("title") if open_tasks else None,
    }


def _timeline_events(
    notes: list[dict],
    tasks: list[dict],
    meetings: list[dict],
    reports: list[dict],
    workflows: list[dict] | None = None,
) -> list[dict]:
    events: list[dict] = []
    for note in notes:
        events.append(
            {
                "kind": "note",
                "section_id": "notes",
                "id": note["id"],
                "note_id": note["id"],
                "title": note.get("title") or "Untitled note",
                "subtitle": _trim_text(note.get("body")),
                "status": note.get("note_kind") or "note",
                "event_at": note.get("occurred_at") or note.get("created_at"),
                "project_name": _project_names(note.get("projects")),
                "source": note.get("source"),
            }
        )
    for task in tasks:
        events.append(
            {
                "kind": "task",
                "section_id": "tasks",
                "id": task["id"],
                "note_id": task.get("source_note_id"),
                "title": task.get("title") or "Untitled task",
                "subtitle": _trim_text(task.get("description")),
                "status": task.get("status"),
                "event_at": task.get("due_at") or task.get("created_at"),
                "project_name": task.get("project_name"),
                "person_name": task.get("assignee_name"),
            }
        )
    for meeting in meetings:
        events.append(
            {
                "kind": "meeting",
                "section_id": "meetings",
                "id": meeting["id"],
                "note_id": meeting.get("source_note_id"),
                "title": meeting.get("title") or "Untitled meeting",
                "subtitle": _trim_text(meeting.get("summary")),
                "status": meeting.get("location"),
                "event_at": meeting.get("occurred_at") or meeting.get("created_at"),
                "project_name": meeting.get("project_name"),
            }
        )
    for report in reports:
        events.append(
            {
                "kind": "report",
                "section_id": "reports",
                "id": report["id"],
                "note_id": report.get("source_note_id"),
                "title": report.get("title") or "Untitled report",
                "subtitle": _trim_text(report.get("body")),
                "status": report.get("status"),
                "event_at": report.get("created_at"),
                "project_name": report.get("project_name"),
            }
        )
    for workflow in workflows or []:
        events.append(
            {
                "kind": "workflow",
                "section_id": "workflows",
                "id": workflow["id"],
                "title": workflow.get("name") or "Untitled workflow",
                "subtitle": _trim_text(workflow.get("description")),
                "status": workflow.get("status"),
                "event_at": workflow.get("updated_at") or workflow.get("created_at"),
                "project_name": workflow.get("project_name"),
            }
        )
    events.sort(key=lambda event: str(event.get("event_at") or ""), reverse=True)
    return events[:40]


def _trim_text(value: str | None, limit: int = 240) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit - 1]}..."


def _project_names(projects) -> str | None:
    if not isinstance(projects, list):
        return None
    names = [project.get("name") for project in projects if isinstance(project, dict) and project.get("name")]
    return ", ".join(names[:3]) or None


def _latest_timestamp(rows: list[dict], *keys: str):
    values = []
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value:
                values.append(value)
                break
    return max(values) if values else None


def _create_review_person(cur, review: dict, data: dict, user_id: str) -> str | None:
    name = _review_payload_name(data)
    if not name:
        return None
    cur.execute(
        """
        INSERT INTO people (workspace_id, name, company, role, email, details, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (review["workspace_id"], name, data.get("company"), data.get("role"), data.get("email"), data.get("details"), user_id),
    )
    return str(cur.fetchone()["id"])


def _create_review_project(cur, review: dict, data: dict, user_id: str) -> str | None:
    name = _review_payload_name(data)
    if not name:
        return None
    cur.execute(
        """
        INSERT INTO projects (workspace_id, name, color_hex, kind, ai_mode, shared, created_by)
        VALUES (%s, %s, %s, 'user', %s, FALSE, %s)
        RETURNING id
        """,
        (review["workspace_id"], name, data.get("color_hex"), data.get("ai_mode") or "on", user_id),
    )
    project_id = str(cur.fetchone()["id"])
    cur.execute(
        "INSERT INTO project_members (project_id, clerk_user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (project_id, user_id),
    )
    return project_id


def _review_payload_name(data: dict) -> str | None:
    name = str(data.get("name") or "").strip()
    return name or None


def _update_review_payload(cur, review_id: str, data: dict) -> None:
    cur.execute(
        "UPDATE review_queue SET payload = %s::jsonb WHERE id = %s",
        (json.dumps(data), review_id),
    )


def _reconcile_note_memory_links(
    cur,
    note_id: str,
    workspace_id: str,
    linked_by: str,
    *,
    person_id: str | None = None,
    project_id: str | None = None,
) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"memory-reconcile:{note_id}",))
    if person_id:
        cur.execute(
            """
            INSERT INTO task_people (task_id, person_id, workspace_id, relation, linked_by)
            SELECT t.id, %s, t.workspace_id, 'assignee', %s
            FROM tasks t
            WHERE t.source_note_id = %s AND t.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (person_id, linked_by, note_id, workspace_id),
        )
        cur.execute(
            """
            INSERT INTO meeting_people (meeting_id, person_id, workspace_id, attendance_status, linked_by)
            SELECT m.id, %s, m.workspace_id, 'attended', %s
            FROM meetings m
            WHERE m.source_note_id = %s AND m.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (person_id, linked_by, note_id, workspace_id),
        )
        cur.execute(
            """
            INSERT INTO report_people (report_id, person_id, workspace_id, linked_by)
            SELECT r.id, %s, r.workspace_id, %s
            FROM reports r
            WHERE r.source_note_id = %s AND r.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (person_id, linked_by, note_id, workspace_id),
        )
        cur.execute(
            """
            INSERT INTO company_people (company_id, person_id, workspace_id, linked_by)
            SELECT cn.company_id, %s, cn.workspace_id, %s
            FROM company_notes cn
            WHERE cn.note_id = %s AND cn.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (person_id, linked_by, note_id, workspace_id),
        )
        cur.execute(
            """
            INSERT INTO workflow_people (workflow_id, person_id, workspace_id, relation, linked_by)
            SELECT wn.workflow_id, %s, wn.workspace_id, 'participant', %s
            FROM workflow_notes wn
            WHERE wn.note_id = %s AND wn.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (person_id, linked_by, note_id, workspace_id),
        )
    if project_id:
        cur.execute(
            """
            INSERT INTO task_projects (task_id, project_id, workspace_id, linked_by)
            SELECT t.id, %s, t.workspace_id, %s
            FROM tasks t
            WHERE t.source_note_id = %s AND t.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (project_id, linked_by, note_id, workspace_id),
        )
        cur.execute(
            """
            INSERT INTO meeting_projects (meeting_id, project_id, workspace_id, linked_by)
            SELECT m.id, %s, m.workspace_id, %s
            FROM meetings m
            WHERE m.source_note_id = %s AND m.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (project_id, linked_by, note_id, workspace_id),
        )
        cur.execute(
            """
            INSERT INTO report_projects (report_id, project_id, workspace_id, linked_by)
            SELECT r.id, %s, r.workspace_id, %s
            FROM reports r
            WHERE r.source_note_id = %s AND r.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (project_id, linked_by, note_id, workspace_id),
        )
        cur.execute(
            """
            INSERT INTO company_projects (company_id, project_id, workspace_id, linked_by)
            SELECT cn.company_id, %s, cn.workspace_id, %s
            FROM company_notes cn
            WHERE cn.note_id = %s AND cn.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (project_id, linked_by, note_id, workspace_id),
        )
        cur.execute(
            """
            INSERT INTO workflow_projects (workflow_id, project_id, workspace_id, linked_by)
            SELECT wn.workflow_id, %s, wn.workspace_id, %s
            FROM workflow_notes wn
            WHERE wn.note_id = %s AND wn.workspace_id = %s
            ON CONFLICT DO NOTHING
            """,
            (project_id, linked_by, note_id, workspace_id),
        )


def _json_safe(value):
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {
            key: None
            if item is None
            else str(item)
            if key.endswith("_at") or key.endswith("_id") or key == "id"
            else item
            for key, item in value.items()
        }
    return value
