"""Durable post-commit queue for audio tag writes.

Engine DB callers enqueue only after their database transaction commits.  The
queue transaction is committed before any audio file is opened, so a failed or
interrupted tag write remains available for an explicit retry.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from engine_write_tags import write_audio_tags


PENDING = "pending"
COMPLETED = "completed"
SUPERSEDED = "superseded"
STATUSES = (PENDING, COMPLETED, SUPERSEDED)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _normalize_path(value: object) -> tuple[str, str]:
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(str(value))))
    return normalized, normalized.casefold()


def _canonical_payload(payload: Mapping[str, object] | None) -> dict[str, object]:
    source = dict(payload or {})
    return {
        "genre": source.get("genre"),
        "bpm": source.get("bpm"),
        "key": source.get("key"),
        "styles": source.get("styles"),
        "rating": source.get("rating"),
    }


def _idempotency_key(path_key: str, payload: Mapping[str, object]) -> str:
    body = json.dumps(
        {"path": path_key, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _connect(queue_path: object) -> sqlite3.Connection:
    path = Path(str(queue_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audio_tag_jobs (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL UNIQUE,
            operation_type TEXT NOT NULL,
            track_id INTEGER,
            normalized_path TEXT NOT NULL,
            path_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'superseded')),
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            idempotency_key TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS audio_tag_jobs_status_sequence "
        "ON audio_tag_jobs(status, sequence)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS audio_tag_jobs_path_sequence "
        "ON audio_tag_jobs(path_key, sequence)"
    )
    connection.commit()
    return connection


def _row_to_job(row: sqlite3.Row) -> dict[str, object]:
    return {
        "sequence": int(row["sequence"]),
        "id": row["id"],
        "operation_type": row["operation_type"],
        "track_id": row["track_id"],
        "path": row["normalized_path"],
        "payload": json.loads(row["payload_json"]),
        "status": row["status"],
        "attempts": int(row["attempts"]),
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "idempotency_key": row["idempotency_key"],
    }


def enqueue_audio_tag_jobs(
    queue_path: object,
    jobs: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Persist jobs and supersede older pending writes for the same file."""
    prepared = []
    for source in jobs:
        path, path_key = _normalize_path(source["path"])
        payload = _canonical_payload(source.get("payload"))
        prepared.append(
            {
                "id": str(source.get("id") or uuid.uuid4()),
                "operation_type": str(source.get("operation_type") or "unknown"),
                "track_id": source.get("track_id"),
                "path": path,
                "path_key": path_key,
                "payload": payload,
                "payload_json": json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
                "idempotency_key": str(
                    source.get("idempotency_key")
                    or _idempotency_key(path_key, payload)
                ),
            }
        )
    if not prepared:
        return []

    connection = _connect(queue_path)
    accepted_ids: list[str] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        for item in prepared:
            existing = connection.execute(
                """
                SELECT * FROM audio_tag_jobs
                WHERE idempotency_key = ? AND status IN (?, ?)
                ORDER BY sequence DESC LIMIT 1
                """,
                (item["idempotency_key"], PENDING, COMPLETED),
            ).fetchone()
            if existing is not None:
                accepted_ids.append(existing["id"])
                continue
            timestamp = _now()
            connection.execute(
                """
                UPDATE audio_tag_jobs
                SET status = ?, updated_at = ?
                WHERE path_key = ? AND status = ?
                """,
                (SUPERSEDED, timestamp, item["path_key"], PENDING),
            )
            connection.execute(
                """
                INSERT INTO audio_tag_jobs (
                    id, operation_type, track_id, normalized_path, path_key,
                    payload_json, status, attempts, last_error, created_at,
                    updated_at, completed_at, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, NULL, ?)
                """,
                (
                    item["id"],
                    item["operation_type"],
                    item["track_id"],
                    item["path"],
                    item["path_key"],
                    item["payload_json"],
                    PENDING,
                    timestamp,
                    timestamp,
                    item["idempotency_key"],
                ),
            )
            accepted_ids.append(item["id"])
        connection.commit()
        placeholders = ",".join("?" for _ in accepted_ids)
        rows = connection.execute(
            f"SELECT * FROM audio_tag_jobs WHERE id IN ({placeholders}) "
            "ORDER BY sequence",
            accepted_ids,
        ).fetchall()
        return [_row_to_job(row) for row in rows]
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _default_writer(
    job: Mapping[str, object],
    *,
    backup_dir: object,
    music_root: object,
) -> dict[str, object]:
    payload = dict(job.get("payload") or {})
    return write_audio_tags(
        job["path"],
        genre=payload.get("genre"),
        bpm=payload.get("bpm"),
        key=payload.get("key"),
        autoset_styles=payload.get("styles"),
        rating=payload.get("rating"),
        backup_dir=backup_dir,
        music_root=music_root,
    ).as_dict()


def process_pending_audio_tag_jobs(
    queue_path: object,
    *,
    writer: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    backup_dir: object | None = None,
    music_root: object | None = None,
    job_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    """Attempt pending jobs independently and never re-run completed jobs."""
    requested_ids = list(dict.fromkeys(str(item) for item in (job_ids or [])))
    connection = _connect(queue_path)
    try:
        if requested_ids:
            placeholders = ",".join("?" for _ in requested_ids)
            rows = connection.execute(
                f"SELECT * FROM audio_tag_jobs WHERE status = ? "
                f"AND id IN ({placeholders}) ORDER BY sequence",
                [PENDING, *requested_ids],
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM audio_tag_jobs WHERE status = ? ORDER BY sequence",
                (PENDING,),
            ).fetchall()
    finally:
        connection.close()

    results = []
    for original in rows:
        connection = _connect(queue_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM audio_tag_jobs WHERE id = ?",
                (original["id"],),
            ).fetchone()
            if current is None or current["status"] != PENDING:
                connection.rollback()
                continue
            newer = connection.execute(
                """
                SELECT 1 FROM audio_tag_jobs
                WHERE path_key = ? AND sequence > ?
                  AND status IN (?, ?)
                LIMIT 1
                """,
                (current["path_key"], current["sequence"], PENDING, COMPLETED),
            ).fetchone()
            if newer:
                connection.execute(
                    "UPDATE audio_tag_jobs SET status = ?, updated_at = ? WHERE id = ?",
                    (SUPERSEDED, _now(), current["id"]),
                )
                connection.commit()
                continue
            started_at = _now()
            connection.execute(
                """
                UPDATE audio_tag_jobs
                SET attempts = attempts + 1, updated_at = ?
                WHERE id = ?
                """,
                (started_at, current["id"]),
            )
            connection.commit()
            job = _row_to_job(current)
            job["attempts"] = int(current["attempts"]) + 1
        finally:
            connection.close()

        try:
            if writer is None:
                if backup_dir is None or music_root is None:
                    raise ValueError("backup_dir and music_root are required for the default writer")
                result = dict(
                    _default_writer(
                        job,
                        backup_dir=backup_dir,
                        music_root=music_root,
                    )
                )
            else:
                result = dict(writer(job))
            warning = result.get("file_tags_warning")
            if not result.get("ok") or warning:
                error = str(warning or result.get("error") or "Audio tag write failed")
                status = PENDING
            else:
                error = None
                status = COMPLETED
        except Exception as exc:
            result = {
                "ok": False,
                "file_tags_updated": False,
                "file_tags_warning": str(exc),
                "written_fields": [],
            }
            error = str(exc)
            status = PENDING

        finished_at = _now()
        connection = _connect(queue_path)
        try:
            connection.execute(
                """
                UPDATE audio_tag_jobs
                SET status = ?, last_error = ?, updated_at = ?, completed_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    status,
                    error,
                    finished_at,
                    finished_at if status == COMPLETED else None,
                    job["id"],
                    PENDING,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        results.append({"id": job["id"], "status": status, "result": result})

    state = audio_tag_queue_status(queue_path)
    return {
        "ok": True,
        "attempted": len(results),
        "completed": sum(item["status"] == COMPLETED for item in results),
        "pending": state["pending"],
        "results": results,
        "retry_queue_path": state["retry_queue_path"],
    }


def submit_audio_tag_jobs(
    queue_path: object,
    jobs: Iterable[Mapping[str, object]],
    *,
    writer: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    backup_dir: object | None = None,
    music_root: object | None = None,
) -> dict[str, object]:
    queued = enqueue_audio_tag_jobs(queue_path, jobs)
    processed = process_pending_audio_tag_jobs(
        queue_path,
        writer=writer,
        backup_dir=backup_dir,
        music_root=music_root,
        job_ids=[str(job["id"]) for job in queued],
    )
    processed["queued"] = len(queued)
    processed["jobs"] = queued
    return processed


def audio_tag_queue_status(queue_path: object) -> dict[str, object]:
    path = Path(str(queue_path))
    if not path.exists():
        return {
            "ok": True,
            "pending": 0,
            "completed": 0,
            "superseded": 0,
            "total": 0,
            "retry_queue_path": str(path),
        }
    connection = _connect(path)
    try:
        counts = {status: 0 for status in STATUSES}
        for row in connection.execute(
            "SELECT status, COUNT(*) AS count FROM audio_tag_jobs GROUP BY status"
        ):
            counts[row["status"]] = int(row["count"])
        return {
            "ok": True,
            "pending": counts[PENDING],
            "completed": counts[COMPLETED],
            "superseded": counts[SUPERSEDED],
            "total": sum(counts.values()),
            "retry_queue_path": str(path),
        }
    finally:
        connection.close()
