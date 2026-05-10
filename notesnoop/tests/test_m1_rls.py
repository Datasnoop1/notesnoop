from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("NOTESNOOP_TEST_DATABASE_URL") or os.getenv("MIGRATE_DATABASE_URL")


pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NOTESNOOP_TEST_DATABASE_URL or MIGRATE_DATABASE_URL is required",
)


def _run_migrations() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "notesnoop" / "migrate.py"), "up", "--target=ci"],
        cwd=ROOT,
        env={**os.environ, "NOTESNOOP_TEST_DATABASE_URL": DATABASE_URL or ""},
        check=True,
    )


@pytest.fixture(scope="module")
def conn():
    _run_migrations()
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.close()


def _fetch_ids(cur, sql: str, params: tuple = ()) -> list[str]:
    cur.execute(sql, params)
    values = []
    for row in cur.fetchall():
        if isinstance(row, dict):
            values.append(str(next(iter(row.values()))))
        else:
            values.append(str(row[0]))
    return values


def _as_user(cur, user_id: str) -> None:
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE notesnoop_app")
    cur.execute("SET notesnoop.current_user_id = %s", (user_id,))


def _test_vector(value: float = 0.001) -> str:
    return "[" + ",".join([str(value)] * 1024) + "]"


def test_rls_workspace_project_and_personal_isolation(conn):
    suffix = uuid.uuid4().hex[:8]
    u_admin = f"u_admin_{suffix}"
    u_member = f"u_member_{suffix}"
    u_nonmember = f"u_nonmember_{suffix}"
    u_other = f"u_other_{suffix}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            """
            INSERT INTO user_profiles (clerk_user_id, email, display_name)
            VALUES
              (%s, 'admin@example.test', 'Admin'),
              (%s, 'member@example.test', 'Member'),
              (%s, 'nonmember@example.test', 'Nonmember'),
              (%s, 'other@example.test', 'Other')
            """,
            (u_admin, u_member, u_nonmember, u_other),
        )
        cur.execute(
            "INSERT INTO workspaces (clerk_org_id, name) VALUES (%s, 'Workspace A') RETURNING id",
            (f"org_a_{suffix}",),
        )
        ws_a = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO workspaces (clerk_org_id, name) VALUES (%s, 'Workspace B') RETURNING id",
            (f"org_b_{suffix}",),
        )
        ws_b = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES
              (%s, %s, 'admin'),
              (%s, %s, 'member'),
              (%s, %s, 'member'),
              (%s, %s, 'admin')
            """,
            (ws_a, u_admin, ws_a, u_member, ws_a, u_nonmember, ws_b, u_other),
        )
        cur.execute(
            "INSERT INTO projects (workspace_id, name, kind, created_by) VALUES (%s, 'Deal A', 'user', %s) RETURNING id",
            (ws_a, u_admin),
        )
        project_a = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO projects (workspace_id, name, kind, created_by) VALUES (%s, 'Secret Member', 'personal', %s) RETURNING id",
            (ws_a, u_member),
        )
        member_personal = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO projects (workspace_id, name, kind, created_by) VALUES (%s, 'Other', 'user', %s) RETURNING id",
            (ws_b, u_other),
        )
        project_b = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO project_members (project_id, clerk_user_id)
            VALUES (%s, %s), (%s, %s), (%s, %s), (%s, %s)
            """,
            (project_a, u_admin, project_a, u_member, member_personal, u_member, project_b, u_other),
        )
        cur.execute(
            "INSERT INTO notes (workspace_id, title, body, created_by) VALUES (%s, 'A', 'shared', %s) RETURNING id",
            (ws_a, u_admin),
        )
        note_a = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s)",
            (note_a, project_a, u_admin),
        )
        cur.execute(
            "INSERT INTO notes (workspace_id, title, body, created_by) VALUES (%s, 'P', 'personal', %s) RETURNING id",
            (ws_a, u_member),
        )
        note_personal = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s)",
            (note_personal, member_personal, u_member),
        )
        cur.execute(
            "INSERT INTO notes (workspace_id, title, body, created_by) VALUES (%s, 'B', 'other workspace', %s) RETURNING id",
            (ws_b, u_other),
        )
        note_b = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s)",
            (note_b, project_b, u_other),
        )
        for note_id, workspace_id, label in (
            (note_a, ws_a, "a"),
            (note_personal, ws_a, "personal"),
            (note_b, ws_b, "b"),
        ):
            cur.execute(
                """
                INSERT INTO embeddings (
                  note_id,
                  workspace_id,
                  embedding,
                  model_version,
                  provider,
                  embedding_dimension,
                  embedding_text_sha256
                )
                VALUES (%s, %s, %s::vector, 'qwen3-embedding:0.6b', 'lexical_hash', 1024, %s)
                """,
                (note_id, workspace_id, _test_vector(), f"hash-{label}-{suffix}"),
            )
        conn.commit()

        _as_user(cur, u_member)
        assert set(_fetch_ids(cur, "SELECT id FROM notes ORDER BY title")) == {
            str(note_a),
            str(note_personal),
        }
        assert set(_fetch_ids(cur, "SELECT note_id FROM embeddings ORDER BY note_id")) == {
            str(note_a),
            str(note_personal),
        }
        conn.commit()

        _as_user(cur, u_nonmember)
        assert _fetch_ids(cur, "SELECT id FROM notes ORDER BY title") == []
        assert _fetch_ids(cur, "SELECT note_id FROM embeddings ORDER BY note_id") == []
        conn.commit()

        _as_user(cur, u_admin)
        assert set(_fetch_ids(cur, "SELECT id FROM notes ORDER BY title")) == {str(note_a)}
        assert set(_fetch_ids(cur, "SELECT note_id FROM embeddings ORDER BY note_id")) == {str(note_a)}
        conn.commit()

        _as_user(cur, u_other)
        assert _fetch_ids(cur, "SELECT id FROM notes ORDER BY title") == [str(note_b)]
        assert _fetch_ids(cur, "SELECT note_id FROM embeddings ORDER BY note_id") == [str(note_b)]
        conn.commit()


def test_personal_project_mutual_exclusivity_trigger(conn):
    suffix = uuid.uuid4().hex[:8]
    user_id = f"u_personal_{suffix}"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            "INSERT INTO user_profiles (clerk_user_id) VALUES (%s)",
            (user_id,),
        )
        cur.execute(
            "INSERT INTO workspaces (clerk_org_id, name) VALUES (%s, 'Personal Trigger') RETURNING id",
            (f"org_personal_{suffix}",),
        )
        ws = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO workspace_members (workspace_id, clerk_user_id, role) VALUES (%s, %s, 'admin')",
            (ws, user_id),
        )
        cur.execute(
            "INSERT INTO projects (workspace_id, name, kind, created_by) VALUES (%s, 'Personal', 'personal', %s) RETURNING id",
            (ws, user_id),
        )
        personal = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO projects (workspace_id, name, kind, created_by) VALUES (%s, 'Deal', 'user', %s) RETURNING id",
            (ws, user_id),
        )
        deal = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO notes (workspace_id, body, created_by) VALUES (%s, 'private', %s) RETURNING id",
            (ws, user_id),
        )
        note = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s)",
            (note, personal, user_id),
        )
        with pytest.raises(psycopg2.Error):
            cur.execute(
                "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s)",
                (note, deal, user_id),
            )
        conn.rollback()


def test_workspace_scoped_tables_have_rls_policies(conn):
    expected = {
        "workspaces",
        "workspace_members",
        "projects",
        "project_members",
        "notes",
        "note_versions",
        "note_projects",
        "people",
        "note_people_links",
        "embeddings",
        "flags",
        "review_queue",
        "project_invites",
        "ai_jobs",
        "recently_accessed",
        "calibration_events",
        "person_merge_undos",
        "note_viewers",
        "companies",
        "meetings",
        "tasks",
        "workflows",
        "reports",
        "company_people",
        "company_projects",
        "company_notes",
        "meeting_people",
        "meeting_projects",
        "meeting_notes",
        "task_people",
        "task_projects",
        "task_notes",
        "task_reminders",
        "workflow_projects",
        "workflow_people",
        "workflow_notes",
        "workflow_tasks",
        "report_projects",
        "report_people",
        "report_notes",
        "report_tasks",
        "report_companies",
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_policy p ON p.polrelid = c.oid
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND c.relname = ANY(%s)
            GROUP BY c.oid, c.relname, c.relrowsecurity
            HAVING NOT c.relrowsecurity OR count(p.oid) = 0
            """,
            (list(expected),),
        )
        missing = {row[0] for row in cur.fetchall()}
    assert not missing
