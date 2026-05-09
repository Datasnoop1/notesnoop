from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import signal
import sys
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


def _load_context(cur, note_id: str) -> tuple[dict, list[dict], list[dict]]:
    cur.execute("SELECT * FROM notes WHERE id = %s", (note_id,))
    note = dict(cur.fetchone())
    cur.execute("SELECT * FROM people WHERE workspace_id = %s ORDER BY name", (note["workspace_id"],))
    people = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT * FROM projects WHERE workspace_id = %s ORDER BY name", (note["workspace_id"],))
    projects = [dict(row) for row in cur.fetchall()]
    return note, people, projects


def _insert_review(cur, note: dict, target_user_id: str, entity_kind: str, payload: dict[str, Any], reason: str = "ai_suggestion"):
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


def _link_memory_projects(cur, table: str, id_column: str, entity_id: str, workspace_id: str, project_ids: list[str], linked_by: str) -> None:
    for project_id in project_ids:
        cur.execute(
            f"""
            INSERT INTO {table} ({id_column}, project_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (entity_id, project_id, workspace_id, linked_by),
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


def _link_task_people(cur, task_id: str, workspace_id: str, person_ids: list[str], linked_by: str) -> None:
    for person_id in person_ids:
        cur.execute(
            """
            INSERT INTO task_people (task_id, person_id, workspace_id, relation, linked_by)
            VALUES (%s, %s, %s, 'assignee', %s)
            ON CONFLICT DO NOTHING
            """,
            (task_id, person_id, workspace_id, linked_by),
        )


def _link_meeting_people(cur, meeting_id: str, workspace_id: str, person_ids: list[str], linked_by: str) -> None:
    for person_id in person_ids:
        cur.execute(
            """
            INSERT INTO meeting_people (meeting_id, person_id, workspace_id, attendance_status, linked_by)
            VALUES (%s, %s, %s, 'attended', %s)
            ON CONFLICT DO NOTHING
            """,
            (meeting_id, person_id, workspace_id, linked_by),
        )


def _link_report_people(cur, report_id: str, workspace_id: str, person_ids: list[str], linked_by: str) -> None:
    for person_id in person_ids:
        cur.execute(
            """
            INSERT INTO report_people (report_id, person_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (report_id, person_id, workspace_id, linked_by),
        )


def _materialize_task(cur, note: dict, title: str, source_kind: str, target_user_id: str, project_ids: list[str], person_ids: list[str]) -> str | None:
    if not title:
        return None
    cur.execute(
        """
        INSERT INTO tasks (workspace_id, title, description, status, priority, created_by, source_note_id, source_kind)
        VALUES (%s, %s, %s, 'todo', 3, %s, %s, %s)
        ON CONFLICT (source_note_id, source_kind, lower(title))
          WHERE source_note_id IS NOT NULL
        DO UPDATE
          SET updated_at = now(),
              description = COALESCE(tasks.description, EXCLUDED.description)
        RETURNING id
        """,
        (
            note["workspace_id"],
            title,
            str(note.get("body") or "")[:2000],
            target_user_id,
            note["id"],
            source_kind,
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
    return task_id


def _materialize_ai_memory(cur, note: dict, data: dict[str, Any], target_user_id: str, person_ids: list[str] | None = None) -> dict[str, int]:
    note_id = str(note["id"])
    workspace_id = str(note["workspace_id"])
    note_kind = str(note.get("note_kind") or "note").lower()
    created = {"tasks": 0, "meetings": 0, "reports": 0}
    project_ids = _linked_project_ids(cur, note_id)
    person_ids = person_ids or _linked_person_ids(cur, note_id)

    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"memory:{note_id}",))

    seen_task_titles: set[str] = set()
    for item in data.get("tasks", []):
        title = _materialize_title(item)
        key = title.casefold()
        if not title or key in seen_task_titles:
            continue
        seen_task_titles.add(key)
        if _materialize_task(cur, note, title, "action_item", target_user_id, project_ids, person_ids):
            created["tasks"] += 1

    if note_kind == "task":
        title = _note_title(note, "Task")
        if title.casefold() not in seen_task_titles and _materialize_task(cur, note, title, "note_task", target_user_id, project_ids, person_ids):
            created["tasks"] += 1

    if note_kind in {"meeting", "call"}:
        cur.execute(
            """
            INSERT INTO meetings (workspace_id, title, occurred_at, summary, created_by, source_note_id, source_kind)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_note_id, source_kind)
              WHERE source_note_id IS NOT NULL
            DO UPDATE
              SET updated_at = now(),
                  summary = COALESCE(meetings.summary, EXCLUDED.summary),
                  occurred_at = COALESCE(meetings.occurred_at, EXCLUDED.occurred_at)
            RETURNING id
            """,
            (
                workspace_id,
                _note_title(note, "Meeting"),
                note.get("occurred_at"),
                str(note.get("body") or "")[:4000],
                target_user_id,
                note_id,
                note_kind,
            ),
        )
        meeting_id = str(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO meeting_notes (meeting_id, note_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (meeting_id, note_id, workspace_id, target_user_id),
        )
        _link_memory_projects(cur, "meeting_projects", "meeting_id", meeting_id, workspace_id, project_ids, target_user_id)
        _link_meeting_people(cur, meeting_id, workspace_id, person_ids, target_user_id)
        created["meetings"] += 1

    if note_kind == "report":
        cur.execute(
            """
            INSERT INTO reports (workspace_id, title, body, status, created_by, source_note_id, source_kind)
            VALUES (%s, %s, %s, 'draft', %s, %s, 'report')
            ON CONFLICT (source_note_id, source_kind)
              WHERE source_note_id IS NOT NULL
            DO UPDATE
              SET updated_at = now(),
                  body = COALESCE(reports.body, EXCLUDED.body)
            RETURNING id
            """,
            (workspace_id, _note_title(note, "Report"), note.get("body"), target_user_id, note_id),
        )
        report_id = str(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO report_notes (report_id, note_id, workspace_id, linked_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (report_id, note_id, workspace_id, target_user_id),
        )
        _link_memory_projects(cur, "report_projects", "report_id", report_id, workspace_id, project_ids, target_user_id)
        _link_report_people(cur, report_id, workspace_id, person_ids, target_user_id)
        created["reports"] += 1

    return created


async def _process_extract(job: dict) -> None:
    note_id = str(job["note_id"])
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            note, people, projects = _load_context(cur, note_id)
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
    )
    embedding = await embed_text(note_embedding_text(note))

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            note, people, projects = _load_context(cur, note_id)
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
            _materialize_ai_memory(cur, note, data, target_user_id, person_ids)
            upsert_note_embedding(cur, note, embedding)

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
    while not STOP.is_set():
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
