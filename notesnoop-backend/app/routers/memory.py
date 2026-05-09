from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..schemas import MeetingCreate, ReportCreate, TaskCreate, TaskUpdate


router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/workspaces/{workspace_id}/tasks")
def list_tasks(workspace_id: str, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        params: list = [workspace_id]
        where = "t.workspace_id = %s"
        if project_id:
            where += " AND EXISTS (SELECT 1 FROM task_projects tp WHERE tp.task_id = t.id AND tp.project_id = %s)"
            params.append(project_id)
        return {
            "data": many(
                cur,
                f"""
                SELECT t.*,
                       coalesce(json_agg(DISTINCT p.*) FILTER (WHERE p.id IS NOT NULL), '[]') AS projects
                FROM tasks t
                LEFT JOIN task_projects tp ON tp.task_id = t.id
                LEFT JOIN projects p ON p.id = tp.project_id
                WHERE {where}
                GROUP BY t.id
                ORDER BY
                  CASE t.status
                    WHEN 'doing' THEN 1
                    WHEN 'blocked' THEN 2
                    WHEN 'todo' THEN 3
                    WHEN 'done' THEN 4
                    ELSE 5
                  END,
                  t.due_at NULLS LAST,
                  t.created_at DESC
                LIMIT 100
                """,
                tuple(params),
            )
        }


@router.post("/workspaces/{workspace_id}/tasks")
def create_task(workspace_id: str, payload: TaskCreate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
        _validate_project_ids(cur, workspace_id, payload.project_ids or [])
        _validate_person_ids(cur, workspace_id, payload.person_ids or [])
        _validate_note_ids(cur, workspace_id, payload.note_ids or [])
        completed_at_sql = "now()" if payload.status == "done" else "NULL"
        cur.execute(
            f"""
            INSERT INTO tasks (workspace_id, title, description, status, priority, due_at, completed_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, {completed_at_sql}, %s)
            RETURNING *
            """,
            (
                workspace_id,
                payload.title.strip(),
                payload.description,
                payload.status,
                payload.priority,
                payload.due_at,
                user.clerk_user_id,
            ),
        )
        task = dict(cur.fetchone())
        _link_many(cur, "task_projects", "task_id", "project_id", task["id"], workspace_id, payload.project_ids or [], user.clerk_user_id)
        for person_id in _dedupe(payload.person_ids or []):
            cur.execute(
                """
                INSERT INTO task_people (task_id, person_id, workspace_id, relation, linked_by)
                VALUES (%s, %s, %s, 'assignee', %s)
                ON CONFLICT DO NOTHING
                """,
                (task["id"], person_id, workspace_id, user.clerk_user_id),
            )
        _link_many(cur, "task_notes", "task_id", "note_id", task["id"], workspace_id, payload.note_ids or [], user.clerk_user_id)
        return {"data": _task_payload(cur, str(task["id"]))}


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        task = one(cur, "SELECT * FROM tasks WHERE id = %s", (task_id,))
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        workspace_id = str(task["workspace_id"])
        if payload.project_ids is not None:
            _validate_project_ids(cur, workspace_id, payload.project_ids)
        if payload.person_ids is not None:
            _validate_person_ids(cur, workspace_id, payload.person_ids)
        if payload.note_ids is not None:
            _validate_note_ids(cur, workspace_id, payload.note_ids)

        next_title = payload.title.strip() if payload.title is not None else task["title"]
        next_status = payload.status or task["status"]
        next_completed_at = task.get("completed_at")
        if payload.status == "done" and not next_completed_at:
            completed_at_sql = "now()"
        elif payload.status and payload.status != "done":
            completed_at_sql = "NULL"
        else:
            completed_at_sql = "%s"

        params = [
            next_title,
            payload.description if "description" in payload.model_fields_set else task.get("description"),
            next_status,
            payload.priority if payload.priority is not None else task.get("priority"),
            payload.due_at if "due_at" in payload.model_fields_set else task.get("due_at"),
        ]
        if completed_at_sql == "%s":
            params.append(next_completed_at)
        params.append(task_id)
        cur.execute(
            f"""
            UPDATE tasks
            SET title = %s,
                description = %s,
                status = %s,
                priority = %s,
                due_at = %s,
                completed_at = {completed_at_sql},
                updated_at = now()
            WHERE id = %s
            """,
            tuple(params),
        )
        if payload.project_ids is not None:
            _replace_links(cur, "task_projects", "task_id", "project_id", task_id, workspace_id, payload.project_ids, user.clerk_user_id)
        if payload.person_ids is not None:
            cur.execute("DELETE FROM task_people WHERE task_id = %s", (task_id,))
            for person_id in _dedupe(payload.person_ids):
                cur.execute(
                    """
                    INSERT INTO task_people (task_id, person_id, workspace_id, relation, linked_by)
                    VALUES (%s, %s, %s, 'assignee', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (task_id, person_id, workspace_id, user.clerk_user_id),
                )
        if payload.note_ids is not None:
            _replace_links(cur, "task_notes", "task_id", "note_id", task_id, workspace_id, payload.note_ids, user.clerk_user_id)
        return {"data": _task_payload(cur, task_id)}


@router.get("/workspaces/{workspace_id}/meetings")
def list_meetings(workspace_id: str, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        params: list = [workspace_id]
        where = "m.workspace_id = %s"
        if project_id:
            where += " AND EXISTS (SELECT 1 FROM meeting_projects mp WHERE mp.meeting_id = m.id AND mp.project_id = %s)"
            params.append(project_id)
        return {
            "data": many(
                cur,
                f"""
                SELECT m.*,
                       coalesce(json_agg(DISTINCT p.*) FILTER (WHERE p.id IS NOT NULL), '[]') AS projects,
                       coalesce(json_agg(DISTINCT pe.*) FILTER (WHERE pe.id IS NOT NULL), '[]') AS people
                FROM meetings m
                LEFT JOIN meeting_projects mp ON mp.meeting_id = m.id
                LEFT JOIN projects p ON p.id = mp.project_id
                LEFT JOIN meeting_people mpe ON mpe.meeting_id = m.id
                LEFT JOIN people pe ON pe.id = mpe.person_id
                WHERE {where}
                GROUP BY m.id
                ORDER BY coalesce(m.occurred_at, m.created_at) DESC
                LIMIT 100
                """,
                tuple(params),
            )
        }


@router.post("/workspaces/{workspace_id}/meetings")
def create_meeting(workspace_id: str, payload: MeetingCreate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
        _validate_project_ids(cur, workspace_id, payload.project_ids or [])
        _validate_person_ids(cur, workspace_id, payload.person_ids or [])
        _validate_note_ids(cur, workspace_id, payload.note_ids or [])
        cur.execute(
            """
            INSERT INTO meetings (workspace_id, title, occurred_at, location, summary, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                workspace_id,
                payload.title.strip(),
                payload.occurred_at,
                payload.location,
                payload.summary,
                user.clerk_user_id,
            ),
        )
        meeting = dict(cur.fetchone())
        _link_many(cur, "meeting_projects", "meeting_id", "project_id", meeting["id"], workspace_id, payload.project_ids or [], user.clerk_user_id)
        _link_many(cur, "meeting_people", "meeting_id", "person_id", meeting["id"], workspace_id, payload.person_ids or [], user.clerk_user_id)
        _link_many(cur, "meeting_notes", "meeting_id", "note_id", meeting["id"], workspace_id, payload.note_ids or [], user.clerk_user_id)
        return {"data": _meeting_payload(cur, str(meeting["id"]))}


@router.get("/workspaces/{workspace_id}/reports")
def list_reports(workspace_id: str, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        params: list = [workspace_id]
        where = "r.workspace_id = %s"
        if project_id:
            where += " AND EXISTS (SELECT 1 FROM report_projects rp WHERE rp.report_id = r.id AND rp.project_id = %s)"
            params.append(project_id)
        return {
            "data": many(
                cur,
                f"""
                SELECT r.*,
                       coalesce(json_agg(DISTINCT p.*) FILTER (WHERE p.id IS NOT NULL), '[]') AS projects
                FROM reports r
                LEFT JOIN report_projects rp ON rp.report_id = r.id
                LEFT JOIN projects p ON p.id = rp.project_id
                WHERE {where}
                GROUP BY r.id
                ORDER BY r.created_at DESC
                LIMIT 100
                """,
                tuple(params),
            )
        }


@router.post("/workspaces/{workspace_id}/reports")
def create_report(workspace_id: str, payload: ReportCreate, user: CurrentUser = Depends(current_user)):
    if payload.period_start and payload.period_end and payload.period_start > payload.period_end:
        raise HTTPException(status_code=422, detail="period_start must be on or before period_end")
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
        _validate_project_ids(cur, workspace_id, payload.project_ids or [])
        _validate_person_ids(cur, workspace_id, payload.person_ids or [])
        _validate_note_ids(cur, workspace_id, payload.note_ids or [])
        _validate_task_ids(cur, workspace_id, payload.task_ids or [])
        cur.execute(
            """
            INSERT INTO reports (workspace_id, title, body, status, period_start, period_end, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                workspace_id,
                payload.title.strip(),
                payload.body,
                payload.status,
                payload.period_start,
                payload.period_end,
                user.clerk_user_id,
            ),
        )
        report = dict(cur.fetchone())
        _link_many(cur, "report_projects", "report_id", "project_id", report["id"], workspace_id, payload.project_ids or [], user.clerk_user_id)
        _link_many(cur, "report_people", "report_id", "person_id", report["id"], workspace_id, payload.person_ids or [], user.clerk_user_id)
        _link_many(cur, "report_notes", "report_id", "note_id", report["id"], workspace_id, payload.note_ids or [], user.clerk_user_id)
        _link_many(cur, "report_tasks", "report_id", "task_id", report["id"], workspace_id, payload.task_ids or [], user.clerk_user_id)
        return {"data": _report_payload(cur, str(report["id"]))}


@router.get("/projects/{project_id}/summary")
def project_summary(project_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        project = one(cur, "SELECT * FROM projects WHERE id = %s", (project_id,))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        notes = many(
            cur,
            """
            SELECT n.title, n.body, coalesce(n.occurred_at, n.created_at) AS sort_at
            FROM notes n
            JOIN note_projects np ON np.note_id = n.id
            WHERE np.project_id = %s
            ORDER BY coalesce(n.occurred_at, n.created_at) DESC, n.id
            LIMIT 10
            """,
            (project_id,),
        )
        tasks = many(
            cur,
            """
            SELECT t.title, t.status, t.priority, t.due_at
            FROM tasks t
            JOIN task_projects tp ON tp.task_id = t.id
            WHERE tp.project_id = %s
              AND t.status <> 'archived'
            ORDER BY
              CASE t.status
                WHEN 'blocked' THEN 1
                WHEN 'doing' THEN 2
                WHEN 'todo' THEN 3
                WHEN 'done' THEN 4
                ELSE 5
              END,
              t.priority,
              t.due_at NULLS LAST,
              t.created_at DESC
            LIMIT 10
            """,
            (project_id,),
        )
        return {"data": build_project_summary(project, notes, tasks)}


def build_project_summary(project: dict, notes: list[dict], tasks: list[dict]) -> dict:
    task_counts = {status: 0 for status in ("todo", "doing", "blocked", "done")}
    for task in tasks:
        status = str(task.get("status") or "")
        if status in task_counts:
            task_counts[status] += 1
    recent_notes = [_display_note(note) for note in notes[:5]]
    open_tasks = [
        {
            "title": str(task.get("title") or "").strip(),
            "status": task.get("status"),
            "priority": task.get("priority"),
            "due_at": task.get("due_at"),
        }
        for task in tasks
        if task.get("status") not in {"done", "archived"}
    ][:5]
    lines = [f"# {project.get('name') or 'Project'}"]
    lines.append(f"Tasks: {task_counts['blocked']} blocked, {task_counts['doing']} doing, {task_counts['todo']} todo, {task_counts['done']} done")
    if open_tasks:
        lines.append("Open tasks:")
        lines.extend(f"- [{task['status']}] {task['title']}" for task in open_tasks)
    if recent_notes:
        lines.append("Recent notes:")
        lines.extend(f"- {note}" for note in recent_notes)
    return {
        "project_id": project.get("id"),
        "project_name": project.get("name"),
        "task_counts": task_counts,
        "open_tasks": open_tasks,
        "recent_notes": recent_notes,
        "markdown": "\n".join(lines),
    }


def _display_note(note: dict) -> str:
    title = str(note.get("title") or "").strip()
    if title:
        return title
    body = " ".join(str(note.get("body") or "").split())
    return body[:80] or "(untitled)"


def _ensure_workspace_access(cur, workspace_id: str) -> None:
    if not one(cur, "SELECT id FROM workspaces WHERE id = %s", (workspace_id,)):
        raise HTTPException(status_code=404, detail="Workspace not found")


def _validate_project_ids(cur, workspace_id: str, ids: list[str]) -> None:
    _validate_ids(cur, "projects", workspace_id, ids, "One or more projects are unavailable")


def _validate_person_ids(cur, workspace_id: str, ids: list[str]) -> None:
    _validate_ids(cur, "people", workspace_id, ids, "One or more people are unavailable")


def _validate_note_ids(cur, workspace_id: str, ids: list[str]) -> None:
    _validate_ids(cur, "notes", workspace_id, ids, "One or more notes are unavailable")


def _validate_task_ids(cur, workspace_id: str, ids: list[str]) -> None:
    _validate_ids(cur, "tasks", workspace_id, ids, "One or more tasks are unavailable")


def _validate_ids(cur, table: str, workspace_id: str, ids: list[str], detail: str) -> None:
    unique_ids = _dedupe(ids)
    if not unique_ids:
        return
    row = one(cur, f"SELECT count(*) AS count FROM {table} WHERE workspace_id = %s AND id = ANY(%s::uuid[])", (workspace_id, unique_ids))
    if not row or int(row["count"]) != len(unique_ids):
        raise HTTPException(status_code=422, detail=detail)


def _link_many(cur, table: str, left_column: str, right_column: str, left_id, workspace_id: str, right_ids: list[str], user_id: str) -> None:
    for right_id in _dedupe(right_ids):
        cur.execute(
            f"""
            INSERT INTO {table} ({left_column}, {right_column}, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (left_id, right_id, workspace_id, user_id),
        )


def _replace_links(cur, table: str, left_column: str, right_column: str, left_id, workspace_id: str, right_ids: list[str], user_id: str) -> None:
    cur.execute(f"DELETE FROM {table} WHERE {left_column} = %s", (left_id,))
    _link_many(cur, table, left_column, right_column, left_id, workspace_id, right_ids, user_id)


def _task_payload(cur, task_id: str) -> dict | None:
    task = one(cur, "SELECT * FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return None
    task["projects"] = many(cur, "SELECT p.* FROM projects p JOIN task_projects tp ON tp.project_id = p.id WHERE tp.task_id = %s ORDER BY p.name", (task_id,))
    task["people"] = many(cur, "SELECT p.*, tp.relation FROM people p JOIN task_people tp ON tp.person_id = p.id WHERE tp.task_id = %s ORDER BY p.name", (task_id,))
    task["notes"] = many(cur, "SELECT n.* FROM notes n JOIN task_notes tn ON tn.note_id = n.id WHERE tn.task_id = %s ORDER BY coalesce(n.occurred_at, n.created_at) DESC", (task_id,))
    return task


def _meeting_payload(cur, meeting_id: str) -> dict | None:
    meeting = one(cur, "SELECT * FROM meetings WHERE id = %s", (meeting_id,))
    if not meeting:
        return None
    meeting["projects"] = many(cur, "SELECT p.* FROM projects p JOIN meeting_projects mp ON mp.project_id = p.id WHERE mp.meeting_id = %s ORDER BY p.name", (meeting_id,))
    meeting["people"] = many(cur, "SELECT p.*, mp.attendance_status FROM people p JOIN meeting_people mp ON mp.person_id = p.id WHERE mp.meeting_id = %s ORDER BY p.name", (meeting_id,))
    meeting["notes"] = many(cur, "SELECT n.* FROM notes n JOIN meeting_notes mn ON mn.note_id = n.id WHERE mn.meeting_id = %s ORDER BY coalesce(n.occurred_at, n.created_at) DESC", (meeting_id,))
    return meeting


def _report_payload(cur, report_id: str) -> dict | None:
    report = one(cur, "SELECT * FROM reports WHERE id = %s", (report_id,))
    if not report:
        return None
    report["projects"] = many(cur, "SELECT p.* FROM projects p JOIN report_projects rp ON rp.project_id = p.id WHERE rp.report_id = %s ORDER BY p.name", (report_id,))
    report["people"] = many(cur, "SELECT p.* FROM people p JOIN report_people rp ON rp.person_id = p.id WHERE rp.report_id = %s ORDER BY p.name", (report_id,))
    report["notes"] = many(cur, "SELECT n.* FROM notes n JOIN report_notes rn ON rn.note_id = n.id WHERE rn.report_id = %s ORDER BY coalesce(n.occurred_at, n.created_at) DESC", (report_id,))
    report["tasks"] = many(cur, "SELECT t.* FROM tasks t JOIN report_tasks rt ON rt.task_id = t.id WHERE rt.report_id = %s ORDER BY t.created_at DESC", (report_id,))
    return report


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
