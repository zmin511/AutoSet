from __future__ import annotations

import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import Iterable, Optional

from track_analysis import ANALYSIS_VERSION, TrackProfile, utc_now_iso


DEFAULT_ANALYSIS_DB_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "analysis.db"
)

_TRACK_PROFILE_COLUMNS = {
    field.name
    for field in fields(TrackProfile)
}


def open_analysis_db(
    db_path: str | Path = DEFAULT_ANALYSIS_DB_PATH,
) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")

    initialize_schema(connection)
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS track_analysis (
            track_id TEXT,
            file_path TEXT NOT NULL UNIQUE,
            file_size INTEGER,
            file_mtime REAL,
            analysis_version INTEGER NOT NULL,
            duration_seconds REAL,
            bpm REAL,
            camelot_key TEXT,
            genre TEXT,
            energy_mean REAL,
            energy_intro REAL,
            energy_peak REAL,
            energy_outro REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_track_analysis_track_id
            ON track_analysis(track_id);

        CREATE INDEX IF NOT EXISTS idx_track_analysis_version
            ON track_analysis(analysis_version);

        CREATE INDEX IF NOT EXISTS idx_track_analysis_updated_at
            ON track_analysis(updated_at);
        """
    )
    connection.commit()


def _row_to_profile(row: sqlite3.Row) -> TrackProfile:
    values = {
        name: row[name]
        for name in _TRACK_PROFILE_COLUMNS
        if name in row.keys()
    }
    return TrackProfile(**values)


def upsert_profile(
    connection: sqlite3.Connection,
    profile: TrackProfile,
) -> TrackProfile:
    now = utc_now_iso()
    created_at = profile.created_at or now

    connection.execute(
        """
        INSERT INTO track_analysis (
            track_id,
            file_path,
            file_size,
            file_mtime,
            analysis_version,
            duration_seconds,
            bpm,
            camelot_key,
            genre,
            energy_mean,
            energy_intro,
            energy_peak,
            energy_outro,
            created_at,
            updated_at
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(file_path) DO UPDATE SET
            track_id = excluded.track_id,
            file_size = excluded.file_size,
            file_mtime = excluded.file_mtime,
            analysis_version = excluded.analysis_version,
            duration_seconds = excluded.duration_seconds,
            bpm = excluded.bpm,
            camelot_key = excluded.camelot_key,
            genre = excluded.genre,
            energy_mean = excluded.energy_mean,
            energy_intro = excluded.energy_intro,
            energy_peak = excluded.energy_peak,
            energy_outro = excluded.energy_outro,
            updated_at = excluded.updated_at
        """,
        (
            profile.track_id,
            profile.file_path,
            profile.file_size,
            profile.file_mtime,
            profile.analysis_version,
            profile.duration_seconds,
            profile.bpm,
            profile.camelot_key,
            profile.genre,
            profile.energy_mean,
            profile.energy_intro,
            profile.energy_peak,
            profile.energy_outro,
            created_at,
            now,
        ),
    )
    connection.commit()

    stored = get_profile_by_path(
        connection,
        profile.file_path,
    )
    if stored is None:
        raise RuntimeError(
            f"Profile was not saved: {profile.file_path}"
        )
    return stored


def upsert_profiles(
    connection: sqlite3.Connection,
    profiles: Iterable[TrackProfile],
) -> int:
    count = 0
    for profile in profiles:
        upsert_profile(connection, profile)
        count += 1
    return count


def get_profile_by_path(
    connection: sqlite3.Connection,
    file_path: str,
) -> Optional[TrackProfile]:
    row = connection.execute(
        """
        SELECT
            track_id,
            file_path,
            file_size,
            file_mtime,
            analysis_version,
            duration_seconds,
            bpm,
            camelot_key,
            genre,
            energy_mean,
            energy_intro,
            energy_peak,
            energy_outro,
            created_at
        FROM track_analysis
        WHERE file_path = ?
        """,
        (file_path,),
    ).fetchone()

    if row is None:
        return None
    return _row_to_profile(row)


def get_profile_by_track_id(
    connection: sqlite3.Connection,
    track_id: str,
) -> Optional[TrackProfile]:
    row = connection.execute(
        """
        SELECT
            track_id,
            file_path,
            file_size,
            file_mtime,
            analysis_version,
            duration_seconds,
            bpm,
            camelot_key,
            genre,
            energy_mean,
            energy_intro,
            energy_peak,
            energy_outro,
            created_at
        FROM track_analysis
        WHERE track_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (str(track_id),),
    ).fetchone()

    if row is None:
        return None
    return _row_to_profile(row)


def list_profiles(
    connection: sqlite3.Connection,
    *,
    limit: Optional[int] = None,
) -> list[TrackProfile]:
    sql = """
        SELECT
            track_id,
            file_path,
            file_size,
            file_mtime,
            analysis_version,
            duration_seconds,
            bpm,
            camelot_key,
            genre,
            energy_mean,
            energy_intro,
            energy_peak,
            energy_outro,
            created_at
        FROM track_analysis
        ORDER BY file_path COLLATE NOCASE, track_id
    """
    parameters: tuple[int, ...] = ()

    if limit is not None:
        sql += " LIMIT ?"
        parameters = (max(0, int(limit)),)

    rows = connection.execute(
        sql,
        parameters,
    ).fetchall()

    return [
        _row_to_profile(row)
        for row in rows
    ]


def delete_profile_by_path(
    connection: sqlite3.Connection,
    file_path: str,
) -> bool:
    cursor = connection.execute(
        "DELETE FROM track_analysis WHERE file_path = ?",
        (file_path,),
    )
    connection.commit()
    return cursor.rowcount > 0


def profile_needs_analysis(
    connection: sqlite3.Connection,
    *,
    file_path: str,
    file_size: Optional[int],
    file_mtime: Optional[float],
    analysis_version: int = ANALYSIS_VERSION,
) -> bool:
    row = connection.execute(
        """
        SELECT
            file_size,
            file_mtime,
            analysis_version
        FROM track_analysis
        WHERE file_path = ?
        """,
        (file_path,),
    ).fetchone()

    if row is None:
        return True

    if int(row["analysis_version"]) != int(analysis_version):
        return True

    stored_size = row["file_size"]
    if stored_size != file_size:
        return True

    stored_mtime = row["file_mtime"]
    if stored_mtime is None and file_mtime is None:
        return False

    if stored_mtime is None or file_mtime is None:
        return True

    return abs(float(stored_mtime) - float(file_mtime)) > 0.000001
