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


def test_base_note_links_reject_cross_workspace_targets(conn):
    suffix = uuid.uuid4().hex[:8]
    user_a = f"u_guard_a_{suffix}"
    user_b = f"u_guard_b_{suffix}"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            "INSERT INTO user_profiles (clerk_user_id) VALUES (%s), (%s)",
            (user_a, user_b),
        )
        cur.execute(
            "INSERT INTO workspaces (clerk_org_id, name) VALUES (%s, 'Guard A') RETURNING id",
            (f"org_guard_a_{suffix}",),
        )
        ws_a = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO workspaces (clerk_org_id, name) VALUES (%s, 'Guard B') RETURNING id",
            (f"org_guard_b_{suffix}",),
        )
        ws_b = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'admin'), (%s, %s, 'admin')
            """,
            (ws_a, user_a, ws_b, user_b),
        )
        cur.execute(
            "INSERT INTO notes (workspace_id, body, created_by) VALUES (%s, 'guard note', %s) RETURNING id",
            (ws_a, user_a),
        )
        note_a = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO projects (workspace_id, name, kind, created_by) VALUES (%s, 'Guard Project B', 'user', %s) RETURNING id",
            (ws_b, user_b),
        )
        project_b = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO people (workspace_id, name, created_by) VALUES (%s, 'Guard Person B', %s) RETURNING id",
            (ws_b, user_b),
        )
        person_b = cur.fetchone()["id"]

        cur.execute("SAVEPOINT note_project_guard")
        with pytest.raises(psycopg2.Error):
            cur.execute(
                "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s)",
                (note_a, project_b, user_a),
            )
        cur.execute("ROLLBACK TO SAVEPOINT note_project_guard")

        cur.execute("SAVEPOINT note_people_guard")
        with pytest.raises(psycopg2.Error):
            cur.execute(
                """
                INSERT INTO note_people_links (note_id, person_id, state, confidence, source, source_user_id)
                VALUES (%s, %s, 'confirmed', 1, 'user', %s)
                """,
                (note_a, person_b, user_a),
            )
        cur.execute("ROLLBACK TO SAVEPOINT note_people_guard")
        conn.commit()


def test_stale_shared_inbox_in_private_workspace_does_not_grant_note_access(conn):
    suffix = uuid.uuid4().hex[:8]
    owner = f"u_inbox_owner_{suffix}"
    member = f"u_inbox_member_{suffix}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            """
            INSERT INTO user_profiles (clerk_user_id, email, display_name)
            VALUES
              (%s, %s, 'Inbox Owner'),
              (%s, %s, 'Inbox Member')
            """,
            (owner, f"{owner}@example.test", member, f"{member}@example.test"),
        )
        cur.execute(
            """
            INSERT INTO workspaces (clerk_org_id, name, inbox_mode)
            VALUES (%s, 'Private Inbox RLS', 'per_user_private')
            RETURNING id
            """,
            (f"org_inbox_{suffix}",),
        )
        workspace_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'admin'), (%s, %s, 'member')
            """,
            (workspace_id, owner, workspace_id, member),
        )
        cur.execute(
            """
            INSERT INTO projects (workspace_id, name, kind, shared, created_by)
            VALUES (%s, 'Inbox', 'inbox', TRUE, %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        stale_shared_inbox = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO project_members (project_id, clerk_user_id)
            VALUES (%s, %s), (%s, %s)
            """,
            (stale_shared_inbox, owner, stale_shared_inbox, member),
        )
        cur.execute(
            """
            INSERT INTO notes (workspace_id, title, body, created_by)
            VALUES (%s, 'Stale shared inbox note', 'This should stay with the owner only.', %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        note_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO note_projects (note_id, project_id, linked_by)
            VALUES (%s, %s, %s)
            """,
            (note_id, stale_shared_inbox, owner),
        )
        conn.commit()

        _as_user(cur, member)
        assert _fetch_ids(cur, "SELECT id FROM projects WHERE id = %s", (stale_shared_inbox,)) == []
        assert _fetch_ids(cur, "SELECT id FROM notes WHERE id = %s", (note_id,)) == []
        conn.commit()


def test_shared_inbox_in_shared_workspace_grants_member_note_access(conn):
    suffix = uuid.uuid4().hex[:8]
    owner = f"u_shared_owner_{suffix}"
    member = f"u_shared_member_{suffix}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            """
            INSERT INTO user_profiles (clerk_user_id, email, display_name)
            VALUES
              (%s, %s, 'Shared Owner'),
              (%s, %s, 'Shared Member')
            """,
            (owner, f"{owner}@example.test", member, f"{member}@example.test"),
        )
        cur.execute(
            """
            INSERT INTO workspaces (clerk_org_id, name, inbox_mode)
            VALUES (%s, 'Shared Inbox RLS', 'shared')
            RETURNING id
            """,
            (f"org_shared_{suffix}",),
        )
        workspace_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'admin'), (%s, %s, 'member')
            """,
            (workspace_id, owner, workspace_id, member),
        )
        cur.execute(
            """
            INSERT INTO projects (workspace_id, name, kind, shared, created_by)
            VALUES (%s, 'Inbox', 'inbox', TRUE, %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        shared_inbox = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO notes (workspace_id, title, body, created_by)
            VALUES (%s, 'Shared inbox note', 'Members should see shared inbox notes.', %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        note_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO note_projects (note_id, project_id, linked_by)
            VALUES (%s, %s, %s)
            """,
            (note_id, shared_inbox, owner),
        )
        conn.commit()

        _as_user(cur, member)
        assert _fetch_ids(cur, "SELECT id FROM projects WHERE id = %s", (shared_inbox,)) == [str(shared_inbox)]
        assert _fetch_ids(cur, "SELECT id FROM notes WHERE id = %s", (note_id,)) == [str(note_id)]
        conn.commit()


def test_stale_private_inbox_in_shared_workspace_does_not_grant_access(conn):
    suffix = uuid.uuid4().hex[:8]
    owner = f"u_private_owner_{suffix}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            "INSERT INTO user_profiles (clerk_user_id, email, display_name) VALUES (%s, %s, 'Private Owner')",
            (owner, f"{owner}@example.test"),
        )
        cur.execute(
            """
            INSERT INTO workspaces (clerk_org_id, name, inbox_mode)
            VALUES (%s, 'Shared Workspace With Stale Private Inbox', 'shared')
            RETURNING id
            """,
            (f"org_private_{suffix}",),
        )
        workspace_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'admin')
            """,
            (workspace_id, owner),
        )
        cur.execute(
            """
            INSERT INTO projects (workspace_id, name, kind, shared, created_by)
            VALUES (%s, 'Inbox', 'inbox', FALSE, %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        stale_private_inbox = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO project_members (project_id, clerk_user_id)
            VALUES (%s, %s)
            """,
            (stale_private_inbox, owner),
        )
        conn.commit()

        _as_user(cur, owner)
        assert _fetch_ids(cur, "SELECT id FROM projects WHERE id = %s", (stale_private_inbox,)) == []
        conn.commit()


def test_personal_project_membership_does_not_grant_cross_user_access(conn):
    suffix = uuid.uuid4().hex[:8]
    owner = f"u_personal_owner_{suffix}"
    member = f"u_personal_member_{suffix}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            """
            INSERT INTO user_profiles (clerk_user_id, email, display_name)
            VALUES
              (%s, %s, 'Personal Owner'),
              (%s, %s, 'Personal Member')
            """,
            (owner, f"{owner}@example.test", member, f"{member}@example.test"),
        )
        cur.execute(
            "INSERT INTO workspaces (clerk_org_id, name) VALUES (%s, 'Personal Backdoor RLS') RETURNING id",
            (f"org_personal_{suffix}",),
        )
        workspace_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'admin'), (%s, %s, 'member')
            """,
            (workspace_id, owner, workspace_id, member),
        )
        cur.execute(
            """
            INSERT INTO projects (workspace_id, name, kind, created_by)
            VALUES (%s, 'Personal', 'personal', %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        personal_project = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO project_members (project_id, clerk_user_id)
            VALUES (%s, %s), (%s, %s)
            """,
            (personal_project, owner, personal_project, member),
        )
        cur.execute(
            """
            INSERT INTO notes (workspace_id, title, body, created_by)
            VALUES (%s, 'Personal note', 'This note is private.', %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        note_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO note_projects (note_id, project_id, linked_by)
            VALUES (%s, %s, %s)
            """,
            (note_id, personal_project, owner),
        )
        conn.commit()

        _as_user(cur, member)
        assert _fetch_ids(cur, "SELECT id FROM projects WHERE id = %s", (personal_project,)) == []
        assert _fetch_ids(cur, "SELECT project_id FROM project_members WHERE project_id = %s", (personal_project,)) == []
        assert _fetch_ids(cur, "SELECT id FROM notes WHERE id = %s", (note_id,)) == []
        conn.commit()


def test_fresh_personal_workspace_allows_self_bootstrap_membership(conn):
    suffix = uuid.uuid4().hex[:8]
    user_id = f"u_bootstrap_{suffix}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            "INSERT INTO user_profiles (clerk_user_id, email, display_name) VALUES (%s, %s, 'Bootstrap User')",
            (user_id, f"{user_id}@example.test"),
        )
        cur.execute(
            """
            INSERT INTO workspaces (clerk_org_id, name, inbox_mode)
            VALUES (%s, 'Fresh Bootstrap Workspace', 'per_user_private')
            RETURNING id
            """,
            (f"personal:{user_id}",),
        )
        workspace_id = cur.fetchone()["id"]
        conn.commit()

        _as_user(cur, user_id)
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'admin')
            """,
            (workspace_id, user_id),
        )
        assert _fetch_ids(
            cur,
            "SELECT workspace_id FROM workspace_members WHERE workspace_id = %s AND clerk_user_id = %s",
            (workspace_id, user_id),
        ) == [str(workspace_id)]
        conn.commit()


def test_removed_workspace_member_cannot_use_stale_project_access(conn):
    suffix = uuid.uuid4().hex[:8]
    owner = f"u_removed_owner_{suffix}"
    member = f"u_removed_member_{suffix}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            """
            INSERT INTO user_profiles (clerk_user_id, email, display_name)
            VALUES
              (%s, %s, 'Removed Owner'),
              (%s, %s, 'Removed Member')
            """,
            (owner, f"{owner}@example.test", member, f"{member}@example.test"),
        )
        cur.execute(
            "INSERT INTO workspaces (clerk_org_id, name) VALUES (%s, 'Removed Member RLS') RETURNING id",
            (f"org_removed_{suffix}",),
        )
        workspace_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'admin'), (%s, %s, 'member')
            """,
            (workspace_id, owner, workspace_id, member),
        )
        cur.execute(
            """
            INSERT INTO projects (workspace_id, name, kind, shared, created_by)
            VALUES (%s, 'Removed Project', 'user', TRUE, %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        project_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO project_members (project_id, clerk_user_id)
            VALUES (%s, %s), (%s, %s)
            """,
            (project_id, owner, project_id, member),
        )
        cur.execute(
            """
            INSERT INTO notes (workspace_id, title, body, created_by)
            VALUES (%s, 'Removed project note', 'Stale project membership should not expose this.', %s)
            RETURNING id
            """,
            (workspace_id, owner),
        )
        note_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO note_projects (note_id, project_id, linked_by)
            VALUES (%s, %s, %s)
            """,
            (note_id, project_id, owner),
        )
        conn.commit()

        _as_user(cur, member)
        cur.execute(
            """
            UPDATE workspace_members
            SET role = 'admin'
            WHERE workspace_id = %s AND clerk_user_id = %s
            """,
            (workspace_id, member),
        )
        assert cur.rowcount == 0
        cur.execute(
            """
            SELECT role
            FROM workspace_members
            WHERE workspace_id = %s AND clerk_user_id = %s
            """,
            (workspace_id, member),
        )
        assert cur.fetchone()["role"] == "member"
        conn.commit()

        cur.execute("RESET ROLE")
        cur.execute(
            "INSERT INTO workspaces (clerk_org_id, name) VALUES (%s, 'Attacker Workspace') RETURNING id",
            (f"org_attacker_{suffix}",),
        )
        attacker_workspace_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
            VALUES (%s, %s, 'member')
            """,
            (attacker_workspace_id, member),
        )
        conn.commit()

        _as_user(cur, member)
        cur.execute(
            """
            UPDATE workspace_members
            SET workspace_id = %s
            WHERE workspace_id = %s AND clerk_user_id = %s
            """,
            (workspace_id, attacker_workspace_id, member),
        )
        assert cur.rowcount == 0
        assert _fetch_ids(
            cur,
            "SELECT workspace_id FROM workspace_members WHERE clerk_user_id = %s ORDER BY workspace_id",
            (member,),
        ) == sorted([str(attacker_workspace_id), str(workspace_id)])
        cur.execute(
            """
            SELECT (update_own_workspace_member_settings(%s, 'auto', TRUE)).morning_briefing_optin
            """,
            (attacker_workspace_id,),
        )
        assert cur.fetchone()["morning_briefing_optin"] is True
        conn.commit()

        cur.execute("RESET ROLE")
        cur.execute(
            """
            DELETE FROM workspace_members
            WHERE workspace_id = %s AND clerk_user_id IN (%s, %s)
            """,
            (workspace_id, owner, member),
        )
        conn.commit()

        for removed_user in (owner, member):
            _as_user(cur, removed_user)
            assert _fetch_ids(cur, "SELECT id FROM projects WHERE id = %s", (project_id,)) == []
            assert _fetch_ids(cur, "SELECT project_id FROM project_members WHERE project_id = %s", (project_id,)) == []
            assert _fetch_ids(cur, "SELECT id FROM notes WHERE id = %s", (note_id,)) == []
            for role in ("member", "admin"):
                cur.execute("SAVEPOINT rejoin_guard")
                with pytest.raises(psycopg2.Error):
                    cur.execute(
                        """
                        INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
                        VALUES (%s, %s, %s)
                        """,
                        (workspace_id, removed_user, role),
                    )
                cur.execute("ROLLBACK TO SAVEPOINT rejoin_guard")
            conn.commit()


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
        "meeting_companies",
        "task_people",
        "task_projects",
        "task_notes",
        "task_companies",
        "task_reminders",
        "workflow_projects",
        "workflow_people",
        "workflow_notes",
        "workflow_tasks",
        "workflow_companies",
        "report_projects",
        "report_people",
        "report_notes",
        "report_tasks",
        "report_companies",
        "report_meetings",
        "report_workflows",
        "report_reports",
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
