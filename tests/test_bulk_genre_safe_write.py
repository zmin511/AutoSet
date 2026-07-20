import io
import json
import sqlite3
from pathlib import Path

import pytest

import set_app.set_app as set_app
from engine_db_write import (
    EngineDBBackupError,
    EngineDBLockedError,
    EngineDBWriteBusyError,
    safe_engine_db_write as real_safe_engine_db_write,
)


def _create_track_db(db_path, tracks):
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE Track (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            length REAL,
            bitrate INTEGER,
            bpmAnalyzed REAL,
            key INTEGER,
            rating INTEGER,
            genre TEXT,
            artist TEXT,
            title TEXT,
            path TEXT,
            isAvailable INTEGER,
            lastEditTime TEXT,
            untouched TEXT
        );
        CREATE TABLE PerformanceData (
            trackId INTEGER,
            quickCues BLOB,
            loops BLOB
        );
        """
    )
    connection.executemany(
        """
        INSERT INTO Track (
            id, filename, length, bitrate, bpmAnalyzed, key, rating, genre,
            artist, title, path, isAvailable, lastEditTime, untouched
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        tracks,
    )
    connection.commit()
    connection.close()


def _track(track_id, filename, genre, *, last_edit="old-time", untouched="keep"):
    return (
        track_id,
        filename,
        240.0,
        320,
        124.0 + track_id,
        0,
        80,
        genre,
        f"Artist {track_id}",
        f"Title {track_id}",
        f"../Music/bulk/{filename}",
        last_edit,
        untouched,
    )


def _configure_bulk(tmp_path, monkeypatch, tracks):
    music_root = tmp_path / "Music"
    folder = music_root / "bulk"
    folder.mkdir(parents=True)
    for row in tracks:
        (folder / row[1]).write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "m.db"
    backup_dir = tmp_path / "backups"
    _create_track_db(db_path, tracks)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    return db_path, backup_dir, music_root, folder


def _read_tracks(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return {
            row["id"]: dict(row)
            for row in connection.execute("SELECT * FROM Track ORDER BY id")
        }
    finally:
        connection.close()


def _successful_tags(*_args, **_kwargs):
    return {"ok": True, "file_tags_warning": None}


def test_bulk_genre_preserves_success_response_contract(tmp_path, monkeypatch):
    tracks = [
        _track(1, "change.mp3", "House"),
        _track(2, "unchanged.mp3", "House, Tech House"),
    ]
    _db_path, _backup_dir, _music_root, folder = _configure_bulk(
        tmp_path, monkeypatch, tracks
    )
    (folder / "missing.mp3").write_bytes(b"synthetic audio placeholder")
    tag_calls = []

    def write_tags(path, **kwargs):
        tag_calls.append((path, kwargs))
        return {"ok": True, "file_tags_warning": None}

    monkeypatch.setattr(set_app, "_track_file_tag_result", write_tags)

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    missing_path = str(folder / "missing.mp3")
    assert response == {
        "ok": True,
        "updated": 1,
        "unchanged": 1,
        "file_written": 1,
        "file_failed": 0,
        "engine_db_updated": True,
        "file_tags_updated": True,
        "file_tags_warning": None,
        "written_fields": ["genre", "bpm", "key", "autoset_styles", "rating"],
        "missing": 1,
        "output": (
            "Genre tags updated for current folder.\n"
            "Audio files: 3\n"
            "Matched in Engine DB: 2\n"
            "Updated: 1\n"
            "Unchanged: 1\n"
            "File tags written: 1\n"
            "File tags skipped/failed: 0\n"
            "Not found in Engine DB: 1\n\n"
            f"Missing examples:\n- {missing_path}"
        ),
    }
    assert len(tag_calls) == 1
    assert tag_calls[0][0] == folder / "change.mp3"
    assert tag_calls[0][1]["genre"] == "House, Tech House"


@pytest.mark.parametrize(
    ("action", "kwargs", "expected"),
    [
        ("replace", {"find": "House", "replace": "Deep House"}, "Deep House, Disco"),
        ("remove", {"find": "House"}, "Disco"),
    ],
)
def test_bulk_genre_replace_and_remove(tmp_path, monkeypatch, action, kwargs, expected):
    db_path, _backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House, Disco")]
    )
    monkeypatch.setattr(set_app, "_track_file_tag_result", _successful_tags)

    response = set_app.bulk_update_genres("bulk", False, action, **kwargs)

    assert response["ok"] is True
    assert response["updated"] == 1
    assert _read_tracks(db_path)[1]["genre"] == expected


def test_bulk_updates_only_genre_and_last_edit_time_and_creates_one_valid_backup(
    tmp_path, monkeypatch
):
    tracks = [_track(1, "one.mp3", "House"), _track(2, "two.mp3", "Disco")]
    db_path, backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, tracks
    )
    before = _read_tracks(db_path)
    monkeypatch.setattr(set_app, "_engine_now_str", lambda: "2026-07-20 09:00:00")
    monkeypatch.setattr(set_app, "_track_file_tag_result", _successful_tags)

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    after = _read_tracks(db_path)
    assert response["updated"] == 2
    for track_id in (1, 2):
        changed_columns = {
            key for key, value in after[track_id].items() if value != before[track_id][key]
        }
        assert changed_columns == {"genre", "lastEditTime"}
        assert after[track_id]["lastEditTime"] == "2026-07-20 09:00:00"
    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    connection = sqlite3.connect(backups[0])
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute(
            "SELECT genre FROM Track ORDER BY id"
        ).fetchall() == [("House",), ("Disco",)]
    finally:
        connection.close()


def test_bulk_is_atomic_and_rollback_skips_all_audio_tags(tmp_path, monkeypatch):
    tracks = [_track(1, "one.mp3", "House"), _track(2, "two.mp3", "Disco")]
    db_path, backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, tracks
    )
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TRIGGER fail_second_bulk_update
        BEFORE UPDATE OF genre ON Track
        WHEN OLD.id = 2
        BEGIN
            SELECT RAISE(ABORT, 'synthetic second update failure');
        END
        """
    )
    connection.commit()
    connection.close()
    tag_calls = []
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: tag_calls.append("tags"),
    )

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert "synthetic second update failure" in response["error"]
    assert Path(response["backup_path"]).is_file()
    assert [row["genre"] for row in _read_tracks(db_path).values()] == ["House", "Disco"]
    assert len(list(backup_dir.glob("*.db"))) == 1
    assert tag_calls == []


def test_callback_rereads_current_genres_after_preflight(tmp_path, monkeypatch):
    db_path, _backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    tag_genres = []

    def mutate_before_safe_write(*args, **kwargs):
        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE Track SET genre = 'Disco' WHERE id = 1")
        connection.commit()
        connection.close()
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", mutate_before_safe_write)
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda _path, **kwargs: tag_genres.append(kwargs["genre"])
        or _successful_tags(),
    )

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["updated"] == 1
    assert _read_tracks(db_path)[1]["genre"] == "Disco, Tech House"
    assert tag_genres == ["Disco, Tech House"]


def test_track_removed_after_preflight_is_reported_missing(tmp_path, monkeypatch):
    tracks = [_track(1, "one.mp3", "House"), _track(2, "two.mp3", "Disco")]
    db_path, _backup_dir, _music_root, folder = _configure_bulk(
        tmp_path, monkeypatch, tracks
    )

    def delete_before_safe_write(*args, **kwargs):
        connection = sqlite3.connect(db_path)
        connection.execute("DELETE FROM Track WHERE id = 2")
        connection.commit()
        connection.close()
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", delete_before_safe_write)
    monkeypatch.setattr(set_app, "_track_file_tag_result", _successful_tags)

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["ok"] is True
    assert response["updated"] == 1
    assert response["missing"] == 1
    assert str(folder / "two.mp3") in response["output"]


def test_audio_tags_run_after_entire_batch_commit(tmp_path, monkeypatch):
    tracks = [_track(1, "one.mp3", "House"), _track(2, "two.mp3", "Disco")]
    db_path, _backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, tracks
    )
    observations = []

    def observe_committed_batch(path, **_kwargs):
        connection = sqlite3.connect(db_path)
        try:
            genres = connection.execute(
                "SELECT genre FROM Track ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        observations.append((path.name, genres))
        return _successful_tags()

    monkeypatch.setattr(set_app, "_track_file_tag_result", observe_committed_batch)

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["updated"] == 2
    assert observations == [
        ("one.mp3", [("House, Tech House",), ("Disco, Tech House",)]),
        ("two.mp3", [("House, Tech House",), ("Disco, Tech House",)]),
    ]


def test_audio_tag_failures_continue_and_do_not_rollback_database(tmp_path, monkeypatch):
    tracks = [
        _track(1, "one.mp3", "House"),
        _track(2, "two.mp3", "Disco"),
        _track(3, "three.mp3", "Trance"),
    ]
    db_path, _backup_dir, _music_root, folder = _configure_bulk(
        tmp_path, monkeypatch, tracks
    )
    calls = []

    def mixed_tag_results(path, **_kwargs):
        calls.append(path.name)
        if path.name == "one.mp3":
            return {"ok": False, "file_tags_warning": "synthetic warning"}
        if path.name == "two.mp3":
            raise RuntimeError("synthetic exception")
        return _successful_tags()

    monkeypatch.setattr(set_app, "_track_file_tag_result", mixed_tag_results)

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["ok"] is True
    assert response["updated"] == 3
    assert response["file_written"] == 1
    assert response["file_failed"] == 2
    assert response["file_tags_warning"] == (
        f"{folder / 'one.mp3'}: synthetic warning; "
        f"{folder / 'two.mp3'}: synthetic exception"
    )
    assert "File tag warnings:" in response["output"]
    assert calls == ["one.mp3", "three.mp3", "two.mp3"]
    assert all("Tech House" in row["genre"] for row in _read_tracks(db_path).values())


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (EngineDBWriteBusyError("synthetic busy"), "write_busy"),
        (EngineDBLockedError("synthetic lock"), "db_locked"),
        (EngineDBBackupError("synthetic backup"), "backup_failed"),
    ],
)
def test_structured_safe_write_errors_skip_audio_tags(
    tmp_path, monkeypatch, error, reason
):
    db_path, backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    tag_calls = []
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: (_ for _ in ()).throw(error)
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: tag_calls.append("tags"),
    )

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response == {
        "ok": False,
        "reason": reason,
        "error": str(error),
        "db_path": str(db_path),
    }
    assert not backup_dir.exists()
    assert tag_calls == []


def test_real_backup_failure_skips_database_and_audio_tags(tmp_path, monkeypatch):
    db_path, backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    backup_dir.write_text("not a directory", encoding="utf-8")
    tag_calls = []
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: tag_calls.append("tags"),
    )

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["reason"] == "backup_failed"
    assert "backup_path" not in response
    assert _read_tracks(db_path)[1]["genre"] == "House"
    assert tag_calls == []


def test_missing_database_is_not_created_and_preflight_stops_writes(tmp_path, monkeypatch):
    music_root = tmp_path / "Music"
    folder = music_root / "bulk"
    folder.mkdir(parents=True)
    (folder / "one.mp3").write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "missing" / "m.db"
    backup_dir = tmp_path / "backups"
    calls = []
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: calls.append("tags"),
    )

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["reason"] == "write_failed"
    assert "backup_path" not in response
    assert not db_path.exists()
    assert not backup_dir.exists()
    assert calls == []


def test_corrupt_database_returns_integrity_failure_before_safe_write(
    tmp_path, monkeypatch
):
    music_root = tmp_path / "Music"
    folder = music_root / "bulk"
    folder.mkdir(parents=True)
    (folder / "one.mp3").write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"synthetic corrupt sqlite content")
    calls = []
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: calls.append("tags"),
    )

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["reason"] == "integrity_check_failed"
    assert "backup_path" not in response
    assert calls == []


def test_exclusive_preflight_lock_returns_db_locked_and_stops_writes(
    tmp_path, monkeypatch
):
    db_path, backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    calls = []
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: calls.append("tags"),
    )
    locker = sqlite3.connect(db_path, timeout=0)
    locker.execute("BEGIN EXCLUSIVE")
    try:
        response = set_app.bulk_update_genres(
            "bulk", False, "append", tag="Tech House"
        )
    finally:
        locker.rollback()
        locker.close()

    assert response["reason"] == "db_locked"
    assert not backup_dir.exists()
    assert calls == []


def test_no_tracks_found_preserves_contract_without_backup(tmp_path, monkeypatch):
    db_path, backup_dir, _music_root, folder = _configure_bulk(tmp_path, monkeypatch, [])
    (folder / "missing.mp3").write_bytes(b"synthetic audio placeholder")

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response == {
        "ok": False,
        "updated": 0,
        "output": "No Engine DB tracks found in this folder.",
    }
    assert db_path.exists()
    assert not backup_dir.exists()


def test_no_actual_changes_creates_no_backup_and_writes_no_tags(
    tmp_path, monkeypatch
):
    _db_path, backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House, Tech House")]
    )
    calls = []
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: calls.append("tags"),
    )

    response = set_app.bulk_update_genres("bulk", False, "append", tag="Tech House")

    assert response["ok"] is True
    assert response["updated"] == 0
    assert response["unchanged"] == 1
    assert response["engine_db_updated"] is False
    assert not backup_dir.exists()
    assert calls == []


def test_invalid_input_creates_no_backup(tmp_path, monkeypatch):
    _db_path, backup_dir, _music_root, _folder = _configure_bulk(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )

    with pytest.raises(ValueError, match="Tag is empty"):
        set_app.bulk_update_genres("bulk", False, "append", tag=" / ; ")

    assert not backup_dir.exists()


@pytest.mark.parametrize(
    ("result", "status"),
    [
        (
            {
                "ok": False,
                "reason": "write_busy",
                "error": "synthetic busy",
                "db_path": "/synthetic/m.db",
            },
            500,
        ),
        (
            {
                "ok": False,
                "updated": 0,
                "output": "No Engine DB tracks found in this folder.",
            },
            200,
        ),
    ],
)
def test_bulk_genre_endpoint_status_contract(monkeypatch, result, status):
    payload = json.dumps(
        {"path": "bulk", "recursive": False, "action": "append", "tag": "Tech House"}
    ).encode("utf-8")
    sent = []
    handler = object.__new__(set_app.Handler)
    handler.path = "/api/bulk-genre"
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    monkeypatch.setattr(set_app, "bulk_update_genres", lambda *_args: result)
    monkeypatch.setattr(
        set_app.Handler,
        "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )

    handler.do_POST()

    assert sent == [(result, status)]
