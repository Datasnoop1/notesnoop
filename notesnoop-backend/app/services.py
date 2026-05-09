from __future__ import annotations

import re

import httpx
from fastapi import HTTPException

from .auth import CurrentUser
from .config import get_settings
from .db import many, one, transaction
from .schemas import BootstrapRequest


def derive_title(body: str, title: str | None) -> tuple[str, bool]:
    if title and title.strip():
        return title.strip()[:200], False
    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if not first:
        return "[Untitled note]", True
    return first[:80], True


def inbound_address_for(user_id: str) -> str:
    local = re.sub(r"[^a-z0-9]+", "-", user_id.lower()).strip("-") or "user"
    return f"{local[:48]}@{get_settings().inbound_domain}"


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    return email.strip().lower() or None


def project_invite_url(workspace_id: str, project_id: str) -> str:
    return f"{get_settings().frontend_base_url}/?workspace_id={workspace_id}&project_id={project_id}"


def send_project_invite_email(email: str, project_name: str, inviter_name: str | None, accept_url: str) -> dict:
    settings = get_settings()
    payload = {
        "From": settings.postmark_from,
        "To": email,
        "Subject": f"Join {project_name} in NoteSnoop",
        "TextBody": (
            f"{inviter_name or 'A teammate'} invited you to collaborate on {project_name} in NoteSnoop.\n\n"
            f"Open the project: {accept_url}"
        ),
        "HtmlBody": (
            f"<p>{inviter_name or 'A teammate'} invited you to collaborate on <strong>{project_name}</strong> in NoteSnoop.</p>"
            f'<p><a href="{accept_url}">Open the project</a></p>'
        ),
        "MessageStream": settings.postmark_message_stream,
    }
    if settings.postmark_dry_run:
        return {"sent": True, "dry_run": True, "postmark_payload": payload}
    if not settings.postmark_server_token:
        return {"sent": False, "dry_run": False, "reason": "postmark_not_configured", "postmark_payload": payload}
    try:
        response = httpx.post(
            "https://api.postmarkapp.com/email",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": settings.postmark_server_token,
            },
            json=payload,
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return {"sent": False, "dry_run": False, "reason": str(exc), "postmark_status": status}
    return {"sent": True, "dry_run": False, "postmark_response": response.json()}


def upsert_user_profile(cur, user: CurrentUser, timezone: str = "UTC") -> None:
    cur.execute(
        """
        INSERT INTO user_profiles (clerk_user_id, email, display_name, avatar_url, timezone)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (clerk_user_id) DO UPDATE
          SET email = COALESCE(EXCLUDED.email, user_profiles.email),
              display_name = COALESCE(EXCLUDED.display_name, user_profiles.display_name),
              avatar_url = COALESCE(EXCLUDED.avatar_url, user_profiles.avatar_url),
              timezone = EXCLUDED.timezone
        """,
        (
            user.clerk_user_id,
            normalize_email(user.email),
            user.display_name,
            user.avatar_url,
            timezone,
        ),
    )


def accept_pending_project_invites(cur, user: CurrentUser) -> list[dict]:
    email = normalize_email(user.email)
    if not email:
        return []
    invites = many(
        cur,
        """
        SELECT *
        FROM project_invites
        WHERE status = 'pending'
          AND lower(email) = %s
        ORDER BY created_at
        """,
        (email,),
    )
    accepted: list[dict] = []
    for invite in invites:
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'member')
            ON CONFLICT DO NOTHING
            """,
            (invite["workspace_id"], user.clerk_user_id),
        )
        workspace = one(cur, "SELECT inbox_mode FROM workspaces WHERE id = %s", (invite["workspace_id"],))
        ensure_member_default_projects(
            cur,
            str(invite["workspace_id"]),
            user.clerk_user_id,
            workspace["inbox_mode"] if workspace else "per_user_private",
        )
        cur.execute(
            """
            INSERT INTO project_members (project_id, clerk_user_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (invite["project_id"], user.clerk_user_id),
        )
        cur.execute(
            """
            UPDATE project_invites
            SET status = 'accepted',
                accepted_by = %s,
                accepted_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (user.clerk_user_id, invite["id"]),
        )
        accepted.append(dict(cur.fetchone()))
    return accepted


def ensure_member_default_projects(cur, workspace_id: str, user_id: str, inbox_mode: str) -> None:
    defaults = [("Personal", "personal", "#7c3aed", False)]
    if inbox_mode == "shared":
        shared_inbox = one(
            cur,
            "SELECT id FROM projects WHERE workspace_id = %s AND kind = 'inbox' AND shared = TRUE LIMIT 1",
            (workspace_id,),
        )
        if shared_inbox:
            cur.execute(
                "INSERT INTO project_members (project_id, clerk_user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (shared_inbox["id"], user_id),
            )
        else:
            defaults.append(("Inbox", "inbox", "#0f766e", True))
    else:
        defaults.append(("Inbox", "inbox", "#0f766e", False))

    for name, kind, color, shared in defaults:
        existing = one(
            cur,
            """
            SELECT id
            FROM projects
            WHERE workspace_id = %s
              AND kind = %s
              AND created_by = %s
            LIMIT 1
            """,
            (workspace_id, kind, user_id),
        )
        if existing:
            project_id = existing["id"]
        else:
            cur.execute(
                """
                INSERT INTO projects (workspace_id, name, kind, color_hex, shared, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (workspace_id, name, kind, color, shared, user_id),
            )
            project_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO project_members (project_id, clerk_user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (project_id, user_id),
        )


def _consume_bucket(cur, key: str, capacity: float, refill_per_second: float) -> tuple[bool, int]:
    cur.execute(
        """
        INSERT INTO rate_limit_buckets (key, tokens, last_refill)
        VALUES (%s, %s, now())
        ON CONFLICT (key) DO NOTHING
        """,
        (key, capacity),
    )
    row = one(
        cur,
        """
        SELECT tokens,
               EXTRACT(EPOCH FROM (now() - last_refill)) AS elapsed
        FROM rate_limit_buckets
        WHERE key = %s
        FOR UPDATE
        """,
        (key,),
    )
    tokens = min(capacity, float(row["tokens"]) + float(row["elapsed"]) * refill_per_second)
    if tokens < 1.0:
        retry_after = max(1, int((1.0 - tokens) / refill_per_second))
        cur.execute(
            "UPDATE rate_limit_buckets SET tokens = %s, last_refill = now() WHERE key = %s",
            (tokens, key),
        )
        return False, retry_after
    cur.execute(
        "UPDATE rate_limit_buckets SET tokens = %s, last_refill = now() WHERE key = %s",
        (tokens - 1.0, key),
    )
    return True, 0


def consume_ai_quota(cur, workspace_id: str, user_id: str) -> tuple[bool, int]:
    user_ok, user_retry = _consume_bucket(cur, f"user:{user_id}:ai", 10.0, 5.0 / 60.0)
    workspace_ok, workspace_retry = _consume_bucket(cur, f"workspace:{workspace_id}:ai", 60.0, 30.0 / 60.0)
    if user_ok and workspace_ok:
        return True, 0
    return False, max(user_retry, workspace_retry, 1)


def enqueue_ai_if_allowed(cur, workspace_id: str, note_id: str, user_id: str, project_ids: list[str]) -> bool:
    row = one(
        cur,
        """
        SELECT w.ai_mode,
               bool_or(p.kind = 'personal') AS has_personal,
               bool_or(p.ai_mode = 'manual') AS has_manual_project
        FROM workspaces w
        JOIN projects p ON p.workspace_id = w.id
        WHERE w.id = %s AND p.id = ANY(%s::uuid[])
        GROUP BY w.ai_mode
        """,
        (workspace_id, project_ids),
    )
    if not row or row["ai_mode"] != "on" or row["has_personal"] or row["has_manual_project"]:
        cur.execute(
            "UPDATE notes SET ai_processing_status = 'skipped' WHERE id = %s",
            (note_id,),
        )
        return False
    ok, _retry_after = consume_ai_quota(cur, workspace_id, user_id)
    if not ok:
        return False
    cur.execute(
        """
        INSERT INTO ai_jobs (workspace_id, kind, note_id, target_user_id, priority, idempotency_key)
        VALUES (%s, 'extract', %s, %s, 10, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (workspace_id, note_id, user_id, f"note:{note_id}:extract"),
    )
    cur.execute("UPDATE notes SET ai_processing_status = 'processing' WHERE id = %s", (note_id,))
    return True


def bootstrap_workspace(user: CurrentUser, payload: BootstrapRequest) -> dict:
    settings = get_settings()
    workspace_name = payload.workspace_name or "My NoteSnoop workspace"
    with transaction(user.clerk_user_id) as cur:
        upsert_user_profile(cur, user, payload.timezone)
        accept_pending_project_invites(cur, user)
        existing = one(
            cur,
            """
            SELECT w.id
            FROM workspaces w
            JOIN workspace_members wm ON wm.workspace_id = w.id
            WHERE wm.clerk_user_id = %s
            ORDER BY w.created_at
            LIMIT 1
            """,
            (user.clerk_user_id,),
        )
        if existing:
            return get_bootstrap_state(cur, user.clerk_user_id, str(existing["id"]))

        cur.execute(
            """
            INSERT INTO workspaces (clerk_org_id, name, inbox_mode)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (f"personal:{user.clerk_user_id}", workspace_name, payload.inbox_mode),
        )
        workspace_id = str(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role, email_ai_mode, morning_briefing_optin)
            VALUES (%s, %s, 'admin', %s, %s)
            """,
            (workspace_id, user.clerk_user_id, settings.email_ai_default, payload.morning_briefing_optin),
        )
        default_projects = [
            ("Personal", "personal", "#7c3aed", False),
            ("Inbox", "inbox", "#0f766e", payload.inbox_mode == "shared"),
        ]
        for name, kind, color, shared in default_projects:
            cur.execute(
                """
                INSERT INTO projects (workspace_id, name, kind, color_hex, shared, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (workspace_id, name, kind, color, shared, user.clerk_user_id),
            )
            project_id = str(cur.fetchone()["id"])
            cur.execute(
                "INSERT INTO project_members (project_id, clerk_user_id) VALUES (%s, %s)",
                (project_id, user.clerk_user_id),
            )
        cur.execute(
            """
            INSERT INTO people (workspace_id, name, clerk_user_id, created_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (workspace_id, user.display_name or "You", user.clerk_user_id, user.clerk_user_id),
        )
        cur.execute(
            """
            INSERT INTO inbound_email_addresses (clerk_user_id, address)
            VALUES (%s, %s)
            ON CONFLICT (address) DO NOTHING
            """,
            (user.clerk_user_id, inbound_address_for(user.clerk_user_id)),
        )
        return get_bootstrap_state(cur, user.clerk_user_id, workspace_id)


def get_bootstrap_state(cur, user_id: str, workspace_id: str) -> dict:
    workspace = one(
        cur,
        """
        SELECT w.*, wm.role, wm.email_ai_mode, wm.morning_briefing_optin
        FROM workspaces w
        JOIN workspace_members wm ON wm.workspace_id = w.id
        WHERE w.id = %s AND wm.clerk_user_id = %s
        """,
        (workspace_id, user_id),
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    projects = many(cur, "SELECT * FROM projects WHERE workspace_id = %s ORDER BY kind, created_at", (workspace_id,))
    people = many(cur, "SELECT * FROM people WHERE workspace_id = %s ORDER BY created_at", (workspace_id,))
    workspaces = many(
        cur,
        """
        SELECT w.id, w.name, wm.role, wm.joined_at
        FROM workspaces w
        JOIN workspace_members wm ON wm.workspace_id = w.id
        WHERE wm.clerk_user_id = %s
        ORDER BY wm.joined_at DESC
        """,
        (user_id,),
    )
    inbound = one(cur, "SELECT address FROM inbound_email_addresses WHERE clerk_user_id = %s ORDER BY created_at LIMIT 1", (user_id,))
    return {
        "workspace": workspace,
        "workspaces": workspaces,
        "projects": projects,
        "people": people,
        "inbound_address": inbound["address"] if inbound else inbound_address_for(user_id),
    }
