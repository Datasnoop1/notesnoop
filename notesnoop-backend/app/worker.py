from __future__ import annotations

import asyncio
import difflib
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
                  WHERE state = 'queued'
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
        (note["workspace_id"], target_user_id, entity_kind, note["id"], reason, payload),
    )


def _record_calibration(cur, job_id: str, note: dict, confidence: float, decision: str):
    cur.execute(
        """
        INSERT INTO calibration_events (ai_job_id, workspace_id, confidence, user_decision)
        VALUES (%s, %s, %s, %s)
        """,
        (job_id, note["workspace_id"], confidence, decision),
    )


async def _process_extract(job: dict) -> None:
    note_id = str(job["note_id"])
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            note, people, projects = _load_context(cur, note_id)
            if note["is_personal"]:
                cur.execute(
                    "UPDATE notes SET ai_processing_status = 'skipped' WHERE id = %s",
                    (note_id,),
                )
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
                cur.execute("UPDATE notes SET ai_processing_status = 'skipped' WHERE id = %s", (note_id,))
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

            upsert_note_embedding(cur, note, embedding)

            cur.execute(
                """
                UPDATE notes
                SET ai_processing_status = 'processed', ai_processed_at = now()
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
        _finish_job(str(job["id"]), "failed", str(exc)[:1000])


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
