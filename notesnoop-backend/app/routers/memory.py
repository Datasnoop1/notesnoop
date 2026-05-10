from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..schemas import (
    CompanyCreate,
    CompanyUpdate,
    MeetingCreate,
    MeetingUpdate,
    ProjectReportGenerateRequest,
    ReportCreate,
    ReportUpdate,
    TaskCreate,
    TaskReminderUpdate,
    TaskUpdate,
    WorkflowCreate,
    WorkflowUpdate,
)
from ..ollama_client import generate_project_report


router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/workspaces/{workspace_id}/companies")
def list_companies(workspace_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        return {
            "data": many(
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
                GROUP BY c.id
                ORDER BY coalesce(max(coalesce(n.occurred_at, n.created_at)), c.created_at) DESC, lower(c.name)
                LIMIT 100
                """,
                (workspace_id,),
            )
        }


@router.post("/workspaces/{workspace_id}/companies")
def create_company(workspace_id: str, payload: CompanyCreate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
        _validate_person_ids(cur, workspace_id, payload.person_ids or [])
        _validate_project_ids(cur, workspace_id, payload.project_ids or [])
        _validate_note_ids(cur, workspace_id, payload.note_ids or [])
        cur.execute(
            """
            INSERT INTO companies (workspace_id, name, domain, description, created_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (workspace_id, lower(name))
            DO UPDATE
              SET domain = COALESCE(EXCLUDED.domain, companies.domain),
                  description = COALESCE(EXCLUDED.description, companies.description),
                  updated_at = now()
            RETURNING *
            """,
            (workspace_id, payload.name.strip(), payload.domain, payload.description, user.clerk_user_id),
        )
        company = dict(cur.fetchone())
        _link_many(cur, "company_people", "company_id", "person_id", company["id"], workspace_id, payload.person_ids or [], user.clerk_user_id)
        _link_many(cur, "company_projects", "company_id", "project_id", company["id"], workspace_id, payload.project_ids or [], user.clerk_user_id)
        _link_many(cur, "company_notes", "company_id", "note_id", company["id"], workspace_id, payload.note_ids or [], user.clerk_user_id)
        return {"data": _company_payload(cur, str(company["id"]))}


@router.patch("/companies/{company_id}")
def update_company(company_id: str, payload: CompanyUpdate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        company = one(cur, "SELECT * FROM companies WHERE id = %s", (company_id,))
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        workspace_id = str(company["workspace_id"])
        if payload.project_ids is not None:
            _validate_project_ids(cur, workspace_id, payload.project_ids)
        if payload.person_ids is not None:
            _validate_person_ids(cur, workspace_id, payload.person_ids)
        if payload.note_ids is not None:
            _validate_note_ids(cur, workspace_id, payload.note_ids)
        cur.execute(
            """
            UPDATE companies
            SET name = %s,
                domain = %s,
                description = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (
                payload.name.strip() if payload.name is not None else company["name"],
                payload.domain if "domain" in payload.model_fields_set else company.get("domain"),
                payload.description if "description" in payload.model_fields_set else company.get("description"),
                company_id,
            ),
        )
        if payload.person_ids is not None:
            _replace_links(cur, "company_people", "company_id", "person_id", company_id, workspace_id, payload.person_ids, user.clerk_user_id)
        if payload.project_ids is not None:
            _replace_links(cur, "company_projects", "company_id", "project_id", company_id, workspace_id, payload.project_ids, user.clerk_user_id)
        if payload.note_ids is not None:
            _replace_links(cur, "company_notes", "company_id", "note_id", company_id, workspace_id, payload.note_ids, user.clerk_user_id)
        return {"data": _company_payload(cur, company_id)}


@router.get("/companies/{company_id}")
def get_company(company_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        company = _company_payload(cur, company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        return {"data": company}


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
                       coalesce(json_agg(DISTINCT p.*) FILTER (WHERE p.id IS NOT NULL), '[]') AS projects,
                       coalesce(json_agg(DISTINCT pe.*) FILTER (WHERE pe.id IS NOT NULL), '[]') AS people,
                       coalesce(json_agg(DISTINCT n.*) FILTER (WHERE n.id IS NOT NULL), '[]') AS notes,
                       coalesce(json_agg(DISTINCT tr.*) FILTER (WHERE tr.id IS NOT NULL), '[]') AS reminders
                FROM tasks t
                LEFT JOIN task_projects tp ON tp.task_id = t.id
                LEFT JOIN projects p ON p.id = tp.project_id
                LEFT JOIN task_people tpe ON tpe.task_id = t.id
                LEFT JOIN people pe ON pe.id = tpe.person_id
                LEFT JOIN task_notes tn ON tn.task_id = t.id
                LEFT JOIN notes n ON n.id = tn.note_id
                LEFT JOIN task_reminders tr ON tr.task_id = t.id AND tr.state IN ('pending','snoozed')
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


@router.get("/tasks/{task_id}")
def get_task(task_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        task = _task_payload(cur, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"data": task}


@router.get("/workspaces/{workspace_id}/reminders")
def list_task_reminders(workspace_id: str, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        params: list = [workspace_id]
        where = "tr.workspace_id = %s AND tr.state IN ('pending','snoozed')"
        if project_id:
            where += " AND EXISTS (SELECT 1 FROM task_projects tp WHERE tp.task_id = tr.task_id AND tp.project_id = %s)"
            params.append(project_id)
        return {
            "data": many(
                cur,
                f"""
                SELECT tr.*,
                       t.title AS task_title,
                       t.description AS task_description,
                       t.status AS task_status,
                       t.priority,
                       t.due_at,
                       coalesce(tr.snoozed_until, tr.remind_at) AS attention_at,
                       coalesce(json_agg(DISTINCT p.*) FILTER (WHERE p.id IS NOT NULL), '[]') AS projects,
                       coalesce(json_agg(DISTINCT pe.*) FILTER (WHERE pe.id IS NOT NULL), '[]') AS people
                FROM task_reminders tr
                JOIN tasks t ON t.id = tr.task_id
                LEFT JOIN task_projects tp ON tp.task_id = t.id
                LEFT JOIN projects p ON p.id = tp.project_id
                LEFT JOIN task_people tpe ON tpe.task_id = t.id
                LEFT JOIN people pe ON pe.id = tpe.person_id
                WHERE {where}
                GROUP BY tr.id, t.id
                ORDER BY
                  CASE WHEN coalesce(tr.snoozed_until, tr.remind_at) <= now() THEN 0 ELSE 1 END,
                  coalesce(tr.snoozed_until, tr.remind_at),
                  t.priority,
                  tr.created_at DESC
                LIMIT 100
                """,
                tuple(params),
            )
        }


@router.patch("/task-reminders/{reminder_id}")
def update_task_reminder(reminder_id: str, payload: TaskReminderUpdate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        reminder = one(cur, "SELECT * FROM task_reminders WHERE id = %s", (reminder_id,))
        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")
        next_state = payload.state or reminder["state"]
        next_snoozed_until = payload.snoozed_until if "snoozed_until" in payload.model_fields_set else reminder.get("snoozed_until")
        if next_state == "snoozed" and not next_snoozed_until:
            raise HTTPException(status_code=422, detail="Snoozed reminders need snoozed_until")
        if next_state == "pending":
            next_snoozed_until = None
        cur.execute(
            """
            UPDATE task_reminders
            SET remind_at = %s,
                state = %s,
                snoozed_until = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (
                payload.remind_at if "remind_at" in payload.model_fields_set else reminder["remind_at"],
                next_state,
                next_snoozed_until,
                reminder_id,
            ),
        )
        return {"data": _task_reminder_payload(cur, reminder_id)}


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


@router.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: str, payload: MeetingUpdate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        meeting = one(cur, "SELECT * FROM meetings WHERE id = %s", (meeting_id,))
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        workspace_id = str(meeting["workspace_id"])
        if payload.project_ids is not None:
            _validate_project_ids(cur, workspace_id, payload.project_ids)
        if payload.person_ids is not None:
            _validate_person_ids(cur, workspace_id, payload.person_ids)
        if payload.note_ids is not None:
            _validate_note_ids(cur, workspace_id, payload.note_ids)
        cur.execute(
            """
            UPDATE meetings
            SET title = %s,
                occurred_at = %s,
                location = %s,
                summary = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (
                payload.title.strip() if payload.title is not None else meeting["title"],
                payload.occurred_at if "occurred_at" in payload.model_fields_set else meeting.get("occurred_at"),
                payload.location if "location" in payload.model_fields_set else meeting.get("location"),
                payload.summary if "summary" in payload.model_fields_set else meeting.get("summary"),
                meeting_id,
            ),
        )
        if payload.project_ids is not None:
            _replace_links(cur, "meeting_projects", "meeting_id", "project_id", meeting_id, workspace_id, payload.project_ids, user.clerk_user_id)
        if payload.person_ids is not None:
            _replace_links(cur, "meeting_people", "meeting_id", "person_id", meeting_id, workspace_id, payload.person_ids, user.clerk_user_id)
        if payload.note_ids is not None:
            _replace_links(cur, "meeting_notes", "meeting_id", "note_id", meeting_id, workspace_id, payload.note_ids, user.clerk_user_id)
        return {"data": _meeting_payload(cur, meeting_id)}


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        meeting = _meeting_payload(cur, meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return {"data": meeting}


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
        _validate_company_ids(cur, workspace_id, payload.company_ids or [])
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
        _link_many(cur, "report_companies", "report_id", "company_id", report["id"], workspace_id, payload.company_ids or [], user.clerk_user_id)
        _link_many(cur, "report_notes", "report_id", "note_id", report["id"], workspace_id, payload.note_ids or [], user.clerk_user_id)
        _link_many(cur, "report_tasks", "report_id", "task_id", report["id"], workspace_id, payload.task_ids or [], user.clerk_user_id)
        return {"data": _report_payload(cur, str(report["id"]))}


@router.patch("/reports/{report_id}")
def update_report(report_id: str, payload: ReportUpdate, user: CurrentUser = Depends(current_user)):
    if payload.period_start and payload.period_end and payload.period_start > payload.period_end:
        raise HTTPException(status_code=422, detail="period_start must be on or before period_end")
    with transaction(user.clerk_user_id) as cur:
        report = one(cur, "SELECT * FROM reports WHERE id = %s", (report_id,))
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        workspace_id = str(report["workspace_id"])
        if payload.project_ids is not None:
            _validate_project_ids(cur, workspace_id, payload.project_ids)
        if payload.person_ids is not None:
            _validate_person_ids(cur, workspace_id, payload.person_ids)
        if payload.company_ids is not None:
            _validate_company_ids(cur, workspace_id, payload.company_ids)
        if payload.note_ids is not None:
            _validate_note_ids(cur, workspace_id, payload.note_ids)
        if payload.task_ids is not None:
            _validate_task_ids(cur, workspace_id, payload.task_ids)
        cur.execute(
            """
            UPDATE reports
            SET title = %s,
                body = %s,
                status = %s,
                period_start = %s,
                period_end = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (
                payload.title.strip() if payload.title is not None else report["title"],
                payload.body if "body" in payload.model_fields_set else report.get("body"),
                payload.status or report["status"],
                payload.period_start if "period_start" in payload.model_fields_set else report.get("period_start"),
                payload.period_end if "period_end" in payload.model_fields_set else report.get("period_end"),
                report_id,
            ),
        )
        if payload.project_ids is not None:
            _replace_links(cur, "report_projects", "report_id", "project_id", report_id, workspace_id, payload.project_ids, user.clerk_user_id)
        if payload.person_ids is not None:
            _replace_links(cur, "report_people", "report_id", "person_id", report_id, workspace_id, payload.person_ids, user.clerk_user_id)
        if payload.company_ids is not None:
            _replace_links(cur, "report_companies", "report_id", "company_id", report_id, workspace_id, payload.company_ids, user.clerk_user_id)
        if payload.note_ids is not None:
            _replace_links(cur, "report_notes", "report_id", "note_id", report_id, workspace_id, payload.note_ids, user.clerk_user_id)
        if payload.task_ids is not None:
            _replace_links(cur, "report_tasks", "report_id", "task_id", report_id, workspace_id, payload.task_ids, user.clerk_user_id)
        return {"data": _report_payload(cur, report_id)}


@router.get("/reports/{report_id}")
def get_report(report_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        report = _report_payload(cur, report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return {"data": report}


@router.get("/workspaces/{workspace_id}/workflows")
def list_workflows(workspace_id: str, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        params: list = [workspace_id]
        where = "w.workspace_id = %s"
        if project_id:
            where += " AND EXISTS (SELECT 1 FROM workflow_projects wp WHERE wp.workflow_id = w.id AND wp.project_id = %s)"
            params.append(project_id)
        return {
            "data": many(
                cur,
                f"""
                SELECT w.*,
                       count(DISTINCT wt.task_id) AS task_count,
                       count(DISTINCT wt.task_id) FILTER (WHERE t.status IN ('todo','doing','blocked')) AS open_task_count,
                       coalesce(json_agg(DISTINCT p.*) FILTER (WHERE p.id IS NOT NULL), '[]') AS projects,
                       coalesce(json_agg(DISTINCT pe.*) FILTER (WHERE pe.id IS NOT NULL), '[]') AS people
                FROM workflows w
                LEFT JOIN workflow_projects wp ON wp.workflow_id = w.id
                LEFT JOIN projects p ON p.id = wp.project_id
                LEFT JOIN workflow_people wpe ON wpe.workflow_id = w.id
                LEFT JOIN people pe ON pe.id = wpe.person_id
                LEFT JOIN workflow_tasks wt ON wt.workflow_id = w.id
                LEFT JOIN tasks t ON t.id = wt.task_id
                WHERE {where}
                GROUP BY w.id
                ORDER BY
                  CASE w.status WHEN 'active' THEN 1 WHEN 'draft' THEN 2 WHEN 'paused' THEN 3 ELSE 4 END,
                  w.updated_at DESC
                LIMIT 100
                """,
                tuple(params),
            )
        }


@router.post("/workspaces/{workspace_id}/workflows")
def create_workflow(workspace_id: str, payload: WorkflowCreate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
        _validate_project_ids(cur, workspace_id, payload.project_ids or [])
        _validate_person_ids(cur, workspace_id, payload.person_ids or [])
        _validate_note_ids(cur, workspace_id, payload.note_ids or [])
        _validate_task_ids(cur, workspace_id, payload.task_ids or [])
        cur.execute(
            """
            INSERT INTO workflows (workspace_id, name, description, status, created_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (workspace_id, lower(name))
            DO UPDATE
              SET description = COALESCE(EXCLUDED.description, workflows.description),
                  status = EXCLUDED.status,
                  updated_at = now()
            RETURNING *
            """,
            (workspace_id, payload.name.strip(), payload.description, payload.status, user.clerk_user_id),
        )
        workflow = dict(cur.fetchone())
        _link_many(cur, "workflow_projects", "workflow_id", "project_id", workflow["id"], workspace_id, payload.project_ids or [], user.clerk_user_id)
        for person_id in _dedupe(payload.person_ids or []):
            cur.execute(
                """
                INSERT INTO workflow_people (workflow_id, person_id, workspace_id, relation, linked_by)
                VALUES (%s, %s, %s, 'participant', %s)
                ON CONFLICT DO NOTHING
                """,
                (workflow["id"], person_id, workspace_id, user.clerk_user_id),
            )
        _link_many(cur, "workflow_notes", "workflow_id", "note_id", workflow["id"], workspace_id, payload.note_ids or [], user.clerk_user_id)
        position = 0
        for task_id in _dedupe(payload.task_ids or []):
            cur.execute(
                """
                INSERT INTO workflow_tasks (workflow_id, task_id, workspace_id, position, linked_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (workflow["id"], task_id, workspace_id, position, user.clerk_user_id),
            )
            position += 1
        return {"data": _workflow_payload(cur, str(workflow["id"]))}


@router.patch("/workflows/{workflow_id}")
def update_workflow(workflow_id: str, payload: WorkflowUpdate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        workflow = one(cur, "SELECT * FROM workflows WHERE id = %s", (workflow_id,))
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        workspace_id = str(workflow["workspace_id"])
        if payload.project_ids is not None:
            _validate_project_ids(cur, workspace_id, payload.project_ids)
        if payload.person_ids is not None:
            _validate_person_ids(cur, workspace_id, payload.person_ids)
        if payload.note_ids is not None:
            _validate_note_ids(cur, workspace_id, payload.note_ids)
        if payload.task_ids is not None:
            _validate_task_ids(cur, workspace_id, payload.task_ids)
        cur.execute(
            """
            UPDATE workflows
            SET name = %s,
                description = %s,
                status = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (
                payload.name.strip() if payload.name is not None else workflow["name"],
                payload.description if "description" in payload.model_fields_set else workflow.get("description"),
                payload.status or workflow["status"],
                workflow_id,
            ),
        )
        if payload.project_ids is not None:
            _replace_links(cur, "workflow_projects", "workflow_id", "project_id", workflow_id, workspace_id, payload.project_ids, user.clerk_user_id)
        if payload.person_ids is not None:
            cur.execute("DELETE FROM workflow_people WHERE workflow_id = %s", (workflow_id,))
            for person_id in _dedupe(payload.person_ids):
                cur.execute(
                    """
                    INSERT INTO workflow_people (workflow_id, person_id, workspace_id, relation, linked_by)
                    VALUES (%s, %s, %s, 'participant', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (workflow_id, person_id, workspace_id, user.clerk_user_id),
                )
        if payload.note_ids is not None:
            _replace_links(cur, "workflow_notes", "workflow_id", "note_id", workflow_id, workspace_id, payload.note_ids, user.clerk_user_id)
        if payload.task_ids is not None:
            cur.execute("DELETE FROM workflow_tasks WHERE workflow_id = %s", (workflow_id,))
            for position, task_id in enumerate(_dedupe(payload.task_ids)):
                cur.execute(
                    """
                    INSERT INTO workflow_tasks (workflow_id, task_id, workspace_id, position, linked_by)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (workflow_id, task_id, workspace_id, position, user.clerk_user_id),
                )
        return {"data": _workflow_payload(cur, workflow_id)}


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        workflow = _workflow_payload(cur, workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"data": workflow}


@router.get("/workspaces/{workspace_id}/memory-graph")
def memory_graph(workspace_id: str, project_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        _ensure_workspace_access(cur, workspace_id)
        if project_id:
            _validate_project_ids(cur, workspace_id, [project_id])
        notes = many(
            cur,
            """
            SELECT n.id, n.title, n.note_kind, coalesce(n.occurred_at, n.created_at) AS happened_at
            FROM notes n
            WHERE n.workspace_id = %s
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1 FROM note_projects np
                  WHERE np.note_id = n.id AND np.project_id = %s::uuid
                )
              )
            ORDER BY coalesce(n.occurred_at, n.created_at) DESC
            LIMIT 60
            """,
            (workspace_id, project_id, project_id),
        )
        tasks = many(
            cur,
            """
            SELECT DISTINCT t.id, t.title, t.status, t.due_at, t.created_at
            FROM tasks t
            LEFT JOIN task_projects tp ON tp.task_id = t.id
            WHERE t.workspace_id = %s
              AND (%s::uuid IS NULL OR tp.project_id = %s::uuid)
            ORDER BY t.created_at DESC
            LIMIT 80
            """,
            (workspace_id, project_id, project_id),
        )
        meetings = many(
            cur,
            """
            SELECT DISTINCT m.id, m.title, coalesce(m.occurred_at, m.created_at) AS happened_at
            FROM meetings m
            LEFT JOIN meeting_projects mp ON mp.meeting_id = m.id
            WHERE m.workspace_id = %s
              AND (%s::uuid IS NULL OR mp.project_id = %s::uuid)
            ORDER BY happened_at DESC
            LIMIT 60
            """,
            (workspace_id, project_id, project_id),
        )
        reports = many(
            cur,
            """
            SELECT DISTINCT r.id, r.title, r.status, r.created_at
            FROM reports r
            LEFT JOIN report_projects rp ON rp.report_id = r.id
            WHERE r.workspace_id = %s
              AND (%s::uuid IS NULL OR rp.project_id = %s::uuid)
            ORDER BY r.created_at DESC
            LIMIT 60
            """,
            (workspace_id, project_id, project_id),
        )
        workflows = many(
            cur,
            """
            SELECT DISTINCT w.id, w.name AS title, w.status, w.updated_at
            FROM workflows w
            LEFT JOIN workflow_projects wp ON wp.workflow_id = w.id
            WHERE w.workspace_id = %s
              AND (%s::uuid IS NULL OR wp.project_id = %s::uuid)
            ORDER BY w.updated_at DESC
            LIMIT 60
            """,
            (workspace_id, project_id, project_id),
        )
        companies = many(
            cur,
            """
            SELECT DISTINCT c.id, c.name AS title, c.domain, c.updated_at
            FROM companies c
            LEFT JOIN company_projects cp ON cp.company_id = c.id
            WHERE c.workspace_id = %s
              AND (%s::uuid IS NULL OR cp.project_id = %s::uuid)
            ORDER BY title
            LIMIT 60
            """,
            (workspace_id, project_id, project_id),
        )
        projects = many(
            cur,
            """
            SELECT p.id, p.name AS title, p.color_hex, p.kind
            FROM projects p
            WHERE p.workspace_id = %s
              AND p.kind <> 'personal'
              AND (%s::uuid IS NULL OR p.id = %s::uuid)
            ORDER BY p.kind, p.name
            LIMIT 60
            """,
            (workspace_id, project_id, project_id),
        )
        note_ids = [str(note["id"]) for note in notes]
        task_ids = [str(task["id"]) for task in tasks]
        meeting_ids = [str(meeting["id"]) for meeting in meetings]
        report_ids = [str(report["id"]) for report in reports]
        workflow_ids = [str(workflow["id"]) for workflow in workflows]
        company_ids = [str(company["id"]) for company in companies]
        project_ids = [str(project["id"]) for project in projects]
        people = many(
            cur,
            """
            SELECT DISTINCT p.id, p.name AS title, p.company
            FROM people p
            WHERE p.workspace_id = %s
              AND (
                %s::uuid IS NULL
                OR EXISTS (
                  SELECT 1
                  FROM note_people_links npl
                  JOIN note_projects np ON np.note_id = npl.note_id
                  WHERE npl.person_id = p.id
                    AND npl.state IN ('confirmed','auto_linked')
                    AND np.project_id = %s::uuid
                )
                OR EXISTS (
                  SELECT 1
                  FROM task_people tp
                  JOIN task_projects tpr ON tpr.task_id = tp.task_id
                  WHERE tp.person_id = p.id AND tpr.project_id = %s::uuid
                )
                OR EXISTS (
                  SELECT 1
                  FROM meeting_people mp
                  JOIN meeting_projects mpr ON mpr.meeting_id = mp.meeting_id
                  WHERE mp.person_id = p.id AND mpr.project_id = %s::uuid
                )
                OR EXISTS (
                  SELECT 1
                  FROM report_people rp
                  JOIN report_projects rpr ON rpr.report_id = rp.report_id
                  WHERE rp.person_id = p.id AND rpr.project_id = %s::uuid
                )
                OR EXISTS (
                  SELECT 1
                  FROM workflow_people wp
                  JOIN workflow_projects wpr ON wpr.workflow_id = wp.workflow_id
                  WHERE wp.person_id = p.id AND wpr.project_id = %s::uuid
                )
                OR EXISTS (
                  SELECT 1
                  FROM company_people cp
                  JOIN company_projects cpr ON cpr.company_id = cp.company_id
                  WHERE cp.person_id = p.id AND cpr.project_id = %s::uuid
                )
              )
            ORDER BY p.name
            LIMIT 80
            """,
            (workspace_id, project_id, project_id, project_id, project_id, project_id, project_id, project_id),
        )
        person_ids = [str(person["id"]) for person in people]
        edges = many(
            cur,
            """
            SELECT 'note' AS from_kind, note_id::text AS from_id, 'person' AS to_kind, person_id::text AS to_id, 'mentions' AS relation
            FROM note_people_links
            WHERE note_id = ANY(%s::uuid[]) AND person_id = ANY(%s::uuid[]) AND state IN ('confirmed','auto_linked')
            UNION ALL
            SELECT 'note', note_id::text, 'project', project_id::text, 'filed_in'
            FROM note_projects
            WHERE note_id = ANY(%s::uuid[]) AND project_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'task', task_id::text, 'note', note_id::text, 'sourced_from'
            FROM task_notes
            WHERE task_id = ANY(%s::uuid[]) AND note_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'task', task_id::text, 'person', person_id::text, relation
            FROM task_people
            WHERE task_id = ANY(%s::uuid[]) AND person_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'task', task_id::text, 'project', project_id::text, 'filed_in'
            FROM task_projects
            WHERE task_id = ANY(%s::uuid[]) AND project_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'meeting', meeting_id::text, 'note', note_id::text, 'sourced_from'
            FROM meeting_notes
            WHERE meeting_id = ANY(%s::uuid[]) AND note_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'meeting', meeting_id::text, 'person', person_id::text, attendance_status
            FROM meeting_people
            WHERE meeting_id = ANY(%s::uuid[]) AND person_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'meeting', meeting_id::text, 'project', project_id::text, 'filed_in'
            FROM meeting_projects
            WHERE meeting_id = ANY(%s::uuid[]) AND project_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'report', report_id::text, 'note', note_id::text, 'sourced_from'
            FROM report_notes
            WHERE report_id = ANY(%s::uuid[]) AND note_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'report', report_id::text, 'person', person_id::text, 'mentions'
            FROM report_people
            WHERE report_id = ANY(%s::uuid[]) AND person_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'report', report_id::text, 'project', project_id::text, 'filed_in'
            FROM report_projects
            WHERE report_id = ANY(%s::uuid[]) AND project_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'report', report_id::text, 'task', task_id::text, 'includes'
            FROM report_tasks
            WHERE report_id = ANY(%s::uuid[]) AND task_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'report', report_id::text, 'company', company_id::text, 'covers'
            FROM report_companies
            WHERE report_id = ANY(%s::uuid[]) AND company_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'workflow', workflow_id::text, 'note', note_id::text, 'sourced_from'
            FROM workflow_notes
            WHERE workflow_id = ANY(%s::uuid[]) AND note_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'workflow', workflow_id::text, 'task', task_id::text, 'contains'
            FROM workflow_tasks
            WHERE workflow_id = ANY(%s::uuid[]) AND task_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'workflow', workflow_id::text, 'person', person_id::text, relation
            FROM workflow_people
            WHERE workflow_id = ANY(%s::uuid[]) AND person_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'workflow', workflow_id::text, 'project', project_id::text, 'runs_in'
            FROM workflow_projects
            WHERE workflow_id = ANY(%s::uuid[]) AND project_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'company', company_id::text, 'note', note_id::text, 'sourced_from'
            FROM company_notes
            WHERE company_id = ANY(%s::uuid[]) AND note_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'company', company_id::text, 'person', person_id::text, 'associated_with'
            FROM company_people
            WHERE company_id = ANY(%s::uuid[]) AND person_id = ANY(%s::uuid[])
            UNION ALL
            SELECT 'company', company_id::text, 'project', project_id::text, 'works_on'
            FROM company_projects
            WHERE company_id = ANY(%s::uuid[]) AND project_id = ANY(%s::uuid[])
            """,
            (
                note_ids, person_ids,
                note_ids, project_ids,
                task_ids, note_ids,
                task_ids, person_ids,
                task_ids, project_ids,
                meeting_ids, note_ids,
                meeting_ids, person_ids,
                meeting_ids, project_ids,
                report_ids, note_ids,
                report_ids, person_ids,
                report_ids, project_ids,
                report_ids, task_ids,
                report_ids, company_ids,
                workflow_ids, note_ids,
                workflow_ids, task_ids,
                workflow_ids, person_ids,
                workflow_ids, project_ids,
                company_ids, note_ids,
                company_ids, person_ids,
                company_ids, project_ids,
            ),
        )
        nodes = []
        for kind, rows in (
            ("note", notes),
            ("person", people),
            ("project", projects),
            ("task", tasks),
            ("meeting", meetings),
            ("report", reports),
            ("workflow", workflows),
            ("company", companies),
        ):
            nodes.extend({**row, "kind": kind} for row in rows)
        return {"data": {"nodes": nodes, "edges": edges}}


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
        meetings = many(
            cur,
            """
            SELECT m.title, m.summary, coalesce(m.occurred_at, m.created_at) AS sort_at
            FROM meetings m
            JOIN meeting_projects mp ON mp.meeting_id = m.id
            WHERE mp.project_id = %s
            ORDER BY coalesce(m.occurred_at, m.created_at) DESC
            LIMIT 5
            """,
            (project_id,),
        )
        reports = many(
            cur,
            """
            SELECT r.title, r.status, r.created_at
            FROM reports r
            JOIN report_projects rp ON rp.report_id = r.id
            WHERE rp.project_id = %s
            ORDER BY r.created_at DESC
            LIMIT 5
            """,
            (project_id,),
        )
        return {"data": build_project_summary(project, notes, tasks, meetings, reports)}


@router.post("/projects/{project_id}/reports/generate")
def generate_project_memory_report(project_id: str, payload: ProjectReportGenerateRequest, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        project = _load_reportable_project(cur, project_id)
        workspace_id = str(project["workspace_id"])
        notes = many(
            cur,
            """
            SELECT n.id, n.title, n.body, n.note_kind, n.occurred_at, n.created_at
            FROM notes n
            JOIN note_projects np ON np.note_id = n.id
            WHERE np.project_id = %s
            ORDER BY coalesce(n.occurred_at, n.created_at) DESC, n.id
            LIMIT 40
            """,
            (project_id,),
        )
        tasks = many(
            cur,
            """
            SELECT t.id, t.title, t.description, t.status, t.priority, t.due_at, t.created_at
            FROM tasks t
            JOIN task_projects tp ON tp.task_id = t.id
            WHERE tp.project_id = %s
              AND t.status <> 'archived'
            ORDER BY
              CASE t.status WHEN 'blocked' THEN 1 WHEN 'doing' THEN 2 WHEN 'todo' THEN 3 WHEN 'done' THEN 4 ELSE 5 END,
              t.priority,
              t.due_at NULLS LAST,
              t.created_at DESC
            LIMIT 60
            """,
            (project_id,),
        )
        meetings = many(
            cur,
            """
            SELECT m.id, m.title, m.summary, m.location, m.occurred_at, m.created_at
            FROM meetings m
            JOIN meeting_projects mp ON mp.meeting_id = m.id
            WHERE mp.project_id = %s
            ORDER BY coalesce(m.occurred_at, m.created_at) DESC, m.id
            LIMIT 25
            """,
            (project_id,),
        )
        prior_reports = many(
            cur,
            """
            SELECT r.id, r.title, r.body, r.status, r.created_at
            FROM reports r
            JOIN report_projects rp ON rp.report_id = r.id
            WHERE rp.project_id = %s
            ORDER BY r.created_at DESC, r.id
            LIMIT 10
            """,
            (project_id,),
        )
        people = many(
            cur,
            """
            SELECT DISTINCT p.id, p.name, p.company, p.role, p.email
            FROM people p
            LEFT JOIN note_people_links npl ON npl.person_id = p.id
            LEFT JOIN note_projects np ON np.note_id = npl.note_id
            LEFT JOIN task_people tp ON tp.person_id = p.id
            LEFT JOIN task_projects tpr ON tpr.task_id = tp.task_id
            LEFT JOIN meeting_people mp ON mp.person_id = p.id
            LEFT JOIN meeting_projects mpr ON mpr.meeting_id = mp.meeting_id
            WHERE p.workspace_id = %s
              AND (
                np.project_id = %s
                OR tpr.project_id = %s
                OR mpr.project_id = %s
              )
            ORDER BY p.name
            LIMIT 40
            """,
            (workspace_id, project_id, project_id, project_id),
        )
        companies = many(
            cur,
            """
            SELECT DISTINCT c.id, c.name, c.domain, c.description
            FROM companies c
            LEFT JOIN company_projects cp ON cp.company_id = c.id
            LEFT JOIN company_people cpe ON cpe.company_id = c.id
            LEFT JOIN people p ON p.id = cpe.person_id
            LEFT JOIN note_people_links npl ON npl.person_id = p.id
            LEFT JOIN note_projects np ON np.note_id = npl.note_id
            WHERE c.workspace_id = %s
              AND (cp.project_id = %s OR np.project_id = %s)
            ORDER BY c.name
            LIMIT 40
            """,
            (workspace_id, project_id, project_id),
        )

    notes = _dedupe_source_rows(notes)
    tasks = _dedupe_source_rows(tasks)
    meetings = _dedupe_source_rows(meetings)
    prior_reports = _dedupe_source_rows(prior_reports)
    people = _dedupe_source_rows(people)
    companies = _dedupe_source_rows(companies)
    if not any((notes, tasks, meetings, prior_reports)):
        raise HTTPException(
            status_code=422,
            detail="Project needs notes, tasks, meetings, or prior reports before generating a report",
        )

    project_context = {**project, "people": people, "companies": companies}
    generated = asyncio.run(generate_project_report(project_context, notes, tasks, meetings, prior_reports, payload.variant))
    title = (payload.title or generated.get("title") or f"{project.get('name') or 'Project'} report").strip()[:240]
    body = str(generated.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=502, detail="Report generation returned an empty body")

    project_ids = [project_id]
    note_ids = _source_ids(notes)
    task_ids = _source_ids(tasks)
    meeting_ids = _source_ids(meetings)
    prior_report_ids = _source_ids(prior_reports)
    person_ids = _source_ids(people)
    company_ids = _source_ids(companies)
    with transaction(user.clerk_user_id) as cur:
        project = _load_reportable_project(cur, project_id)
        workspace_id = str(project["workspace_id"])
        cur.execute(
            """
            INSERT INTO reports (workspace_id, title, body, status, created_by)
            VALUES (%s, %s, %s, 'draft', %s)
            RETURNING *
            """,
            (workspace_id, title, body, user.clerk_user_id),
        )
        report = dict(cur.fetchone())
        report_id = str(report["id"])
        _link_many(cur, "report_projects", "report_id", "project_id", report_id, workspace_id, project_ids, user.clerk_user_id)
        _link_many(cur, "report_notes", "report_id", "note_id", report_id, workspace_id, note_ids, user.clerk_user_id)
        _link_many(cur, "report_tasks", "report_id", "task_id", report_id, workspace_id, task_ids, user.clerk_user_id)
        _link_many(cur, "report_people", "report_id", "person_id", report_id, workspace_id, person_ids, user.clerk_user_id)
        _link_many(cur, "report_companies", "report_id", "company_id", report_id, workspace_id, company_ids, user.clerk_user_id)
        created = _report_payload(cur, report_id)
        if created is not None:
            source_counts = {
                "projects": len(project_ids),
                "notes": len(note_ids),
                "tasks": len(task_ids),
                "meetings": len(meeting_ids),
                "reports": len(prior_report_ids),
                "people": len(person_ids),
                "companies": len(company_ids),
            }
            source_counts["total"] = sum(source_counts.values())
            created["generation_confidence"] = generated.get("confidence")
            created["source_counts"] = source_counts
        return {"data": created}


def _load_reportable_project(cur, project_id: str) -> dict:
    project = one(cur, "SELECT * FROM projects WHERE id = %s", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    access = one(cur, "SELECT can_access_project(%s::uuid) AS allowed", (project_id,))
    if not access or not access.get("allowed"):
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("kind") == "personal":
        raise HTTPException(status_code=403, detail="Personal projects cannot generate shareable reports")
    return project


def _dedupe_source_rows(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped = []
    for row in rows:
        row_id = row.get("id")
        if row_id is None:
            continue
        key = str(row_id)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _source_ids(rows: list[dict]) -> list[str]:
    return [str(row["id"]) for row in rows]


def build_project_summary(
    project: dict,
    notes: list[dict],
    tasks: list[dict],
    meetings: list[dict] | None = None,
    reports: list[dict] | None = None,
) -> dict:
    meetings = meetings or []
    reports = reports or []
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
    if meetings:
        lines.append("Recent meetings/calls:")
        lines.extend(f"- {_display_note(meeting)}" for meeting in meetings[:3])
    if reports:
        lines.append("Reports:")
        lines.extend(f"- {report.get('title')}" for report in reports[:3])
    return {
        "project_id": project.get("id"),
        "project_name": project.get("name"),
        "task_counts": task_counts,
        "open_tasks": open_tasks,
        "recent_notes": recent_notes,
        "recent_meetings": [_display_note(meeting) for meeting in meetings[:5]],
        "recent_reports": [report.get("title") for report in reports[:5]],
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


def _validate_company_ids(cur, workspace_id: str, ids: list[str]) -> None:
    _validate_ids(cur, "companies", workspace_id, ids, "One or more companies are unavailable")


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
    task["reminders"] = many(cur, "SELECT * FROM task_reminders WHERE task_id = %s ORDER BY coalesce(snoozed_until, remind_at), created_at DESC", (task_id,))
    return task


def _task_reminder_payload(cur, reminder_id: str) -> dict | None:
    reminder = one(
        cur,
        """
        SELECT tr.*,
               t.title AS task_title,
               t.description AS task_description,
               t.status AS task_status,
               t.due_at,
               coalesce(tr.snoozed_until, tr.remind_at) AS attention_at
        FROM task_reminders tr
        JOIN tasks t ON t.id = tr.task_id
        WHERE tr.id = %s
        """,
        (reminder_id,),
    )
    if not reminder:
        return None
    reminder["projects"] = many(cur, "SELECT p.* FROM projects p JOIN task_projects tp ON tp.project_id = p.id WHERE tp.task_id = %s ORDER BY p.name", (reminder["task_id"],))
    reminder["people"] = many(cur, "SELECT p.*, tp.relation FROM people p JOIN task_people tp ON tp.person_id = p.id WHERE tp.task_id = %s ORDER BY p.name", (reminder["task_id"],))
    return reminder


def _company_payload(cur, company_id: str) -> dict | None:
    company = one(cur, "SELECT * FROM companies WHERE id = %s", (company_id,))
    if not company:
        return None
    company["people"] = many(cur, "SELECT p.*, cp.role FROM people p JOIN company_people cp ON cp.person_id = p.id WHERE cp.company_id = %s ORDER BY p.name", (company_id,))
    company["projects"] = many(cur, "SELECT p.* FROM projects p JOIN company_projects cp ON cp.project_id = p.id WHERE cp.company_id = %s ORDER BY p.name", (company_id,))
    company["notes"] = many(cur, "SELECT n.* FROM notes n JOIN company_notes cn ON cn.note_id = n.id WHERE cn.company_id = %s ORDER BY coalesce(n.occurred_at, n.created_at) DESC", (company_id,))
    return company


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
    report["companies"] = many(cur, "SELECT c.* FROM companies c JOIN report_companies rc ON rc.company_id = c.id WHERE rc.report_id = %s ORDER BY c.name", (report_id,))
    report["notes"] = many(cur, "SELECT n.* FROM notes n JOIN report_notes rn ON rn.note_id = n.id WHERE rn.report_id = %s ORDER BY coalesce(n.occurred_at, n.created_at) DESC", (report_id,))
    report["tasks"] = many(cur, "SELECT t.* FROM tasks t JOIN report_tasks rt ON rt.task_id = t.id WHERE rt.report_id = %s ORDER BY t.created_at DESC", (report_id,))
    return report


def _workflow_payload(cur, workflow_id: str) -> dict | None:
    workflow = one(cur, "SELECT * FROM workflows WHERE id = %s", (workflow_id,))
    if not workflow:
        return None
    workflow["projects"] = many(cur, "SELECT p.* FROM projects p JOIN workflow_projects wp ON wp.project_id = p.id WHERE wp.workflow_id = %s ORDER BY p.name", (workflow_id,))
    workflow["people"] = many(cur, "SELECT p.*, wp.relation FROM people p JOIN workflow_people wp ON wp.person_id = p.id WHERE wp.workflow_id = %s ORDER BY p.name", (workflow_id,))
    workflow["notes"] = many(cur, "SELECT n.* FROM notes n JOIN workflow_notes wn ON wn.note_id = n.id WHERE wn.workflow_id = %s ORDER BY coalesce(n.occurred_at, n.created_at) DESC", (workflow_id,))
    workflow["tasks"] = many(cur, "SELECT t.* FROM tasks t JOIN workflow_tasks wt ON wt.task_id = t.id WHERE wt.workflow_id = %s ORDER BY wt.position, t.created_at DESC", (workflow_id,))
    return workflow


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
