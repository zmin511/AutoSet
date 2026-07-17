import io
import json
import sqlite3
from pathlib import Path

import pytest

from set_app import set_app
from engine_db_write import (
    EngineDBWriteBusyError,
    safe_engine_db_write as real_safe_engine_db_write,
)


def _create_track_db(path: Path, *, genre: str = "House") -> None:
    connection = sqlite3.connect(path)
    connection.execute(
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
            lastEditTime TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO Track (
            id, filename, length, bitrate, bpmAnalyzed, key, rating,
            genre, artist, title, path, lastEditTime
        ) VALUES (1, 'track.mp3', 240.0, 320, 124.0, NULL, 80,
                  ?, 'Artist', 'Title', 'fake/track.mp3', 'old-edit-time')
        """,
        (genre,),
    )
    connection.commit()
    connection.close()


def _read_track(path: Path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return dict(connection.execute("SELECT * FROM Track WHERE id = 1").fetchone())
    finally:
        connection.close()


def _configure_update(tmp_path, monkeypatch, *, genre="House", file_result=None):
    db_path = tmp_path / "m.db"
    backup_dir = tmp_path / "backups"
    fake_audio_path = tmp_path / "audio" / "track.mp3"
    _create_track_db(db_path, genre=genre)
    calls = []
    if file_result is None:
        file_result = {
            "ok": True,
            "file_tags_updated": True,
            "file_tags_warning": None,
            "written_fields": ["genre", "autoset_styles"],
        }

    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", tmp_path / "music")
    monkeypatch.setattr(set_app, "safe_media_path", lambda _path: fake_audio_path)

    def record_file_tags(*args, **kwargs):
        calls.append((args, kwargs))
        return file_result

    monkeypatch.setattr(set_app, "_track_file_tag_result", record_file_tags)
    return db_path, backup_dir, fake_audio_path, calls, file_result


def test_update_genre_preserves_success_response_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "m.db"
    music_root = tmp_path / "music"
    fake_audio_path = tmp_path / "audio" / "track.mp3"
    _create_track_db(db_path)
    file_result = {
        "ok": True,
        "file_tags_updated": True,
        "file_tags_warning": None,
        "written_fields": ["genre", "autoset_styles"],
    }
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    monkeypatch.setattr(set_app, "safe_media_path", lambda _path: fake_audio_path)
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: file_result,
    )

    response = set_app.update_genre(1, "  Deep   House / Tech House  ")

    assert response == {
        "ok": True,
        "track": {
            "id": 1,
            "label": "Artist - Title",
            "artist": "Artist",
            "title": "Title",
            "filename": "track.mp3",
            "genre": "Deep House, Tech House",
            "bpm": 124.0,
            "camelot": "",
            "bitrate": 320,
            "rating": 4,
            "rating_raw": 80,
            "energy": None,
            "energy_rating": 0,
            "length": 240.0,
            "path": str(music_root / "fake" / "track.mp3"),
            "rel": "fake/track.mp3",
            "has_cue": False,
            "has_loop": False,
        },
        "engine_db_updated": True,
        "file_tags_updated": True,
        "file_tags_warning": None,
        "written_fields": ["genre", "autoset_styles"],
        "file_tag_result": file_result,
    }


def test_update_genre_updates_only_genre_and_last_edit_time_and_backs_up_old_value(
    tmp_path, monkeypatch
):
    db_path, backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )
    before = _read_track(db_path)
    monkeypatch.setattr(set_app, "_engine_now_str", lambda: "2026-07-17 17:00:00")
    safe_write_kwargs = []

    def inspect_safe_write(*args, **kwargs):
        safe_write_kwargs.append(kwargs)
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", inspect_safe_write)

    response = set_app.update_genre(1, "Tech House")

    after = _read_track(db_path)
    assert response["ok"] is True
    assert after["genre"] == "Tech House"
    assert after["lastEditTime"] == "2026-07-17 17:00:00"
    assert {
        key for key in after if after[key] != before[key]
    } == {"genre", "lastEditTime"}
    assert len(calls) == 1
    assert safe_write_kwargs == [{}]
    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0])
    try:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT genre FROM Track WHERE id = 1").fetchone()[0] == "House"
    finally:
        backup.close()


def test_genre_validation_error_creates_no_backup_or_file_tag_write(
    tmp_path, monkeypatch
):
    db_path, backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )

    with pytest.raises(ValueError, match="Genre is empty"):
        set_app.update_genre(1, "  / | ; ,  ")

    assert _read_track(db_path)["genre"] == "House"
    assert not backup_dir.exists()
    assert calls == []


def test_missing_track_preserves_error_without_backup_or_file_tag_write(
    tmp_path, monkeypatch
):
    db_path, backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )

    with pytest.raises(ValueError, match="^Track not found$"):
        set_app.update_genre(999, "Tech House")

    assert _read_track(db_path)["genre"] == "House"
    assert not backup_dir.exists()
    assert calls == []


def test_missing_database_is_not_created(tmp_path, monkeypatch):
    db_path = tmp_path / "missing" / "m.db"
    backup_dir = tmp_path / "backups"
    calls = []
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app, "safe_media_path", lambda _path: calls.append("media")
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: calls.append("tags"),
    )

    response = set_app.update_genre(1, "Tech House")

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert response["db_path"] == str(db_path)
    assert response["error"]
    assert "backup_path" not in response
    assert not db_path.exists()
    assert not backup_dir.exists()
    assert calls == []


def test_preflight_external_exclusive_lock_returns_structured_failure(
    tmp_path, monkeypatch
):
    db_path, backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app, "safe_media_path", lambda _path: calls.append("media")
    )
    locker = sqlite3.connect(db_path, timeout=0)
    locker.execute("BEGIN EXCLUSIVE")
    try:
        response = set_app.update_genre(1, "Tech House")
    finally:
        locker.rollback()
        locker.close()

    assert response["ok"] is False
    assert response["reason"] == "db_locked"
    assert response["db_path"] == str(db_path)
    assert response["error"]
    assert "backup_path" not in response
    assert _read_track(db_path)["genre"] == "House"
    assert not backup_dir.exists()
    assert calls == []


def test_preflight_corrupt_database_returns_integrity_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "corrupt.db"
    backup_dir = tmp_path / "backups"
    calls = []
    db_path.write_bytes(b"synthetic corrupt sqlite content")
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app, "safe_media_path", lambda _path: calls.append("media")
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: calls.append("tags"),
    )

    response = set_app.update_genre(1, "Tech House")

    assert response["ok"] is False
    assert response["reason"] == "integrity_check_failed"
    assert response["db_path"] == str(db_path)
    assert response["error"]
    assert "backup_path" not in response
    assert db_path.read_bytes() == b"synthetic corrupt sqlite content"
    assert not backup_dir.exists()
    assert calls == []


def test_backup_failure_prevents_update_and_file_tag_write(tmp_path, monkeypatch):
    db_path, backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )
    backup_dir.write_text("not a directory", encoding="utf-8")

    response = set_app.update_genre(1, "Tech House")

    assert response["ok"] is False
    assert response["reason"] == "backup_failed"
    assert response["db_path"] == str(db_path)
    assert "backup_path" not in response
    assert _read_track(db_path)["genre"] == "House"
    assert calls == []


def test_db_locked_prevents_update_and_file_tag_write(tmp_path, monkeypatch):
    db_path, backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )

    def lock_before_safe_write(*args, **kwargs):
        locker = sqlite3.connect(db_path, timeout=0)
        locker.execute("BEGIN IMMEDIATE")
        try:
            return real_safe_engine_db_write(*args, sqlite_timeout=0.01, **kwargs)
        finally:
            locker.rollback()
            locker.close()

    monkeypatch.setattr(set_app, "safe_engine_db_write", lock_before_safe_write)

    response = set_app.update_genre(1, "Tech House")

    assert response == {
        "ok": False,
        "reason": "db_locked",
        "error": "database is locked",
        "db_path": str(db_path),
    }
    assert _read_track(db_path)["genre"] == "House"
    assert not backup_dir.exists()
    assert calls == []


def test_write_busy_preserves_error_contract_and_skips_file_tags(
    tmp_path, monkeypatch
):
    db_path, backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )

    def write_busy(*_args, **_kwargs):
        raise EngineDBWriteBusyError("synthetic busy write")

    monkeypatch.setattr(set_app, "safe_engine_db_write", write_busy)

    response = set_app.update_genre(1, "Tech House")

    assert response == {
        "ok": False,
        "reason": "write_busy",
        "error": "synthetic busy write",
        "db_path": str(db_path),
    }
    assert _read_track(db_path)["genre"] == "House"
    assert not backup_dir.exists()
    assert calls == []


def test_exception_after_update_rolls_back_and_skips_file_tags(tmp_path, monkeypatch):
    db_path, _backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )

    def fail_after_callback(db, backup_dir, operation, callback, **kwargs):
        def wrapped_callback(connection, backup_path):
            callback(connection, backup_path)
            raise RuntimeError("synthetic callback failure")

        return real_safe_engine_db_write(
            db, backup_dir, operation, wrapped_callback, **kwargs
        )

    monkeypatch.setattr(set_app, "safe_engine_db_write", fail_after_callback)

    response = set_app.update_genre(1, "Tech House")

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert response["error"] == "synthetic callback failure"
    assert Path(response["backup_path"]).is_file()
    assert _read_track(db_path)["genre"] == "House"
    assert calls == []


def test_callback_rechecks_track_after_preflight(tmp_path, monkeypatch):
    db_path, _backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )

    def delete_before_safe_write(*args, **kwargs):
        connection = sqlite3.connect(db_path)
        connection.execute("DELETE FROM Track WHERE id = 1")
        connection.commit()
        connection.close()
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", delete_before_safe_write)

    response = set_app.update_genre(1, "Tech House")

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert response["error"] == "Track not found"
    assert Path(response["backup_path"]).is_file()
    assert calls == []


def test_file_tags_are_written_only_after_database_commit(tmp_path, monkeypatch):
    db_path, _backup_dir, fake_audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch
    )

    def observe_committed_genre(*args, **kwargs):
        connection = sqlite3.connect(db_path)
        try:
            committed_genre = connection.execute(
                "SELECT genre FROM Track WHERE id = 1"
            ).fetchone()[0]
        finally:
            connection.close()
        calls.append((args, kwargs, committed_genre))
        return {
            "ok": True,
            "file_tags_updated": True,
            "file_tags_warning": None,
            "written_fields": ["genre", "autoset_styles"],
        }

    monkeypatch.setattr(set_app, "_track_file_tag_result", observe_committed_genre)

    response = set_app.update_genre(1, "Tech House")

    assert response["ok"] is True
    assert len(calls) == 1
    args, kwargs, committed_genre = calls[0]
    assert args == (fake_audio_path,)
    assert kwargs["genre"] == "Tech House"
    assert committed_genre == "Tech House"


def test_file_tag_warning_does_not_rollback_committed_genre(tmp_path, monkeypatch):
    file_result = {
        "ok": False,
        "file_tags_updated": False,
        "file_tags_warning": "synthetic tag warning",
        "written_fields": [],
        "skipped_fields": ["genre", "autoset_styles"],
    }
    db_path, _backup_dir, _audio_path, calls, _file_result = _configure_update(
        tmp_path, monkeypatch, file_result=file_result
    )

    response = set_app.update_genre(1, "Tech House")

    assert _read_track(db_path)["genre"] == "Tech House"
    assert len(calls) == 1
    assert response["engine_db_updated"] is True
    assert response["file_tags_updated"] is False
    assert response["file_tags_warning"] == "synthetic tag warning"
    assert response["written_fields"] == []
    assert response["file_tag_result"] == file_result


def test_update_genre_endpoint_returns_http_500_for_safe_write_failure(
    monkeypatch
):
    result = {
        "ok": False,
        "reason": "write_busy",
        "error": "synthetic busy write",
        "db_path": "/synthetic/m.db",
    }
    payload = json.dumps({"track_id": 1, "genre": "Tech House"}).encode("utf-8")
    sent = []
    handler = object.__new__(set_app.Handler)
    handler.path = "/api/update-genre"
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    monkeypatch.setattr(set_app, "update_genre", lambda *_args: result)
    monkeypatch.setattr(
        set_app.Handler,
        "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )

    handler.do_POST()

    assert sent == [(result, 500)]
