from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import signal
import sys
import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from psycopg2.extras import RealDictCursor

from .briefing import enqueue_due_morning_briefings, send_morning_briefing
from .embeddings import embed_text, note_embedding_text, upsert_note_embedding
from .db import get_worker_conn, put_conn
from .ollama_client import extract_entities


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("notesnoop-worker")

POLL_INTERVAL_S = float(os.getenv("NOTESNOOP_WORKER_POLL_INTERVAL_S", "2"))
MAX_JOB_ATTEMPTS = int(os.getenv("NOTESNOOP_WORKER_MAX_ATTEMPTS", "3"))
RETRY_BACKOFF_SECONDS = int(os.getenv("NOTESNOOP_WORKER_RETRY_BACKOFF_SECONDS", "60"))
HEARTBEAT_INTERVAL_S = float(os.getenv("NOTESNOOP_WORKER_HEARTBEAT_INTERVAL_S", "30"))
STOP = asyncio.Event()


def get_conn():
    return get_worker_conn()


def _stop(*_args):
    STOP.set()


def _claim_job():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            cur.execute(
                """
                UPDATE ai_jobs
                SET state = 'running', consumed_at = now(), attempts = attempts + 1
                WHERE id = (
                  SELECT id
                  FROM ai_jobs
                  WHERE (
                      state = 'queued'
                      AND (consumed_at IS NULL OR consumed_at <= now())
                    )
                    OR (
                      state = 'running'
                      AND consumed_at IS NOT NULL
                      AND consumed_at < now() - (visibility_timeout_minutes * interval '1 minute')
                    )
                  ORDER BY priority DESC, created_at ASC
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                RETURNING *
                """
            )
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def _finish_job(job_id: str, state: str, error: str | None = None) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL search_path = public")
            cur.execute(
                """
                UPDATE ai_jobs
                SET state = %s, completed_at = now(), last_error = %s
                WHERE id = %s
                """,
                (state, error, job_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def _retry_job(job_id: str, error: str, delay_seconds: int) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL search_path = public")
            cur.execute(
                """
                UPDATE ai_jobs
                SET state = 'queued',
                    consumed_at = now() + (%s * interval '1 second'),
                    completed_at = NULL,
                    last_error = %s
                WHERE id = %s
                """,
                (delay_seconds, error, job_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def _write_heartbeat(key: str = "notesnoop-worker") -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL search_path = public")
            cur.execute(
                """
                INSERT INTO ops_heartbeats (key, last_seen_at, metadata)
                VALUES (%s, now(), jsonb_build_object('pid', pg_backend_pid()))
                ON CONFLICT (key)
                DO UPDATE
                  SET last_seen_at = EXCLUDED.last_seen_at,
                      metadata = EXCLUDED.metadata
                """,
                (key,),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.debug("worker heartbeat failed", exc_info=True)
    finally:
        put_conn(conn)


def _mark_note_failed(note_id: str, error: str) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL search_path = public")
            cur.execute(
                """
                UPDATE notes
                SET ai_processing_status = 'failed',
                    ai_processing_error = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (error[:1000], note_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def _is_retryable_exception(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True
    message = str(exc).lower()
    retryable_markers = (
        "too many requests",
        "rate limit",
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    )
    return any(marker in message for marker in retryable_markers)


def _similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(a=left.lower().strip(), b=right.lower().strip()).ratio()


def _best_match(name: str, rows: list[dict], key: str = "name") -> tuple[dict | None, float]:
    exact = next((row for row in rows if row[key].lower().strip() == name.lower().strip()), None)
    if exact:
        return exact, 1.0
    scored = sorted(((_similarity(name, row[key]), row) for row in rows), reverse=True, key=lambda item: item[0])
    if not scored or scored[0][0] < 0.80:
        return None, scored[0][0] if scored else 0.0
    return scored[0][1], scored[0][0]


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            deduped.append(clean)
    return deduped


def _looks_like_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _item_company_names(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []
    names: list[str] = []
    for key in ("company_name", "company"):
        value = item.get(key)
        if isinstance(value, str):
            names.append(value)
    for key in ("company_names", "companies"):
        value = item.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            if isinstance(entry, dict):
                names.append(str(entry.get("name") or ""))
            else:
                names.append(str(entry or ""))
    return _dedupe_strings(names)


def _item_person_names(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []
    names: list[str] = []
    for key in ("person_name", "assignee_name", "owner_name", "person"):
        value = item.get(key)
        if isinstance(value, str):
            names.append(value)
    for key in ("person_names", "people", "attendees", "participants"):
        value = item.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            if isinstance(entry, dict):
                names.append(str(entry.get("name") or ""))
            else:
                names.append(str(entry or ""))
    return _dedupe_strings(names)


def _resolve_person_ids_from_item(cur, workspace_id: str, item: dict[str, Any]) -> list[str]:
    """Resolve LLM-extracted person hints (name strings or UUIDs) on a memory
    item into known person IDs in the workspace. Mirrors _resolve_company_ids_from_payload.
    """
    resolved: list[str] = []
    raw_ids = _id_list(item.get("person_ids"))
    valid_ids = [value for value in raw_ids if _looks_like_uuid(value)]
    invalid_ids = [value for value in raw_ids if not _looks_like_uuid(value)]
    if valid_ids:
        cur.execute(
            """
            SELECT id
            FROM people
            WHERE workspace_id = %s
              AND id = ANY(%s::uuid[])
            """,
            (workspace_id, valid_ids),
        )
        rows = cur.fetchall()
        db_ids = [str(row["id"]) for row in rows]
        resolved.extend(db_ids or valid_ids)

    names = _dedupe_strings([*invalid_ids, *_item_person_names(item)])
    if names:
        cur.execute("SELECT id, name FROM people WHERE workspace_id = %s ORDER BY name", (workspace_id,))
        people = [dict(row) for row in cur.fetchall()]
        for name in names:
            person, score = _best_match(name, people)
            if person and score >= 0.85:
                resolved.append(str(person["id"]))
    return _dedupe_strings(resolved)


def _resolve_company_ids_from_payload(cur, workspace_id: str, payload: dict[str, Any]) -> list[str]:
    resolved: list[str] = []
    raw_ids = _id_list(payload.get("company_ids"))
    valid_ids = [value for value in raw_ids if _looks_like_uuid(value)]
    invalid_ids = [value for value in raw_ids if not _looks_like_uuid(value)]
    if valid_ids:
        cur.execute(
            """
            SELECT id
            FROM companies
            WHERE workspace_id = %s
              AND id = ANY(%s::uuid[])
            """,
            (workspace_id, valid_ids),
        )
        rows = cur.fetchall()
        db_ids = [str(row["id"]) for row in rows]
        resolved.extend(db_ids or valid_ids)

    names = _dedupe_strings([*invalid_ids, *_item_company_names(payload)])
    if names:
        cur.execute("SELECT id, name FROM companies WHERE workspace_id = %s ORDER BY name", (workspace_id,))
        companies = [dict(row) for row in cur.fetchall()]
        for name in names:
            company, score = _best_match(name, companies)
            if company and score >= 0.90:
                resolved.append(str(company["id"]))
    return _dedupe_strings(resolved)


def _load_context(cur, note_id: str) -> tuple[dict, list[dict], list[dict], list[dict]]:
    cur.execute("SELECT * FROM notes WHERE id = %s", (note_id,))
    note = dict(cur.fetchone())
    cur.execute("SELECT * FROM people WHERE workspace_id = %s ORDER BY name", (note["workspace_id"],))
    people = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT * FROM projects WHERE workspace_id = %s ORDER BY name", (note["workspace_id"],))
    projects = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT * FROM companies WHERE workspace_id = %s ORDER BY name", (note["workspace_id"],))
    companies = [dict(row) for row in cur.fetchall()]
    return note, people, projects, companies


def _unpack_context(context: tuple) -> tuple[dict, list[dict], list[dict], list[dict]]:
    if len(context) == 3:
        note, people, projects = context
        return note, people, projects, []
    note, people, projects, companies = context
    return note, people, projects, companies


def _insert_review(cur, note: dict, target_user_id: str, entity_kind: str, payload: dict[str, Any], reason: str = "ai_suggestion"):
    candidate_key = payload.get("candidate_key")
    if candidate_key:
        cur.execute(
            """
            SELECT id
            FROM review_queue
            WHERE workspace_id = %s
              AND target_user_id = %s
              AND entity_kind = %s
              AND entity_id = %s
              AND reason = %s
              AND state IN ('open','accepted')
              AND payload->>'candidate_key' = %s
            LIMIT 1
            """,
            (note["workspace_id"], target_user_id, entity_kind, note["id"], reason, candidate_key),
        )
        if cur.fetchone():
            return
    cur.execute(
        """
        INSERT INTO review_queue (workspace_id, target_user_id, entity_kind, entity_id, reason, payload)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (note["workspace_id"], target_user_id, entity_kind, note["id"], reason, json.dumps(payload)),
    )


def _record_calibration(cur, job_id: str, note: dict, confidence: float, decision: str):
    cur.execute(
        """
        INSERT INTO calibration_events (ai_job_id, workspace_id, confidence, user_decision)
        VALUES (%s, %s, %s, %s)
        """,
        (job_id, note["workspace_id"], confidence, decision),
    )


def _note_title(note: dict, fallback: str = "Untitled") -> str:
    title = str(note.get("title") or "").strip()
    if title:
        return title[:240]
    first_line = next((line.strip() for line in str(note.get("body") or "").splitlines() if line.strip()), "")
    return (first_line or fallback)[:240]


def _materialize_title(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("title") or value.get("text") or value.get("task") or value.get("action")
    title = str(value or "").strip()
    title = " ".join(title.split()).strip(" .;")
    return title[:240]


def _coerce_due_at(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, time(12, 0), tzinfo=timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            parsed_date = date.fromisoformat(text)
            return datetime.combine(parsed_date, time(12, 0), tzinfo=timezone.utc).isoformat()
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def _linked_project_ids(cur, note_id: str) -> list[str]:
    cur.execute(
        """
        SELECT p.id
        FROM note_projects np
        JOIN projects p ON p.id = np.project_id
        WHERE np.note_id = %s
          AND p.kind <> 'personal'
        ORDER BY p.created_at ASC
        """,
        (note_id,),
    )
    return [str(row["id"]) for row in cur.fetchall()]


def _link_memory_projects(cur, table: str, id_column: str, entity_id: str, workspace_id: str, project_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for project_id in project_ids:
        cur.execute(
            f"""
            INSERT INTO {table} ({id_column}, project_id, workspace_id, linked_by, linked_via)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (entity_id, project_id, workspace_id, linked_by, linked_via),
        )


def _linked_person_ids(cur, note_id: str) -> list[str]:
    cur.execute(
        """
        SELECT person_id
        FROM note_people_links
        WHERE note_id = %s
          AND state IN ('confirmed','auto_linked')
        ORDER BY created_at
        """,
        (note_id,),
    )
    return [str(row["person_id"]) for row in cur.fetchall()]


def _link_task_people(cur, task_id: str, workspace_id: str, person_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    # AI-extracted people on a task with multiple participants are *involved*,
    # not necessarily *responsible*. Mark them all as watchers so the task
    # lands unassigned and the operator picks the right assignee. The single-
    # person case is unambiguous — if only one person is on the task, treat
    # them as the assignee (preserves the existing single-link semantics).
    deduped = [pid for pid in (person_ids or []) if pid]
    default_relation = "assignee" if len(deduped) == 1 else "watcher"
    for person_id in deduped:
        cur.execute(
            """
            INSERT INTO task_people (task_id, person_id, workspace_id, relation, linked_by, linked_via)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (task_id, person_id, workspace_id, default_relation, linked_by, linked_via),
        )


def _link_task_companies(cur, task_id: str, workspace_id: str, company_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for company_id in company_ids:
        cur.execute(
            """
            INSERT INTO task_companies (task_id, company_id, workspace_id, linked_by, linked_via)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (task_id, company_id, workspace_id, linked_by, linked_via),
        )


def _link_meeting_people(cur, meeting_id: str, workspace_id: str, person_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for person_id in person_ids:
        cur.execute(
            """
            INSERT INTO meeting_people (meeting_id, person_id, workspace_id, attendance_status, linked_by, linked_via)
            VALUES (%s, %s, %s, 'attended', %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (meeting_id, person_id, workspace_id, linked_by, linked_via),
        )


def _link_meeting_companies(cur, meeting_id: str, workspace_id: str, company_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for company_id in company_ids:
        cur.execute(
            """
            INSERT INTO meeting_companies (meeting_id, company_id, workspace_id, linked_by, linked_via)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (meeting_id, company_id, workspace_id, linked_by, linked_via),
        )


def _link_report_people(cur, report_id: str, workspace_id: str, person_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for person_id in person_ids:
        cur.execute(
            """
            INSERT INTO report_people (report_id, person_id, workspace_id, linked_by, linked_via)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (report_id, person_id, workspace_id, linked_by, linked_via),
        )


def _link_company_people(cur, company_id: str, workspace_id: str, person_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for person_id in person_ids:
        cur.execute(
            """
            INSERT INTO company_people (company_id, person_id, workspace_id, linked_by, linked_via)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (company_id, person_id, workspace_id, linked_by, linked_via),
        )


def _link_company_projects(cur, company_id: str, workspace_id: str, project_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for project_id in project_ids:
        cur.execute(
            """
            INSERT INTO company_projects (company_id, project_id, workspace_id, linked_by, linked_via)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (company_id, project_id, workspace_id, linked_by, linked_via),
        )


def _link_company_note(cur, company_id: str, note_id: str, workspace_id: str, linked_by: str) -> None:
    cur.execute(
        """
        INSERT INTO company_notes (company_id, note_id, workspace_id, linked_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (company_id, note_id, workspace_id, linked_by),
    )


def _link_workflow_people(cur, workflow_id: str, workspace_id: str, person_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for person_id in person_ids:
        cur.execute(
            """
            INSERT INTO workflow_people (workflow_id, person_id, workspace_id, relation, linked_by, linked_via)
            VALUES (%s, %s, %s, 'participant', %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (workflow_id, person_id, workspace_id, linked_by, linked_via),
        )


def _link_workflow_note(cur, workflow_id: str, note_id: str, workspace_id: str, linked_by: str) -> None:
    cur.execute(
        """
        INSERT INTO workflow_notes (workflow_id, note_id, workspace_id, linked_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (workflow_id, note_id, workspace_id, linked_by),
    )


def _link_workflow_companies(cur, workflow_id: str, workspace_id: str, company_ids: list[str], linked_by: str, linked_via: str = "ai") -> None:
    for company_id in company_ids:
        cur.execute(
            """
            INSERT INTO workflow_companies (workflow_id, company_id, workspace_id, linked_by, linked_via)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (workflow_id, company_id, workspace_id, linked_by, linked_via),
        )


def _link_workflow_tasks(cur, workflow_id: str, workspace_id: str, task_ids: list[str], linked_by: str) -> None:
    for position, task_id in enumerate(task_ids, start=1):
        cur.execute(
            """
            INSERT INTO workflow_tasks (workflow_id, task_id, workspace_id, position, linked_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (workflow_id, task_id, workspace_id, position, linked_by),
        )


def _memory_item_title(item: Any, default: str) -> str:
    title = _materialize_title(item)
    if not title and isinstance(item, dict):
        title = _materialize_title(item.get("name") or item.get("summary"))
    return title or default


def _memory_item_description(item: Any, fallback: str = "") -> str | None:
    if isinstance(item, dict):
        value = item.get("description") or item.get("summary") or item.get("body") or fallback
    else:
        value = fallback
    text = " ".join(str(value or "").split())
    return text[:4000] if text else None


def _materialize_company(
    cur,
    note: dict,
    item: Any,
    target_user_id: str,
    project_ids: list[str],
    person_ids: list[str],
    source_kind: str = "ai_company",
    review_id: str | None = None,
    source_confidence: float | None = None,
    source_payload: dict[str, Any] | None = None,
) -> str | None:
    name = _memory_item_title(item, "")
    if not name:
        return None
    domain = item.get("domain") if isinstance(item, dict) else None
    description = _memory_item_description(item)
    cur.execute(
        """
        INSERT INTO companies (
          workspace_id, name, domain, description, created_by, source_note_id, source_kind,
          ai_review_state, ai_review_id, source_confidence, source_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'accepted', %s, %s, %s::jsonb)
        ON CONFLICT (workspace_id, lower(name))
        DO UPDATE
          SET domain = COALESCE(EXCLUDED.domain, companies.domain),
              description = COALESCE(EXCLUDED.description, companies.description),
              source_note_id = COALESCE(companies.source_note_id, EXCLUDED.source_note_id),
              source_kind = COALESCE(companies.source_kind, EXCLUDED.source_kind),
              ai_review_state = 'accepted',
              ai_review_id = COALESCE(EXCLUDED.ai_review_id, companies.ai_review_id),
              source_confidence = COALESCE(EXCLUDED.source_confidence, companies.source_confidence),
              source_payload = COALESCE(EXCLUDED.source_payload, companies.source_payload),
              updated_at = now()
        RETURNING id
        """,
        (
            note["workspace_id"],
            name,
            domain,
            description,
            target_user_id,
            note["id"],
            source_kind,
            review_id,
            source_confidence,
            json.dumps(source_payload) if source_payload else None,
        ),
    )
    row = cur.fetchone()
    if not row:
        return None
    company_id = str(row["id"])
    _link_company_note(cur, company_id, str(note["id"]), str(note["workspace_id"]), target_user_id)
    _link_company_projects(cur, company_id, str(note["workspace_id"]), project_ids, target_user_id)
    _link_company_people(cur, company_id, str(note["workspace_id"]), person_ids, target_user_id)
    return company_id


def _materialize_meeting(
    cur,
    note: dict,
    item: Any,
    target_user_id: str,
    project_ids: list[str],
    person_ids: list[str],
    source_kind: str,
    company_ids: list[str] | None = None,
    review_id: str | None = None,
    source_confidence: float | None = None,
    source_payload: dict[str, Any] | None = None,
) -> str | None:
    title = _memory_item_title(item, "Captured conversation")
    occurred_at = note.get("occurred_at")
    if isinstance(item, dict):
        occurred_at = _coerce_due_at(item.get("occurred_at") or item.get("occurred_date")) or occurred_at
    cur.execute(
        """
        INSERT INTO meetings (
          workspace_id, title, occurred_at, summary, created_by, source_note_id, source_kind,
          ai_review_state, ai_review_id, source_confidence, source_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'accepted', %s, %s, %s::jsonb)
        ON CONFLICT (source_note_id, source_kind)
          WHERE source_note_id IS NOT NULL
        DO UPDATE
          SET updated_at = now(),
              title = COALESCE(NULLIF(EXCLUDED.title, ''), meetings.title),
              summary = COALESCE(EXCLUDED.summary, meetings.summary),
              occurred_at = COALESCE(EXCLUDED.occurred_at, meetings.occurred_at),
              ai_review_state = 'accepted',
              ai_review_id = COALESCE(EXCLUDED.ai_review_id, meetings.ai_review_id),
              source_confidence = COALESCE(EXCLUDED.source_confidence, meetings.source_confidence),
              source_payload = COALESCE(EXCLUDED.source_payload, meetings.source_payload)
        RETURNING id
        """,
        (
            note["workspace_id"],
            title,
            occurred_at,
            _memory_item_description(item, str(note.get("body") or "")[:4000]),
            target_user_id,
            note["id"],
            source_kind,
            review_id,
            source_confidence,
            json.dumps(source_payload) if source_payload else None,
        ),
    )
    row = cur.fetchone()
    if not row:
        return None
    meeting_id = str(row["id"])
    cur.execute(
        """
        INSERT INTO meeting_notes (meeting_id, note_id, workspace_id, linked_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (meeting_id, note["id"], note["workspace_id"], target_user_id),
    )
    _link_memory_projects(cur, "meeting_projects", "meeting_id", meeting_id, str(note["workspace_id"]), project_ids, target_user_id)
    _link_meeting_people(cur, meeting_id, str(note["workspace_id"]), person_ids, target_user_id)
    _link_meeting_companies(cur, meeting_id, str(note["workspace_id"]), company_ids or [], target_user_id)
    return meeting_id


def _materialize_report(
    cur,
    note: dict,
    item: Any,
    target_user_id: str,
    project_ids: list[str],
    person_ids: list[str],
    task_ids: list[str],
    company_ids: list[str],
    meeting_ids: list[str] | None,
    workflow_ids: list[str] | None,
    report_ids: list[str] | None,
    source_kind: str,
    review_id: str | None = None,
    source_confidence: float | None = None,
    source_payload: dict[str, Any] | None = None,
) -> str | None:
    title = _memory_item_title(item, "Captured brief")
    status = "draft"
    if isinstance(item, dict) and item.get("status") in {"draft", "published", "archived"}:
        status = item["status"]
    cur.execute(
        """
        INSERT INTO reports (
          workspace_id, title, body, status, created_by, source_note_id, source_kind,
          ai_review_state, ai_review_id, source_confidence, source_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'accepted', %s, %s, %s::jsonb)
        ON CONFLICT (source_note_id, source_kind)
          WHERE source_note_id IS NOT NULL
        DO UPDATE
          SET updated_at = now(),
              title = COALESCE(NULLIF(EXCLUDED.title, ''), reports.title),
              body = COALESCE(EXCLUDED.body, reports.body),
              status = EXCLUDED.status,
              ai_review_state = 'accepted',
              ai_review_id = COALESCE(EXCLUDED.ai_review_id, reports.ai_review_id),
              source_confidence = COALESCE(EXCLUDED.source_confidence, reports.source_confidence),
              source_payload = COALESCE(EXCLUDED.source_payload, reports.source_payload)
        RETURNING id
        """,
        (
            note["workspace_id"],
            title,
            _memory_item_description(item, str(note.get("body") or "")),
            status,
            target_user_id,
            note["id"],
            source_kind,
            review_id,
            source_confidence,
            json.dumps(source_payload) if source_payload else None,
        ),
    )
    row = cur.fetchone()
    if not row:
        return None
    report_id = str(row["id"])
    cur.execute(
        """
        INSERT INTO report_notes (report_id, note_id, workspace_id, linked_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (report_id, note["id"], note["workspace_id"], target_user_id),
    )
    _link_memory_projects(cur, "report_projects", "report_id", report_id, str(note["workspace_id"]), project_ids, target_user_id)
    _link_report_people(cur, report_id, str(note["workspace_id"]), person_ids, target_user_id)
    for task_id in task_ids:
        cur.execute(
            """
            INSERT INTO report_tasks (report_id, task_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (report_id, task_id, note["workspace_id"], target_user_id),
        )
    for company_id in company_ids:
        cur.execute(
            """
            INSERT INTO report_companies (report_id, company_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (report_id, company_id, note["workspace_id"], target_user_id),
        )
    for meeting_id in meeting_ids or []:
        cur.execute(
            """
            INSERT INTO report_meetings (report_id, meeting_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (report_id, meeting_id, note["workspace_id"], target_user_id),
        )
    for workflow_id in workflow_ids or []:
        cur.execute(
            """
            INSERT INTO report_workflows (report_id, workflow_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (report_id, workflow_id, note["workspace_id"], target_user_id),
        )
    for source_report_id in report_ids or []:
        if source_report_id == report_id:
            continue
        cur.execute(
            """
            INSERT INTO report_reports (report_id, source_report_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (report_id, source_report_id, note["workspace_id"], target_user_id),
        )
    return report_id


def _materialize_workflow(
    cur,
    note: dict,
    item: Any,
    target_user_id: str,
    project_ids: list[str],
    person_ids: list[str],
    task_ids: list[str],
    company_ids: list[str] | None = None,
    source_kind: str = "ai_workflow",
    review_id: str | None = None,
    source_confidence: float | None = None,
    source_payload: dict[str, Any] | None = None,
) -> str | None:
    name = _memory_item_title(item, "")
    if not name:
        return None
    status = "active"
    if isinstance(item, dict) and item.get("status") in {"draft", "active", "paused", "retired"}:
        status = item["status"]
    cur.execute(
        """
        INSERT INTO workflows (
          workspace_id, name, description, status, created_by, source_note_id, source_kind,
          ai_review_state, ai_review_id, source_confidence, source_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'accepted', %s, %s, %s::jsonb)
        ON CONFLICT (workspace_id, lower(name))
        DO UPDATE
          SET description = COALESCE(EXCLUDED.description, workflows.description),
              status = CASE WHEN workflows.status = 'retired' THEN workflows.status ELSE EXCLUDED.status END,
              source_note_id = COALESCE(workflows.source_note_id, EXCLUDED.source_note_id),
              source_kind = COALESCE(workflows.source_kind, EXCLUDED.source_kind),
              ai_review_state = 'accepted',
              ai_review_id = COALESCE(EXCLUDED.ai_review_id, workflows.ai_review_id),
              source_confidence = COALESCE(EXCLUDED.source_confidence, workflows.source_confidence),
              source_payload = COALESCE(EXCLUDED.source_payload, workflows.source_payload),
              updated_at = now()
        RETURNING id
        """,
        (
            note["workspace_id"],
            name,
            _memory_item_description(item, str(note.get("body") or "")[:1000]),
            status,
            target_user_id,
            note["id"],
            source_kind,
            review_id,
            source_confidence,
            json.dumps(source_payload) if source_payload else None,
        ),
    )
    row = cur.fetchone()
    if not row:
        return None
    workflow_id = str(row["id"])
    _link_memory_projects(cur, "workflow_projects", "workflow_id", workflow_id, str(note["workspace_id"]), project_ids, target_user_id)
    _link_workflow_people(cur, workflow_id, str(note["workspace_id"]), person_ids, target_user_id)
    _link_workflow_companies(cur, workflow_id, str(note["workspace_id"]), company_ids or [], target_user_id)
    _link_workflow_note(cur, workflow_id, str(note["id"]), str(note["workspace_id"]), target_user_id)
    _link_workflow_tasks(cur, workflow_id, str(note["workspace_id"]), task_ids, target_user_id)
    return workflow_id


def _materialize_task(
    cur,
    note: dict,
    title: str,
    source_kind: str,
    target_user_id: str,
    project_ids: list[str],
    person_ids: list[str],
    due_at: Any = None,
    company_ids: list[str] | None = None,
    description: str | None = None,
    status: str = "todo",
    priority: int = 3,
    review_id: str | None = None,
    source_confidence: float | None = None,
    source_payload: dict[str, Any] | None = None,
) -> str | None:
    if not title:
        return None
    task_due_at = _coerce_due_at(due_at)
    if status not in {"todo", "doing", "blocked", "done", "archived"}:
        status = "todo"
    try:
        priority = max(1, min(5, int(priority)))
    except (TypeError, ValueError):
        priority = 3
    cur.execute(
        """
        INSERT INTO tasks (
          workspace_id, title, description, status, priority, due_at, created_by, source_note_id, source_kind,
          ai_review_state, ai_review_id, source_confidence, source_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'accepted', %s, %s, %s::jsonb)
        ON CONFLICT (source_note_id, source_kind, lower(title))
          WHERE source_note_id IS NOT NULL
        DO UPDATE
          SET updated_at = now(),
              description = COALESCE(EXCLUDED.description, tasks.description),
              status = EXCLUDED.status,
              priority = EXCLUDED.priority,
              due_at = COALESCE(EXCLUDED.due_at, tasks.due_at),
              ai_review_state = 'accepted',
              ai_review_id = COALESCE(EXCLUDED.ai_review_id, tasks.ai_review_id),
              source_confidence = COALESCE(EXCLUDED.source_confidence, tasks.source_confidence),
              source_payload = COALESCE(EXCLUDED.source_payload, tasks.source_payload)
        RETURNING id
        """,
        (
            note["workspace_id"],
            title,
            (description if description is not None else str(note.get("body") or "")[:2000]),
            status,
            priority,
            task_due_at,
            target_user_id,
            note["id"],
            source_kind,
            review_id,
            source_confidence,
            json.dumps(source_payload) if source_payload else None,
        ),
    )
    row = cur.fetchone()
    if not row:
        return None
    task_id = str(row["id"])
    cur.execute(
        """
        INSERT INTO task_notes (task_id, note_id, workspace_id, linked_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (task_id, note["id"], note["workspace_id"], target_user_id),
    )
    _link_memory_projects(cur, "task_projects", "task_id", task_id, note["workspace_id"], project_ids, target_user_id)
    _link_task_people(cur, task_id, note["workspace_id"], person_ids, target_user_id)
    _link_task_companies(cur, task_id, note["workspace_id"], company_ids or [], target_user_id)
    return task_id


def _item_confidence(item: Any, default: float = 0.75) -> float:
    if isinstance(item, dict):
        try:
            return max(0.0, min(1.0, float(item.get("confidence") or default)))
        except (TypeError, ValueError):
            return default
    return default


def _candidate_key(kind: str, note_id: str, source_kind: str, title: str) -> str:
    return f"{kind}:{note_id}:{source_kind}:{title.casefold()[:160]}"


def _base_candidate(
    kind: str,
    note: dict,
    title: str,
    source_kind: str,
    item: Any,
    project_ids: list[str],
    person_ids: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidate_key": _candidate_key(kind, str(note["id"]), source_kind, title),
        "source_note_id": str(note["id"]),
        "note_id": str(note["id"]),
        "source_kind": source_kind,
        "confidence": _item_confidence(item),
        "project_ids": project_ids,
        "person_ids": person_ids,
    }
    if isinstance(item, dict):
        payload.update({key: value for key, value in item.items() if value not in (None, "")})
    return payload


def _ai_source_payload(
    kind: str,
    note: dict,
    title: str,
    source_kind: str,
    item: Any,
    project_ids: list[str],
    person_ids: list[str],
) -> dict[str, Any]:
    payload = _base_candidate(kind, note, title, source_kind, item, project_ids, person_ids)
    payload["title" if kind != "company" else "name"] = title
    return payload


def _enrich_company_links_from_context(
    cur,
    note: dict,
    data: dict[str, Any],
    target_user_id: str,
    project_ids: list[str],
    person_ids: list[str],
    companies: list[dict],
    job_id: str | None = None,
) -> list[str]:
    linked_ids: list[str] = []
    name_to_id: dict[str, str] = {}

    for item in data.get("companies", []):
        if not isinstance(item, dict):
            continue
        name = _memory_item_title(item, "")
        if not name:
            continue
        company, match_score = _best_match(name, companies)
        confidence = _item_confidence(item)
        effective_confidence = min(confidence, match_score) if company else confidence
        if company and effective_confidence >= 0.90:
            company_id = str(company["id"])
            item["_skip_company_candidate"] = True
            item["matched_company_id"] = company_id
            item["company_ids"] = [company_id]
            name_to_id[name.casefold()] = company_id
            linked_ids.append(company_id)
            _link_company_note(cur, company_id, str(note["id"]), str(note["workspace_id"]), target_user_id)
            _link_company_projects(cur, company_id, str(note["workspace_id"]), project_ids, target_user_id)
            _link_company_people(cur, company_id, str(note["workspace_id"]), person_ids, target_user_id)
            if job_id:
                _record_calibration(cur, job_id, note, effective_confidence, "accepted")
        elif company and effective_confidence >= 0.70:
            item["matched_company_id"] = str(company["id"])

    linked_ids = _dedupe_strings(linked_ids)
    for collection in ("tasks", "meetings", "workflows", "reports"):
        for item in data.get(collection, []):
            if not isinstance(item, dict):
                continue
            item_ids = [value for value in _id_list(item.get("company_ids")) if _looks_like_uuid(value)]
            for name in _item_company_names(item):
                company_id = name_to_id.get(name.casefold())
                if not company_id:
                    company, score = _best_match(name, companies)
                    if company and score >= 0.90:
                        company_id = str(company["id"])
                if company_id:
                    item_ids.append(company_id)
                    if company_id not in linked_ids:
                        linked_ids.append(company_id)
                        _link_company_note(cur, company_id, str(note["id"]), str(note["workspace_id"]), target_user_id)
                        _link_company_projects(cur, company_id, str(note["workspace_id"]), project_ids, target_user_id)
                        _link_company_people(cur, company_id, str(note["workspace_id"]), person_ids, target_user_id)
            if not item_ids and len(linked_ids) == 1:
                item_ids = [linked_ids[0]]
            if item_ids:
                item["company_ids"] = _dedupe_strings(item_ids)
    return _dedupe_strings(linked_ids)


_LIST_HEADER_PREFIXES = (
    "action items",
    "action item",
    "todos",
    "to-dos",
    "to do list",
    "to-do list",
    "tasks",
    "decisions",
    "follow-ups",
    "follow ups",
    "next steps",
    "summary",
)


def _is_list_header_title(title: str) -> bool:
    """True when the proposed task title is a structural list header rather
    than a concrete actionable phrase (e.g. "Action items: (1) draft..."
    that the LLM occasionally extracts alongside the real tasks)."""
    if not title:
        return False
    head = title.strip().lower()
    if len(head) > 220:
        return True  # paragraph-length titles are never real tasks
    for prefix in _LIST_HEADER_PREFIXES:
        if head == prefix or head.startswith(prefix + ":") or head.startswith(prefix + " ("):
            return True
    return False


def _structured_memory_candidates(
    note: dict,
    data: dict[str, Any],
    project_ids: list[str],
    person_ids: list[str],
) -> list[tuple[str, dict[str, Any]]]:
    note_id = str(note["id"])
    note_kind = str(note.get("note_kind") or "note").lower()
    candidates: list[tuple[str, dict[str, Any]]] = []

    seen_company_names: set[str] = set()
    for item in data.get("companies", []):
        if isinstance(item, dict) and item.get("_skip_company_candidate"):
            continue
        name = _memory_item_title(item, "")
        key = name.casefold()
        if not name or key in seen_company_names:
            continue
        seen_company_names.add(key)
        payload = _base_candidate("company", note, name, f"ai_company:{key[:80]}", item, project_ids, person_ids)
        payload["name"] = name
        payload["description"] = payload.get("description") or payload.get("summary")
        candidates.append(("company", payload))

    seen_task_titles: set[str] = set()
    for item in data.get("tasks", []):
        title = _materialize_title(item)
        if _is_list_header_title(title):
            # LLM sometimes lifts the "Action items:" / "Decisions:" line itself
            # as a standalone task — drop those so the review queue only shows
            # actionable phrases.
            continue
        key = title.casefold()
        if not title or key in seen_task_titles:
            continue
        seen_task_titles.add(key)
        payload = _base_candidate("task", note, title, "action_item", item, project_ids, person_ids)
        payload["title"] = title
        payload["description"] = payload.get("description") or payload.get("summary") or str(note.get("body") or "")[:2000]
        payload["status"] = payload.get("status") or "todo"
        payload["priority"] = payload.get("priority") or 3
        payload["due_at"] = payload.get("due_at") or payload.get("due_date")
        candidates.append(("task", payload))

    if note_kind == "task":
        title = _note_title(note, "Task")
        key = title.casefold()
        if key not in seen_task_titles:
            candidates.append(
                (
                    "task",
                    {
                        "candidate_key": _candidate_key("task", note_id, "note_task", title),
                        "source_note_id": note_id,
                        "note_id": note_id,
                        "source_kind": "note_task",
                        "confidence": 0.9,
                        "title": title,
                        "description": str(note.get("body") or "")[:2000],
                        "status": "todo",
                        "priority": 3,
                        "project_ids": project_ids,
                        "person_ids": person_ids,
                    },
                )
            )

    seen_meeting_titles: set[str] = set()
    if note_kind not in {"meeting", "call"}:
        for item in data.get("meetings", []):
            title = _memory_item_title(item, "")
            key = title.casefold()
            if not title or key in seen_meeting_titles:
                continue
            seen_meeting_titles.add(key)
            payload = _base_candidate("meeting", note, title, f"ai_meeting:{key[:80]}", item, project_ids, person_ids)
            payload["title"] = title
            payload["summary"] = payload.get("summary") or payload.get("description") or str(note.get("body") or "")[:4000]
            candidates.append(("meeting", payload))

    if note_kind in {"meeting", "call"}:
        title = _note_title(note, "Meeting")
        candidates.append(
            (
                "meeting",
                {
                    "candidate_key": _candidate_key("meeting", note_id, note_kind, title),
                    "source_note_id": note_id,
                    "note_id": note_id,
                    "source_kind": note_kind,
                    "confidence": 0.9,
                    "title": title,
                    "summary": str(note.get("body") or "")[:4000],
                    "occurred_at": note.get("occurred_at").isoformat() if hasattr(note.get("occurred_at"), "isoformat") else note.get("occurred_at"),
                    "project_ids": project_ids,
                    "person_ids": person_ids,
                },
            )
        )

    seen_workflows: set[str] = set()
    for item in data.get("workflows", []):
        name = _memory_item_title(item, "")
        key = name.casefold()
        if not name or key in seen_workflows:
            continue
        seen_workflows.add(key)
        payload = _base_candidate("workflow", note, name, f"ai_workflow:{key[:80]}", item, project_ids, person_ids)
        payload["name"] = name
        payload["description"] = payload.get("description") or payload.get("summary") or str(note.get("body") or "")[:1000]
        payload["status"] = payload.get("status") or "active"
        payload.setdefault("task_ids", [])
        candidates.append(("workflow", payload))

    seen_reports: set[str] = set()
    if note_kind != "report":
        for item in data.get("reports", []):
            title = _memory_item_title(item, "")
            key = title.casefold()
            if not title or key in seen_reports:
                continue
            seen_reports.add(key)
            payload = _base_candidate("report", note, title, f"ai_report:{key[:80]}", item, project_ids, person_ids)
            payload["title"] = title
            payload["body"] = payload.get("body") or payload.get("summary") or payload.get("description") or str(note.get("body") or "")
            payload["status"] = payload.get("status") or "draft"
            payload.setdefault("task_ids", [])
            payload.setdefault("company_ids", [])
            candidates.append(("report", payload))

    if note_kind == "report":
        title = _note_title(note, "Report")
        candidates.append(
            (
                "report",
                {
                    "candidate_key": _candidate_key("report", note_id, "report", title),
                    "source_note_id": note_id,
                    "note_id": note_id,
                    "source_kind": "report",
                    "confidence": 0.9,
                    "title": title,
                    "body": str(note.get("body") or ""),
                    "status": "draft",
                    "project_ids": project_ids,
                    "person_ids": person_ids,
                    "task_ids": [],
                    "company_ids": [],
                },
            )
        )

    return candidates


def _enqueue_structured_memory_reviews(
    cur,
    note: dict,
    data: dict[str, Any],
    target_user_id: str,
    person_ids: list[str] | None = None,
) -> dict[str, int]:
    note_id = str(note["id"])
    project_ids = _linked_project_ids(cur, note_id)
    person_ids = person_ids or _linked_person_ids(cur, note_id)
    created = {"tasks": 0, "meetings": 0, "reports": 0, "workflows": 0, "companies": 0}
    for kind, payload in _structured_memory_candidates(note, data, project_ids, person_ids):
        _insert_review(cur, note, target_user_id, kind, payload)
        plural = f"{kind}s" if kind != "company" else "companies"
        created[plural] += 1
    return created


def _id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _materialize_review_candidate(cur, review: dict, payload: dict[str, Any], target_user_id: str) -> str | None:
    kind = str(review.get("entity_kind") or "")
    cur.execute("SELECT * FROM notes WHERE id = %s AND workspace_id = %s", (review["entity_id"], review["workspace_id"]))
    note_row = cur.fetchone()
    if not note_row:
        return None
    note = dict(note_row)
    workspace_id = str(note["workspace_id"])
    project_ids = _id_list(payload.get("project_ids")) or _linked_project_ids(cur, str(note["id"]))
    person_ids = _id_list(payload.get("person_ids")) or _linked_person_ids(cur, str(note["id"]))
    company_ids = _resolve_company_ids_from_payload(cur, workspace_id, payload)
    source_kind = str(payload.get("source_kind") or f"review_{kind}")
    confidence = _item_confidence(payload)
    review_id = str(review["id"])

    if kind == "task":
        title = _memory_item_title(payload, "")
        return _materialize_task(
            cur,
            note,
            title,
            source_kind,
            target_user_id,
            project_ids,
            person_ids,
            payload.get("due_at") or payload.get("due_date"),
            description=payload.get("description") or payload.get("summary") or payload.get("body"),
            status=str(payload.get("status") or "todo"),
            priority=payload.get("priority") or 3,
            company_ids=company_ids,
            review_id=review_id,
            source_confidence=confidence,
            source_payload=payload,
        )
    if kind == "meeting":
        return _materialize_meeting(
            cur,
            note,
            payload,
            target_user_id,
            project_ids,
            person_ids,
            source_kind,
            company_ids=company_ids,
            review_id=review_id,
            source_confidence=confidence,
            source_payload=payload,
        )
    if kind == "report":
        return _materialize_report(
            cur,
            note,
            payload,
            target_user_id,
            project_ids,
            person_ids,
            _id_list(payload.get("task_ids")),
            company_ids,
            _id_list(payload.get("meeting_ids")),
            _id_list(payload.get("workflow_ids")),
            _id_list(payload.get("report_ids")),
            source_kind,
            review_id=review_id,
            source_confidence=confidence,
            source_payload=payload,
        )
    if kind == "workflow":
        return _materialize_workflow(
            cur,
            note,
            payload,
            target_user_id,
            project_ids,
            person_ids,
            _id_list(payload.get("task_ids")),
            company_ids=company_ids,
            source_kind=source_kind,
            review_id=review_id,
            source_confidence=confidence,
            source_payload=payload,
        )
    if kind == "company":
        return _materialize_company(
            cur,
            note,
            payload,
            target_user_id,
            project_ids,
            person_ids,
            source_kind=source_kind,
            review_id=review_id,
            source_confidence=confidence,
            source_payload=payload,
        )
    return None


def _materialize_ai_memory(cur, note: dict, data: dict[str, Any], target_user_id: str, person_ids: list[str] | None = None) -> dict[str, int]:
    note_id = str(note["id"])
    note_kind = str(note.get("note_kind") or "note").lower()
    created = {"tasks": 0, "meetings": 0, "reports": 0, "workflows": 0, "companies": 0}
    project_ids = _linked_project_ids(cur, note_id)
    person_ids = person_ids or _linked_person_ids(cur, note_id)

    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"memory:{note_id}",))

    company_ids: list[str] = []
    seen_company_names: set[str] = set()
    for item in data.get("companies", []):
        name = _memory_item_title(item, "")
        key = name.casefold()
        if not name or key in seen_company_names:
            continue
        seen_company_names.add(key)
        source_kind = f"ai_company:{key[:80]}"
        company_id = _materialize_company(
            cur,
            note,
            item,
            target_user_id,
            project_ids,
            person_ids,
            source_kind=source_kind,
            source_confidence=_item_confidence(item),
            source_payload=_ai_source_payload("company", note, name, source_kind, item, project_ids, person_ids),
        )
        if company_id:
            company_ids.append(company_id)
            created["companies"] += 1

    workspace_id = str(note["workspace_id"])
    task_ids: list[str] = []
    seen_task_titles: set[str] = set()
    for item in data.get("tasks", []):
        title = _materialize_title(item)
        key = title.casefold()
        if not title or key in seen_task_titles:
            continue
        seen_task_titles.add(key)
        due_at = (item.get("due_at") or item.get("due_date")) if isinstance(item, dict) else None
        item_person_ids = _resolve_person_ids_from_item(cur, workspace_id, item) or list(person_ids)
        item_company_ids = _resolve_company_ids_from_payload(cur, workspace_id, item) or list(company_ids)
        source_payload = _ai_source_payload("task", note, title, "action_item", item, project_ids, item_person_ids)
        task_id = _materialize_task(
            cur,
            note,
            title,
            "action_item",
            target_user_id,
            project_ids,
            item_person_ids,
            due_at,
            description=source_payload.get("description") or source_payload.get("summary"),
            status=str(source_payload.get("status") or "todo"),
            priority=source_payload.get("priority") or 3,
            company_ids=item_company_ids,
            source_confidence=_item_confidence(item),
            source_payload=source_payload,
        )
        if task_id:
            task_ids.append(task_id)
            created["tasks"] += 1

    if note_kind == "task":
        title = _note_title(note, "Task")
        if title.casefold() not in seen_task_titles:
            payload = _ai_source_payload("task", note, title, "note_task", {"title": title, "description": str(note.get("body") or "")[:2000], "confidence": 0.9}, project_ids, person_ids)
            task_id = _materialize_task(
                cur,
                note,
                title,
                "note_task",
                target_user_id,
                project_ids,
                person_ids,
                description=str(note.get("body") or "")[:2000],
                company_ids=company_ids,
                source_confidence=0.9,
                source_payload=payload,
            )
            if task_id:
                task_ids.append(task_id)
                created["tasks"] += 1

    meeting_ids: list[str] = []
    seen_meeting_titles: set[str] = set()
    if note_kind not in {"meeting", "call"}:
        for item in data.get("meetings", []):
            title = _memory_item_title(item, "")
            key = title.casefold()
            if not title or key in seen_meeting_titles:
                continue
            seen_meeting_titles.add(key)
            source_kind = f"ai_meeting:{key[:80]}"
            item_person_ids = _resolve_person_ids_from_item(cur, workspace_id, item) or list(person_ids)
            item_company_ids = _resolve_company_ids_from_payload(cur, workspace_id, item) or list(company_ids)
            meeting_id = _materialize_meeting(
                cur,
                note,
                item,
                target_user_id,
                project_ids,
                item_person_ids,
                source_kind,
                company_ids=item_company_ids,
                source_confidence=_item_confidence(item),
                source_payload=_ai_source_payload("meeting", note, title, source_kind, item, project_ids, item_person_ids),
            )
            if meeting_id:
                meeting_ids.append(meeting_id)
                created["meetings"] += 1

    if note_kind in {"meeting", "call"}:
        title = _note_title(note, "Meeting")
        item = {"title": title, "summary": str(note.get("body") or "")[:4000], "confidence": 0.9}
        meeting_id = _materialize_meeting(
            cur,
            note,
            item,
            target_user_id,
            project_ids,
            person_ids,
            note_kind,
            company_ids=company_ids,
            source_confidence=0.9,
            source_payload=_ai_source_payload("meeting", note, title, note_kind, item, project_ids, person_ids),
        )
        if meeting_id:
            meeting_ids.append(meeting_id)
            created["meetings"] += 1

    workflow_ids: list[str] = []
    seen_workflows: set[str] = set()
    for item in data.get("workflows", []):
        name = _memory_item_title(item, "")
        key = name.casefold()
        if not name or key in seen_workflows:
            continue
        seen_workflows.add(key)
        source_kind = f"ai_workflow:{key[:80]}"
        item_person_ids = _resolve_person_ids_from_item(cur, workspace_id, item) or list(person_ids)
        item_company_ids = _resolve_company_ids_from_payload(cur, workspace_id, item) or list(company_ids)
        workflow_id = _materialize_workflow(
            cur,
            note,
            item,
            target_user_id,
            project_ids,
            item_person_ids,
            task_ids,
            company_ids=item_company_ids,
            source_kind=source_kind,
            source_confidence=_item_confidence(item),
            source_payload=_ai_source_payload("workflow", note, name, source_kind, item, project_ids, item_person_ids),
        )
        if workflow_id:
            workflow_ids.append(workflow_id)
            created["workflows"] += 1

    seen_reports: set[str] = set()
    if note_kind != "report":
        for item in data.get("reports", []):
            title = _memory_item_title(item, "")
            key = title.casefold()
            if not title or key in seen_reports:
                continue
            seen_reports.add(key)
            source_kind = f"ai_report:{key[:80]}"
            item_person_ids = _resolve_person_ids_from_item(cur, workspace_id, item) or list(person_ids)
            item_company_ids = _resolve_company_ids_from_payload(cur, workspace_id, item) or list(company_ids)
            if _materialize_report(
                cur,
                note,
                item,
                target_user_id,
                project_ids,
                item_person_ids,
                task_ids,
                item_company_ids,
                meeting_ids,
                workflow_ids,
                [],
                source_kind,
                source_confidence=_item_confidence(item),
                source_payload=_ai_source_payload("report", note, title, source_kind, item, project_ids, item_person_ids),
            ):
                created["reports"] += 1

    if note_kind == "report":
        title = _note_title(note, "Report")
        item = {"title": title, "summary": str(note.get("body") or ""), "confidence": 0.9}
        if _materialize_report(
            cur,
            note,
            item,
            target_user_id,
            project_ids,
            person_ids,
            task_ids,
            company_ids,
            meeting_ids,
            workflow_ids,
            [],
            "report",
            source_confidence=0.9,
            source_payload=_ai_source_payload("report", note, title, "report", item, project_ids, person_ids),
        ):
            created["reports"] += 1

    return created


async def _process_extract(job: dict) -> None:
    note_id = str(job["note_id"])
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            note, people, projects, companies = _unpack_context(_load_context(cur, note_id))
            if note["is_personal"]:
                cur.execute("UPDATE notes SET ai_processing_status = 'skipped', ai_processing_error = NULL WHERE id = %s", (note_id,))
                conn.commit()
                _finish_job(str(job["id"]), "done")
                return
            cur.execute(
                """
                SELECT 1
                FROM note_projects np
                JOIN projects p ON p.id = np.project_id
                WHERE np.note_id = %s AND p.kind = 'personal'
                LIMIT 1
                """,
                (note_id,),
            )
            if cur.fetchone():
                cur.execute("UPDATE notes SET ai_processing_status = 'skipped', ai_processing_error = NULL WHERE id = %s", (note_id,))
                conn.commit()
                _finish_job(str(job["id"]), "done")
                return
        conn.commit()
    finally:
        put_conn(conn)

    data = await extract_entities(
        note["body"],
        [person["name"] for person in people],
        [project["name"] for project in projects if project["kind"] != "personal"],
        [company["name"] for company in companies],
    )
    embedding = await embed_text(note_embedding_text(note))

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            note, people, projects, companies = _unpack_context(_load_context(cur, note_id))
            target_user_id = str(job["target_user_id"] or note["created_by"])
            for item in data.get("people", []):
                name = str(item.get("name", "")).strip()
                confidence = float(item.get("confidence") or 0)
                if not name:
                    continue
                person, match_score = _best_match(name, people)
                effective_confidence = min(confidence, match_score) if person else confidence
                if person and effective_confidence >= 0.90:
                    cur.execute(
                        """
                        INSERT INTO note_people_links (note_id, person_id, state, confidence, source, source_user_id)
                        VALUES (%s, %s, 'auto_linked', %s, 'ai', %s)
                        ON CONFLICT (note_id, person_id) DO UPDATE
                          SET state = 'auto_linked', confidence = EXCLUDED.confidence, source = 'ai'
                        """,
                        (note_id, person["id"], effective_confidence, target_user_id),
                    )
                    _record_calibration(cur, str(job["id"]), note, effective_confidence, "accepted")
                elif effective_confidence >= 0.70:
                    _insert_review(
                        cur,
                        note,
                        target_user_id,
                        "person",
                        {"name": name, "matched_person_id": str(person["id"]) if person else None, "confidence": effective_confidence},
                    )
                else:
                    _record_calibration(cur, str(job["id"]), note, effective_confidence, "dropped")

            for item in data.get("projects", []):
                name = str(item.get("name", "")).strip()
                confidence = float(item.get("confidence") or 0)
                if not name:
                    continue
                project, match_score = _best_match(name, projects)
                if not project:
                    if confidence >= 0.70:
                        _insert_review(cur, note, target_user_id, "project", {"name": name, "confidence": confidence})
                    continue
                effective_confidence = min(confidence, match_score)
                if project["kind"] == "personal" or project["shared"] or effective_confidence < 0.90:
                    if effective_confidence >= 0.70:
                        _insert_review(
                            cur,
                            note,
                            target_user_id,
                            "project",
                            {"name": name, "matched_project_id": str(project["id"]), "confidence": effective_confidence},
                        )
                    continue
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (note_id,),
                )
                cur.execute(
                    """
                    INSERT INTO note_projects (note_id, project_id, linked_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (note_id, project["id"], target_user_id),
                )

            person_ids = _linked_person_ids(cur, note_id)
            project_ids = _linked_project_ids(cur, note_id)
            _enrich_company_links_from_context(
                cur,
                note,
                data,
                target_user_id,
                project_ids,
                person_ids,
                companies,
                str(job["id"]),
            )
            _enqueue_structured_memory_reviews(cur, note, data, target_user_id, person_ids)
            upsert_note_embedding(cur, note, embedding)

            suggested_title = str(data.get("note_title") or "").strip()
            if suggested_title and note.get("title_is_derived") and 0 < len(suggested_title) <= 80:
                cur.execute(
                    """
                    UPDATE notes
                    SET title = %s
                    WHERE id = %s
                      AND title_is_derived = true
                    """,
                    (suggested_title, note_id),
                )

            cur.execute(
                """
                UPDATE notes
                SET ai_processing_status = 'processed',
                    ai_processing_error = NULL,
                    ai_processed_at = now()
                WHERE id = %s
                """,
                (note_id,),
            )
        conn.commit()
        _finish_job(str(job["id"]), "done")
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


async def handle_job(job: dict) -> None:
    try:
        if job["kind"] in {"extract", "reprocess"} and job.get("note_id"):
            await _process_extract(job)
        elif job["kind"] == "briefing":
            await send_morning_briefing(job)
            _finish_job(str(job["id"]), "done")
        else:
            _finish_job(str(job["id"]), "done")
    except Exception as exc:
        logger.exception("job failed: %s", job.get("id"))
        error = str(exc)[:1000]
        attempts = int(job.get("attempts") or 0)
        if _is_retryable_exception(exc) and attempts < MAX_JOB_ATTEMPTS:
            delay = max(1, RETRY_BACKOFF_SECONDS) * attempts
            _retry_job(str(job["id"]), error, delay)
            logger.warning("job requeued after transient failure: %s delay=%ss attempt=%s", job.get("id"), delay, attempts)
            return
        _finish_job(str(job["id"]), "failed", error)
        if job.get("note_id"):
            _mark_note_failed(str(job["note_id"]), error)


async def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("NoteSnoop worker started")
    last_heartbeat = 0.0
    while not STOP.is_set():
        loop_time = asyncio.get_running_loop().time()
        if loop_time - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            _write_heartbeat()
            last_heartbeat = loop_time
        job = _claim_job()
        if not job:
            await asyncio.sleep(POLL_INTERVAL_S)
            continue
        await handle_job(job)
    logger.info("NoteSnoop worker stopped")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "enqueue-morning-briefings":
        print(enqueue_due_morning_briefings())
    else:
        asyncio.run(main())
