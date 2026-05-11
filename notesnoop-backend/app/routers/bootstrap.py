from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..schemas import BootstrapRequest, PersonCreate, PersonUpdate, ProjectCreate, ProjectInviteCreate, ProjectUpdate, WorkspaceSettingsUpdate
from ..services import (
    accept_pending_project_invites,
    bootstrap_workspace,
    get_bootstrap_state,
    normalize_email,
    project_invite_url,
    send_project_invite_email,
    upsert_user_profile,
)


router = APIRouter(prefix="/api", tags=["bootstrap"])


@router.post("/bootstrap")
def bootstrap(payload: BootstrapRequest, user: CurrentUser = Depends(current_user)):
    return {"data": bootstrap_workspace(user, payload)}


@router.get("/me")
def me(workspace_id: str | None = None, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        upsert_user_profile(cur, user)
        accepted_invites = accept_pending_project_invites(cur, user)
        selected_workspace_id = workspace_id or (str(accepted_invites[-1]["workspace_id"]) if accepted_invites else None)
        membership = one(
            cur,
            """
            SELECT workspace_id
            FROM workspace_members
            WHERE clerk_user_id = %s
              AND (%s::uuid IS NULL OR workspace_id = %s::uuid)
            ORDER BY joined_at DESC
            LIMIT 1
            """,
            (user.clerk_user_id, selected_workspace_id, selected_workspace_id),
        )
        if not membership:
            return {"data": {"user": user.__dict__, "bootstrapped": False, "accepted_invites": accepted_invites}}
        state = get_bootstrap_state(cur, user.clerk_user_id, str(membership["workspace_id"]))
        return {"data": {"user": user.__dict__, "bootstrapped": True, "accepted_invites": accepted_invites, **state}}


@router.patch("/workspaces/{workspace_id}/settings")
def update_workspace_settings(
    workspace_id: str,
    payload: WorkspaceSettingsUpdate,
    user: CurrentUser = Depends(current_user),
):
    with transaction(user.clerk_user_id) as cur:
        if payload.ai_mode is not None:
            cur.execute(
                "UPDATE workspaces SET ai_mode = %s WHERE id = %s",
                (payload.ai_mode, workspace_id),
            )
        if payload.email_ai_mode is not None or payload.morning_briefing_optin is not None:
            cur.execute(
                """
                UPDATE workspace_members
                SET email_ai_mode = COALESCE(%s, email_ai_mode),
                    morning_briefing_optin = COALESCE(%s, morning_briefing_optin)
                WHERE workspace_id = %s AND clerk_user_id = %s
                """,
                (
                    payload.email_ai_mode,
                    payload.morning_briefing_optin,
                    workspace_id,
                    user.clerk_user_id,
                ),
            )
        return {"data": get_bootstrap_state(cur, user.clerk_user_id, workspace_id)}


@router.post("/workspaces/{workspace_id}/people")
def create_person(
    workspace_id: str,
    payload: PersonCreate,
    user: CurrentUser = Depends(current_user),
):
    with transaction(user.clerk_user_id) as cur:
        cur.execute(
            """
            INSERT INTO people (workspace_id, name, company, role, email, details, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (workspace_id, payload.name.strip(), payload.company, payload.role, payload.email, payload.details, user.clerk_user_id),
        )
        person = dict(cur.fetchone())
        if payload.company:
            cur.execute(
                """
                INSERT INTO companies (workspace_id, name, created_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (workspace_id, lower(name))
                DO UPDATE SET updated_at = now()
                RETURNING id
                """,
                (workspace_id, payload.company.strip(), user.clerk_user_id),
            )
            company = cur.fetchone()
            if company:
                cur.execute(
                    """
                    INSERT INTO company_people (company_id, person_id, workspace_id, role, linked_by)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (company["id"], person["id"], workspace_id, payload.role, user.clerk_user_id),
                )
        return {"data": person}


@router.patch("/people/{person_id}")
def update_person(person_id: str, payload: PersonUpdate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        person = one(cur, "SELECT * FROM people WHERE id = %s", (person_id,))
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        cur.execute(
            """
            UPDATE people
            SET name = %s,
                company = %s,
                role = %s,
                email = %s,
                details = %s
            WHERE id = %s
            RETURNING *
            """,
            (
                payload.name.strip() if payload.name is not None else person["name"],
                payload.company if "company" in payload.model_fields_set else person.get("company"),
                payload.role if "role" in payload.model_fields_set else person.get("role"),
                payload.email if "email" in payload.model_fields_set else person.get("email"),
                payload.details if "details" in payload.model_fields_set else person.get("details"),
                person_id,
            ),
        )
        return {"data": dict(cur.fetchone())}


@router.get("/workspaces/{workspace_id}/people")
def list_people(workspace_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        return {
            "data": many(
                cur,
                """
                SELECT p.*,
                       count(npl.note_id) FILTER (WHERE npl.state IN ('confirmed','auto_linked')) AS confirmed_note_count
                FROM people p
                LEFT JOIN note_people_links npl ON npl.person_id = p.id
                WHERE p.workspace_id = %s
                GROUP BY p.id
                ORDER BY lower(p.name)
                """,
                (workspace_id,),
            )
        }


@router.post("/workspaces/{workspace_id}/projects")
def create_project(
    workspace_id: str,
    payload: ProjectCreate,
    user: CurrentUser = Depends(current_user),
):
    with transaction(user.clerk_user_id) as cur:
        cur.execute(
            """
            INSERT INTO projects (workspace_id, name, color_hex, kind, ai_mode, shared, created_by)
            VALUES (%s, %s, %s, 'user', %s, FALSE, %s)
            RETURNING *
            """,
            (workspace_id, payload.name.strip(), payload.color_hex, payload.ai_mode, user.clerk_user_id),
        )
        project = dict(cur.fetchone())
        cur.execute(
            "INSERT INTO project_members (project_id, clerk_user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (project["id"], user.clerk_user_id),
        )
        return {"data": project}


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        project = one(cur, "SELECT * FROM projects WHERE id = %s", (project_id,))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project["kind"] in ("inbox", "personal") and payload.name is not None and payload.name.strip().lower() != project["name"].lower():
            raise HTTPException(status_code=400, detail="System projects cannot be renamed")
        if payload.status is not None and project["kind"] in ("inbox", "personal"):
            raise HTTPException(status_code=400, detail="System projects cannot be closed")
        prev_status = project.get("status") or "active"
        next_status = payload.status if payload.status is not None else prev_status
        is_close_transition = next_status == "closed" and prev_status != "closed"
        closed_at_sql = "now()" if is_close_transition else (
            "NULL" if next_status == "active" else "closed_at"
        )
        cur.execute(
            f"""
            UPDATE projects
            SET name = %s,
                color_hex = %s,
                ai_mode = %s,
                status = %s,
                closed_at = {closed_at_sql},
                description = %s
            WHERE id = %s
            RETURNING *
            """,
            (
                payload.name.strip() if payload.name is not None else project["name"],
                payload.color_hex if "color_hex" in payload.model_fields_set else project.get("color_hex"),
                payload.ai_mode if payload.ai_mode is not None else project.get("ai_mode"),
                next_status,
                payload.description if "description" in payload.model_fields_set else project.get("description"),
                project_id,
            ),
        )
        updated = dict(cur.fetchone())
        archived_task_count = 0
        if is_close_transition and payload.close_open_tasks:
            cur.execute(
                """
                UPDATE tasks
                SET status = 'archived'
                WHERE id IN (
                    SELECT t.id
                    FROM tasks t
                    JOIN task_projects tp ON tp.task_id = t.id AND tp.project_id = %s
                    WHERE t.status NOT IN ('done', 'archived')
                      AND NOT EXISTS (
                          SELECT 1
                          FROM task_projects tp2
                          JOIN projects p2 ON p2.id = tp2.project_id
                          WHERE tp2.task_id = t.id
                            AND tp2.project_id <> %s
                            AND coalesce(p2.status, 'active') = 'active'
                      )
                )
                RETURNING id
                """,
                (project_id, project_id),
            )
            archived_task_count = len(cur.fetchall())
        updated["archived_task_count"] = archived_task_count
        return {"data": updated}


@router.get("/workspaces/{workspace_id}/projects")
def list_projects(workspace_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        return {
            "data": many(
                cur,
                """
                SELECT p.*,
                       count(DISTINCT np.note_id) AS note_count,
                       max(n.created_at) AS last_note_at
                FROM projects p
                LEFT JOIN note_projects np ON np.project_id = p.id
                LEFT JOIN notes n ON n.id = np.note_id
                WHERE p.workspace_id = %s
                GROUP BY p.id
                ORDER BY p.kind, coalesce(max(n.created_at), p.created_at) DESC
                """,
                (workspace_id,),
            )
        }


@router.post("/projects/{project_id}/members/{member_user_id}")
def add_project_member(
    project_id: str,
    member_user_id: str,
    user: CurrentUser = Depends(current_user),
):
    with transaction(user.clerk_user_id) as cur:
        project = one(cur, "SELECT * FROM projects WHERE id = %s", (project_id,))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project["kind"] == "personal":
            raise HTTPException(status_code=422, detail="Personal projects cannot be shared")
        is_admin = one(
            cur,
            "SELECT 1 FROM workspace_members WHERE workspace_id = %s AND clerk_user_id = %s AND role = 'admin'",
            (project["workspace_id"], user.clerk_user_id),
        )
        if not is_admin and project["created_by"] != user.clerk_user_id:
            raise HTTPException(status_code=403, detail="Only workspace admins or the project creator can add members")
        member = one(cur, "SELECT clerk_user_id FROM user_profiles WHERE clerk_user_id = %s", (member_user_id,))
        if not member:
            raise HTTPException(status_code=422, detail="Invite this user by email first")
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'member')
            ON CONFLICT DO NOTHING
            """,
            (project["workspace_id"], member_user_id),
        )
        cur.execute(
            """
            INSERT INTO project_members (project_id, clerk_user_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (project_id, member_user_id),
        )
        cur.execute("UPDATE projects SET shared = TRUE WHERE id = %s", (project_id,))
        return {"data": {"project_id": project_id, "member_user_id": member_user_id}}


@router.post("/projects/{project_id}/invites")
def invite_project_member(
    project_id: str,
    payload: ProjectInviteCreate,
    user: CurrentUser = Depends(current_user),
):
    email = normalize_email(payload.email)
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email address is required")
    with transaction(user.clerk_user_id) as cur:
        project = one(cur, "SELECT * FROM projects WHERE id = %s", (project_id,))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project["kind"] == "personal":
            raise HTTPException(status_code=422, detail="Personal projects cannot be shared")
        is_admin = one(
            cur,
            "SELECT 1 FROM workspace_members WHERE workspace_id = %s AND clerk_user_id = %s AND role = 'admin'",
            (project["workspace_id"], user.clerk_user_id),
        )
        if not is_admin and project["created_by"] != user.clerk_user_id:
            raise HTTPException(status_code=403, detail="Only workspace admins or the project creator can invite people")

        cur.execute("UPDATE projects SET shared = TRUE WHERE id = %s", (project_id,))
        cur.execute(
            """
            INSERT INTO project_invites (workspace_id, project_id, email, display_name, invited_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (project_id, (lower(email))) WHERE status = 'pending'
            DO UPDATE SET display_name = EXCLUDED.display_name
            RETURNING *
            """,
            (
                project["workspace_id"],
                project_id,
                email,
                payload.display_name,
                user.clerk_user_id,
            ),
        )
        invite = dict(cur.fetchone())
    accept_url = project_invite_url(str(invite["workspace_id"]), str(project_id))
    delivery = send_project_invite_email(email, project["name"], user.display_name, accept_url)
    invite["accept_url"] = accept_url
    invite["delivery"] = delivery
    return {"data": invite}
