"""Durable post-commit queue for audio tag writes.

Engine DB callers enqueue only after their database transaction commits. The
queue transaction is committed before an audio file is opened. Workers claim
jobs with an expiring lease so concurrent manual retries cannot write the same
job at the same time.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from engine_write_tags import write_audio_tags


PENDING = "pending"
PROCESSING = "processing"
COMPLETED = "completed"
SUPERSEDED = "superseded"
STATUSES = (PENDING, PROCESSING, COMPLETED, SUPERSEDED)
DEFAULT_LEASE_SECONDS = 300

_CREATE_TABLE_SQL = """
CREATE TABLE audio_tag_jobs (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    operation_type TEXT NOT NULL,
    track_id INTEGER,
    normalized_path TEXT NOT NULL,
    path_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'processing', 'completed', 'superseded')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    idempotency_key TEXT NOT NULL,
    claim_token TEXT,
    lease_expires_at TEXT,
    result_json TEXT
)
"""
_REQUIRED_COLUMNS = {
    "sequence",
    "id",
    "operation_type",
    "track_id",
    "normalized_path",
    "path_key",
    "payload_json",
    "status",
    "attempts",
    "last_error",
    "created_at",
    "updated_at",
    "completed_at",
    "idempotency_key",
    "claim_token",
    "lease_expires_at",
    "result_json",
}


def _now_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now_datetime()).isoformat(timespec="microseconds")


def _normalize_path(
    value: object,
    *,
    platform_name: str | None = None,
) -> tuple[str, str]:
    platform = platform_name or os.name
    raw = os.path.expanduser(str(value))
    if platform == "nt":
        normalized = ntpath.normpath(ntpath.abspath(raw))
        return normalized, ntpath.normcase(normalized)
    normalized = os.path.normpath(os.path.abspath(raw))
    return normalized, normalized


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


def _schema_is_current(connection: sqlite3.Connection) -> bool:
    table = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'audio_tag_jobs'"
    ).fetchone()
    if table is None:
        return False
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(audio_tag_jobs)")
    }
    return _REQUIRED_COLUMNS <= columns and "processing" in str(table["sql"] or "")


def _create_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS audio_tag_jobs_status_sequence "
        "ON audio_tag_jobs(status, sequence)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS audio_tag_jobs_path_sequence "
        "ON audio_tag_jobs(path_key, sequence)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS audio_tag_jobs_lease "
        "ON audio_tag_jobs(status, lease_expires_at)"
    )


def _migrate_or_create_schema(connection: sqlite3.Connection) -> None:
    if _schema_is_current(connection):
        _create_indexes(connection)
        connection.commit()
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        if _schema_is_current(connection):
            _create_indexes(connection)
            connection.commit()
            return
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audio_tag_jobs'"
        ).fetchone()
        if exists is None:
            connection.execute(_CREATE_TABLE_SQL)
        else:
            connection.execute(
                "ALTER TABLE audio_tag_jobs RENAME TO audio_tag_jobs_legacy"
            )
            legacy_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(audio_tag_jobs_legacy)"
                )
            }
            connection.execute(_CREATE_TABLE_SQL)
            optional = {
                "claim_token": "claim_token" if "claim_token" in legacy_columns else "NULL",
                "lease_expires_at": (
                    "lease_expires_at" if "lease_expires_at" in legacy_columns else "NULL"
                ),
                "result_json": "result_json" if "result_json" in legacy_columns else "NULL",
            }
            connection.execute(
                f"""
                INSERT INTO audio_tag_jobs (
                    sequence, id, operation_type, track_id, normalized_path,
                    path_key, payload_json, status, attempts, last_error,
                    created_at, updated_at, completed_at, idempotency_key,
                    claim_token, lease_expires_at, result_json
                )
                SELECT
                    sequence, id, operation_type, track_id, normalized_path,
                    path_key, payload_json,
                    CASE
                        WHEN status IN ('pending', 'processing', 'completed', 'superseded')
                        THEN status ELSE 'pending'
                    END,
                    attempts, last_error, created_at, updated_at, completed_at,
                    idempotency_key, {optional['claim_token']},
                    {optional['lease_expires_at']}, {optional['result_json']}
                FROM audio_tag_jobs_legacy
                """
            )
            connection.execute("DROP TABLE audio_tag_jobs_legacy")
        _create_indexes(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _connect(queue_path: object) -> sqlite3.Connection:
    path = Path(str(queue_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        _migrate_or_create_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _json_dict(value: object) -> dict[str, object] | None:
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


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
        "claim_token": row["claim_token"],
        "lease_expires_at": row["lease_expires_at"],
        "result": _json_dict(row["result_json"]),
    }


def enqueue_audio_tag_jobs(
    queue_path: object,
    jobs: Iterable[Mapping[str, object]],
    *,
    platform_name: str | None = None,
) -> list[dict[str, object]]:
    """Persist jobs and return one queue record for every input, in order."""
    prepared = []
    for input_index, source in enumerate(jobs):
        path, path_key = _normalize_path(
            source["path"],
            platform_name=platform_name,
        )
        payload = _canonical_payload(source.get("payload"))
        prepared.append(
            {
                "input_index": input_index,
                "id": str(source.get("id") or uuid.uuid4()),
                "operation_type": str(source.get("operation_type") or "unknown"),
                "track_id": source.get("track_id"),
                "path": path,
                "path_key": path_key,
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
    accepted: list[tuple[int, str, bool]] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        for item in prepared:
            existing = connection.execute(
                """
                SELECT id FROM audio_tag_jobs
                WHERE idempotency_key = ? AND status IN (?, ?, ?)
                ORDER BY sequence DESC LIMIT 1
                """,
                (item["idempotency_key"], PENDING, PROCESSING, COMPLETED),
            ).fetchone()
            if existing is not None:
                accepted.append((item["input_index"], existing["id"], False))
                continue
            timestamp = _timestamp()
            connection.execute(
                """
                UPDATE audio_tag_jobs
                SET status = ?, claim_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE path_key = ? AND (
                    status = ? OR (
                        status = ? AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                    )
                )
                """,
                (
                    SUPERSEDED,
                    timestamp,
                    item["path_key"],
                    PENDING,
                    PROCESSING,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO audio_tag_jobs (
                    id, operation_type, track_id, normalized_path, path_key,
                    payload_json, status, attempts, last_error, created_at,
                    updated_at, completed_at, idempotency_key, claim_token,
                    lease_expires_at, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, NULL, ?, NULL, NULL, NULL)
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
            accepted.append((item["input_index"], item["id"], True))
        connection.commit()
        ordered = []
        for input_index, job_id, inserted in accepted:
            row = connection.execute(
                "SELECT * FROM audio_tag_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            job = _row_to_job(row)
            job["input_index"] = input_index
            job["enqueued"] = inserted
            ordered.append(job)
        return ordered
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


def _candidate_jobs(
    queue_path: object,
    requested_ids: list[str],
) -> list[tuple[str, int]]:
    connection = _connect(queue_path)
    now = _timestamp()
    try:
        parameters: list[object] = [PENDING, PROCESSING, now]
        id_clause = ""
        if requested_ids:
            placeholders = ",".join("?" for _ in requested_ids)
            id_clause = f" AND id IN ({placeholders})"
            parameters.extend(requested_ids)
        rows = connection.execute(
            """
            SELECT id, attempts FROM audio_tag_jobs
            WHERE (
                status = ? OR (
                    status = ? AND lease_expires_at IS NOT NULL
                    AND lease_expires_at <= ?
                )
            )
            """
            + id_clause
            + " ORDER BY sequence",
            parameters,
        ).fetchall()
        return [(row["id"], int(row["attempts"])) for row in rows]
    finally:
        connection.close()


def _claim_job(
    queue_path: object,
    job_id: str,
    expected_attempts: int,
    *,
    lease_seconds: int,
) -> dict[str, object] | None:
    connection = _connect(queue_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT * FROM audio_tag_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        now_dt = _now_datetime()
        now = _timestamp(now_dt)
        if current is None or int(current["attempts"]) != expected_attempts:
            connection.rollback()
            return None
        claimable = current["status"] == PENDING or (
            current["status"] == PROCESSING
            and current["lease_expires_at"] is not None
            and current["lease_expires_at"] <= now
        )
        if not claimable:
            connection.rollback()
            return None
        active_older = connection.execute(
            """
            SELECT 1 FROM audio_tag_jobs
            WHERE path_key = ? AND id != ? AND status = ?
              AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
            LIMIT 1
            """,
            (current["path_key"], current["id"], PROCESSING, now),
        ).fetchone()
        if active_older:
            connection.rollback()
            return None
        newer = connection.execute(
            """
            SELECT 1 FROM audio_tag_jobs
            WHERE path_key = ? AND sequence > ?
              AND status IN (?, ?, ?)
            LIMIT 1
            """,
            (
                current["path_key"],
                current["sequence"],
                PENDING,
                PROCESSING,
                COMPLETED,
            ),
        ).fetchone()
        if newer:
            connection.execute(
                """
                UPDATE audio_tag_jobs
                SET status = ?, claim_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (SUPERSEDED, now, current["id"]),
            )
            connection.commit()
            return None
        token = uuid.uuid4().hex
        lease_expires_at = _timestamp(
            now_dt + timedelta(seconds=max(1, int(lease_seconds)))
        )
        updated = connection.execute(
            """
            UPDATE audio_tag_jobs
            SET status = ?, claim_token = ?, lease_expires_at = ?,
                attempts = attempts + 1, updated_at = ?
            WHERE id = ? AND attempts = ? AND (
                status = ? OR (
                    status = ? AND lease_expires_at IS NOT NULL
                    AND lease_expires_at <= ?
                )
            )
            """,
            (
                PROCESSING,
                token,
                lease_expires_at,
                now,
                current["id"],
                expected_attempts,
                PENDING,
                PROCESSING,
                now,
            ),
        )
        if updated.rowcount != 1:
            connection.rollback()
            return None
        connection.commit()
        claimed = connection.execute(
            "SELECT * FROM audio_tag_jobs WHERE id = ?",
            (current["id"],),
        ).fetchone()
        return _row_to_job(claimed)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _complete_claim(
    queue_path: object,
    job_id: str,
    claim_token: str,
    *,
    status: str,
    error: str | None,
    result: Mapping[str, object],
) -> bool:
    finished_at = _timestamp()
    result_json = json.dumps(
        dict(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    connection = _connect(queue_path)
    try:
        updated = connection.execute(
            """
            UPDATE audio_tag_jobs
            SET status = ?, last_error = ?, updated_at = ?, completed_at = ?,
                claim_token = NULL, lease_expires_at = NULL, result_json = ?
            WHERE id = ? AND status = ? AND claim_token = ?
            """,
            (
                status,
                error,
                finished_at,
                finished_at if status == COMPLETED else None,
                result_json,
                job_id,
                PROCESSING,
                claim_token,
            ),
        )
        connection.commit()
        return updated.rowcount == 1
    finally:
        connection.close()


def _jobs_by_id(queue_path: object, job_ids: Iterable[str]) -> dict[str, dict[str, object]]:
    unique_ids = list(dict.fromkeys(str(item) for item in job_ids))
    if not unique_ids:
        return {}
    connection = _connect(queue_path)
    try:
        placeholders = ",".join("?" for _ in unique_ids)
        rows = connection.execute(
            f"SELECT * FROM audio_tag_jobs WHERE id IN ({placeholders})",
            unique_ids,
        ).fetchall()
        return {row["id"]: _row_to_job(row) for row in rows}
    finally:
        connection.close()


def _fallback_result(job: Mapping[str, object]) -> dict[str, object]:
    stored = job.get("result")
    if isinstance(stored, dict):
        return stored
    if job.get("status") == COMPLETED:
        return {
            "ok": True,
            "file_tags_updated": False,
            "file_tags_warning": None,
            "written_fields": [],
        }
    if job.get("status") == PROCESSING:
        warning = "Audio tag write is already processing"
    else:
        warning = str(job.get("last_error") or "Audio tag write is pending")
    return {
        "ok": False,
        "file_tags_updated": False,
        "file_tags_warning": warning,
        "written_fields": [],
    }


def process_pending_audio_tag_jobs(
    queue_path: object,
    *,
    writer: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    backup_dir: object | None = None,
    music_root: object | None = None,
    job_ids: Iterable[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, object]:
    """Claim and attempt each eligible job at most once for this invocation."""
    requested_ids = list(dict.fromkeys(str(item) for item in (job_ids or [])))
    candidates = _candidate_jobs(queue_path, requested_ids)
    results = []
    for job_id, expected_attempts in candidates:
        job = _claim_job(
            queue_path,
            job_id,
            expected_attempts,
            lease_seconds=lease_seconds,
        )
        if job is None:
            continue
        try:
            if writer is None:
                if backup_dir is None or music_root is None:
                    raise ValueError(
                        "backup_dir and music_root are required for the default writer"
                    )
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
                error = str(
                    warning or result.get("error") or "Audio tag write failed"
                )
                final_status = PENDING
            else:
                error = None
                final_status = COMPLETED
        except Exception as exc:
            result = {
                "ok": False,
                "file_tags_updated": False,
                "file_tags_warning": str(exc),
                "written_fields": [],
            }
            error = str(exc)
            final_status = PENDING
        owned = _complete_claim(
            queue_path,
            str(job["id"]),
            str(job["claim_token"]),
            status=final_status,
            error=error,
            result=result,
        )
        current = _jobs_by_id(queue_path, [str(job["id"])]).get(str(job["id"]))
        results.append(
            {
                "id": job["id"],
                "path": job["path"],
                "status": current["status"] if current else final_status,
                "claim_completed": owned,
                "result": result,
            }
        )

    state = audio_tag_queue_status(queue_path)
    return {
        "ok": True,
        "attempted": len(results),
        "completed": sum(
            item["status"] == COMPLETED and item["claim_completed"]
            for item in results
        ),
        "pending": state["pending"],
        "processing": state["processing"],
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
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    platform_name: str | None = None,
) -> dict[str, object]:
    queued_jobs = enqueue_audio_tag_jobs(
        queue_path,
        jobs,
        platform_name=platform_name,
    )
    processed = process_pending_audio_tag_jobs(
        queue_path,
        writer=writer,
        backup_dir=backup_dir,
        music_root=music_root,
        job_ids=[str(job["id"]) for job in queued_jobs],
        lease_seconds=lease_seconds,
    )
    attempted_by_id = {item["id"]: item for item in processed["results"]}
    current_by_id = _jobs_by_id(
        queue_path,
        [str(job["id"]) for job in queued_jobs],
    )
    input_results = []
    for queued_job in queued_jobs:
        current = current_by_id[str(queued_job["id"])]
        attempted = attempted_by_id.get(str(queued_job["id"]))
        input_results.append(
            {
                "input_index": queued_job["input_index"],
                "id": queued_job["id"],
                "path": queued_job["path"],
                "status": current["status"],
                "result": (
                    attempted["result"]
                    if attempted is not None
                    else _fallback_result(current)
                ),
            }
        )
    processed["results"] = input_results
    processed["queued"] = sum(bool(job["enqueued"]) for job in queued_jobs)
    processed["reused"] = len(queued_jobs) - processed["queued"]
    processed["jobs"] = queued_jobs
    return processed


def audio_tag_queue_status(queue_path: object) -> dict[str, object]:
    path = Path(str(queue_path))
    if not path.exists():
        counts = {status: 0 for status in STATUSES}
    else:
        connection = _connect(path)
        try:
            counts = {status: 0 for status in STATUSES}
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM audio_tag_jobs GROUP BY status"
            ):
                counts[row["status"]] = int(row["count"])
        finally:
            connection.close()
    return {
        "ok": True,
        "pending": counts[PENDING],
        "processing": counts[PROCESSING],
        "completed": counts[COMPLETED],
        "superseded": counts[SUPERSEDED],
        "total": sum(counts.values()),
        "retry_queue_path": str(path),
    }
