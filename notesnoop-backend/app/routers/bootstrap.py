from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..schemas import BootstrapRequest, PersonCreate, ProjectCreate, ProjectInviteCreate, WorkspaceSettingsUpdate
from ..services import accept_pending_project_invites, bootstrap_workspace, get_bootstrap_state, normalize_email, upsert_user_profile


router = APIRouter(prefix="/api", tags=["bootstrap"])


@router.post("/bootstrap")
def bootstrap(payload: BootstrapRequest, user: CurrentUser = Depends(current_user)):
    return {"data": bootstrap_workspace(user, payload)}


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        upsert_user_profile(cur, user)
        accepted_invites = accept_pending_project_invites(cur, user)
        membership = one(
            cur,
            """
            SELECT workspace_id
            FROM workspace_members
            WHERE clerk_user_id = %s
            ORDER BY joined_at
            LIMIT 1
            """,
            (user.clerk_user_id,),
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
            INSERT INTO people (workspace_id, name, company, details, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (workspace_id, payload.name.strip(), payload.company, payload.details, user.clerk_user_id),
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
        return {"data": dict(cur.fetchone())}
