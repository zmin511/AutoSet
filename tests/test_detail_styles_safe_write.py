import io
import json
import sqlite3
from pathlib import Path

import pytest

import set_app.set_app as set_app
from engine_db_write import (
    EngineDBBackupError,
    EngineDBLockedError,
    EngineDBOperationError,
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


def _track(track_id, filename, genre, *, subfolder="detail"):
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
        f"../Music/{subfolder}/{filename}",
        "old-time",
        "keep",
    )


def _configure_detail(tmp_path, monkeypatch, tracks, files=None):
    music_root = tmp_path / "Music"
    folder = music_root / "detail"
    folder.mkdir(parents=True)
    for filename in files or [row[1] for row in tracks]:
        path = folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "m.db"
    backup_dir = tmp_path / "backups"
    _create_track_db(db_path, tracks)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    monkeypatch.setattr(set_app, "LASTFM_API_KEY", "")
    return db_path, backup_dir, folder


def _decision_for_track(track, _path):
    if track["filename"] == "high.mp3":
        return {
            "additions": ["Tech House"],
            "new_genre": f'{track["genre"]}, Tech House',
            "confidence": "high",
            "reason": "synthetic high",
        }
    if track["filename"] == "low.mp3":
        return {
            "additions": ["Deep House"],
            "new_genre": f'{track["genre"]}, Deep House',
            "confidence": "low",
            "reason": "synthetic low",
        }
    return {
        "additions": [],
        "new_genre": track["genre"],
        "confidence": "low",
        "reason": "no suggestion",
    }


def _high_decision(track, _path=None):
    return {
        "additions": ["Tech House"],
        "new_genre": f'{track["genre"]}, Tech House',
        "confidence": "high",
        "reason": "synthetic high",
        "source": "Synthetic online",
    }


def _no_decision(track, _path=None):
    return {
        "additions": [],
        "new_genre": track["genre"],
        "confidence": "low",
        "reason": "no suggestion",
    }


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


def test_preview_preserves_response_contract(tmp_path, monkeypatch):
    tracks = [
        _track(1, "high.mp3", "House"),
        _track(2, "low.mp3", "House"),
        _track(3, "none.mp3", "Disco"),
    ]
    _db_path, _backup_dir, folder = _configure_detail(
        tmp_path,
        monkeypatch,
        tracks,
        files=["high.mp3", "low.mp3", "none.mp3", "missing.mp3"],
    )
    monkeypatch.setattr(set_app, "suggest_style_details", _decision_for_track)

    response = set_app.detail_folder_styles(
        "detail", apply=False, min_confidence="medium", source="local"
    )

    assert response == {
        "ok": True,
        "apply": False,
        "suggestions": [
            {
                "track_id": 1,
                "file": str(folder / "high.mp3"),
                "label": "Artist 1 - Title 1",
                "old_genre": "House",
                "additions": ["Tech House"],
                "new_genre": "House, Tech House",
                "confidence": "high",
                "reason": "synthetic high",
                "source": "AutoSet local",
                "action": "preview",
            },
            {
                "track_id": 2,
                "file": str(folder / "low.mp3"),
                "label": "Artist 2 - Title 2",
                "old_genre": "House",
                "additions": ["Deep House"],
                "new_genre": "House, Deep House",
                "confidence": "low",
                "reason": "synthetic low",
                "source": "AutoSet local",
                "action": "skipped_confidence",
            },
        ],
        "suggestion_count": 2,
        "updated": 0,
        "unchanged": 1,
        "skipped_confidence": 1,
        "missing": 1,
        "file_tags_updated": False,
        "file_tags_warning": None,
        "written_fields": [],
        "output": (
            "Style detail preview for current folder.\n"
            "Source: local AutoSet rules\n"
            "Online providers: Discogs + MusicBrainz (Last.fm API key not set)\n"
            "Audio files scanned: 4 of 4\n"
            "Matched in Engine DB: 3\n"
            "Tracks with suggestions: 2\n"
            "Updated: 0\n"
            "Already detailed/no suggestion: 1\n"
            "Skipped by confidence: 1\n"
            "File tags written: 0\n"
            "File tags skipped/failed: 0\n"
            "Not found in Engine DB: 1\n\n"
            "Examples:\n"
            "- Artist 1 - Title 1: + Tech House -> House, Tech House "
            "[AutoSet local; high; preview]\n"
            "- Artist 2 - Title 2: + Deep House -> House, Deep House "
            "[AutoSet local; low; skipped_confidence]\n\n"
            f"Missing examples:\n- {folder / 'missing.mp3'}"
        ),
    }


def test_apply_preserves_response_contract(tmp_path, monkeypatch):
    tracks = [_track(1, "high.mp3", "House")]
    _db_path, _backup_dir, folder = _configure_detail(tmp_path, monkeypatch, tracks)
    monkeypatch.setattr(set_app, "suggest_style_details", _decision_for_track)
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: {
            "ok": True,
            "file_tags_updated": True,
            "file_tags_warning": None,
            "written_fields": ["genre", "bpm", "key", "autoset_styles", "rating"],
        },
    )

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response["ok"] is True
    assert response["apply"] is True
    assert response["suggestion_count"] == 1
    assert response["updated"] == 1
    assert response["unchanged"] == 0
    assert response["skipped_confidence"] == 0
    assert response["missing"] == 0
    assert response["file_tags_updated"] is True
    assert response["file_tags_warning"] is None
    assert response["written_fields"] == [
        "genre",
        "bpm",
        "key",
        "autoset_styles",
        "rating",
    ]
    assert response["suggestions"] == [
        {
            "track_id": 1,
            "file": str(folder / "high.mp3"),
            "label": "Artist 1 - Title 1",
            "old_genre": "House",
            "additions": ["Tech House"],
            "new_genre": "House, Tech House",
            "confidence": "high",
            "reason": "synthetic high",
            "source": "AutoSet local",
            "action": "updated",
        }
    ]
    assert "Style detail applied for current folder." in response["output"]
    assert "Updated: 1" in response["output"]


@pytest.mark.parametrize("apply", [False, True])
def test_detail_styles_endpoint_success_status_contract(monkeypatch, apply):
    result = {"ok": True, "apply": apply}
    payload = json.dumps({"path": "detail", "apply": apply}).encode("utf-8")
    sent = []
    handler = object.__new__(set_app.Handler)
    handler.path = "/api/detail-styles"
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    monkeypatch.setattr(set_app, "detail_folder_styles", lambda *_args: result)
    monkeypatch.setattr(
        set_app.Handler,
        "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )

    handler.do_POST()

    assert sent == [(result, 200)]


def test_local_source_uses_only_local_suggester(tmp_path, monkeypatch):
    _db_path, _backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    calls = []
    monkeypatch.setattr(
        set_app,
        "suggest_style_details",
        lambda track, path: calls.append((track["id"], path.name)) or _high_decision(track),
    )
    monkeypatch.setattr(
        set_app,
        "suggest_online_style_details",
        lambda *_args: pytest.fail("online provider path must not run"),
    )

    response = set_app.detail_folder_styles("detail", apply=False, source="local")

    assert response["suggestion_count"] == 1
    assert response["suggestions"][0]["source"] == "AutoSet local"
    assert calls == [(1, "one.mp3")]


def test_online_source_is_fully_mocked_and_local_rules_are_not_used(tmp_path, monkeypatch):
    _db_path, _backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    calls = []
    monkeypatch.setattr(
        set_app,
        "suggest_online_style_details",
        lambda track: calls.append(track["id"]) or _high_decision(track),
    )
    monkeypatch.setattr(
        set_app,
        "suggest_style_details",
        lambda *_args: pytest.fail("local suggester must not run"),
    )

    response = set_app.detail_folder_styles("detail", apply=False, source="online")

    assert response["suggestion_count"] == 1
    assert response["suggestions"][0]["source"] == "Synthetic online"
    assert calls == [1]


def test_selected_files_and_min_confidence_filter_updates(tmp_path, monkeypatch):
    tracks = [_track(1, "high.mp3", "House"), _track(2, "low.mp3", "House")]
    db_path, _backup_dir, folder = _configure_detail(tmp_path, monkeypatch, tracks)
    monkeypatch.setattr(set_app, "suggest_style_details", _decision_for_track)
    monkeypatch.setattr(set_app, "_track_file_tag_result", _successful_tags)

    response = set_app.detail_folder_styles(
        "detail",
        apply=True,
        min_confidence="high",
        selected_files=[str(folder / "high.mp3"), str(folder / "low.mp3")],
        source="local",
    )

    assert response["updated"] == 1
    assert response["skipped_confidence"] == 1
    assert _read_tracks(db_path)[1]["genre"] == "House, Tech House"
    assert _read_tracks(db_path)[2]["genre"] == "House"


def test_selected_files_excludes_unselected_and_recursive_controls_scope(
    tmp_path, monkeypatch
):
    tracks = [
        _track(1, "root.mp3", "House"),
        _track(2, "nested.mp3", "House", subfolder="detail/nested"),
    ]
    _db_path, _backup_dir, folder = _configure_detail(
        tmp_path,
        monkeypatch,
        tracks,
        files=["root.mp3", "nested/nested.mp3"],
    )
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)

    flat = set_app.detail_folder_styles("detail", recursive=False, apply=False, source="local")
    selected = set_app.detail_folder_styles(
        "detail",
        recursive=True,
        apply=False,
        selected_files=[str(folder / "nested" / "nested.mp3")],
        source="local",
    )

    assert [item["track_id"] for item in flat["suggestions"]] == [1]
    assert [item["track_id"] for item in selected["suggestions"]] == [2]


@pytest.mark.parametrize("protected", ["Set", "Sets", "sets/nested"])
def test_protected_set_paths_are_rejected(tmp_path, monkeypatch, protected):
    music_root = tmp_path / "Music"
    (music_root / protected).mkdir(parents=True)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)

    with pytest.raises(ValueError, match="protected"):
        set_app.detail_folder_styles(protected, apply=True, source="local")


def test_preview_is_read_only_and_skips_safe_write_backup_and_tags(tmp_path, monkeypatch):
    db_path, backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    calls = []
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app, "_track_file_tag_result", lambda *_args, **_kwargs: calls.append("tags")
    )

    response = set_app.detail_folder_styles("detail", apply=False, source="local")

    assert response["suggestions"][0]["action"] == "preview"
    assert _read_tracks(db_path)[1]["genre"] == "House"
    assert not backup_dir.exists()
    assert calls == []


@pytest.mark.parametrize("decision", [_no_decision, _decision_for_track])
def test_apply_without_allowed_changes_creates_no_backup_or_tags(
    tmp_path, monkeypatch, decision
):
    filename = "one.mp3" if decision is _no_decision else "low.mp3"
    _db_path, backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, filename, "House")]
    )
    calls = []
    monkeypatch.setattr(set_app, "suggest_style_details", decision)
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app, "_track_file_tag_result", lambda *_args, **_kwargs: calls.append("tags")
    )

    response = set_app.detail_folder_styles(
        "detail", apply=True, min_confidence="high", source="local"
    )

    assert response["updated"] == 0
    assert not backup_dir.exists()
    assert calls == []


def test_apply_changes_only_genre_and_last_edit_and_creates_one_valid_backup(
    tmp_path, monkeypatch
):
    tracks = [_track(1, "one.mp3", "House"), _track(2, "two.mp3", "Disco")]
    db_path, backup_dir, _folder = _configure_detail(tmp_path, monkeypatch, tracks)
    before = _read_tracks(db_path)
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)
    monkeypatch.setattr(set_app, "_engine_now_str", lambda: "2026-07-20 11:00:00")
    monkeypatch.setattr(set_app, "_track_file_tag_result", _successful_tags)

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    after = _read_tracks(db_path)
    assert response["updated"] == 2
    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    for track_id in (1, 2):
        changed = {
            key for key, value in after[track_id].items() if value != before[track_id][key]
        }
        assert changed == {"genre", "lastEditTime"}
        assert after[track_id]["lastEditTime"] == "2026-07-20 11:00:00"
    connection = sqlite3.connect(backups[0])
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute(
            "SELECT genre FROM Track ORDER BY id"
        ).fetchall() == [("House",), ("Disco",)]
    finally:
        connection.close()


def test_callback_rereads_current_genre_and_preserves_concurrent_change(
    tmp_path, monkeypatch
):
    db_path, _backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    tag_genres = []
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)

    def mutate_before_write(*args, **kwargs):
        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE Track SET genre = 'Disco' WHERE id = 1")
        connection.commit()
        connection.close()
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", mutate_before_write)
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda _path, **kwargs: tag_genres.append(kwargs["genre"]) or _successful_tags(),
    )

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert _read_tracks(db_path)[1]["genre"] == "Disco, Tech House"
    assert response["suggestions"][0]["old_genre"] == "Disco"
    assert response["suggestions"][0]["new_genre"] == "Disco, Tech House"
    assert response["suggestions"][0]["action"] == "updated"
    assert tag_genres == ["Disco, Tech House"]


def test_addition_appearing_after_preflight_becomes_unchanged_without_tag_write(
    tmp_path, monkeypatch
):
    db_path, _backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    tag_calls = []
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)

    def mutate_before_write(*args, **kwargs):
        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE Track SET genre = 'House, Tech House' WHERE id = 1")
        connection.commit()
        connection.close()
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", mutate_before_write)
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: tag_calls.append("tags"),
    )

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response["updated"] == 0
    assert response["unchanged"] == 1
    assert response["suggestions"][0]["action"] == "unchanged"
    assert response["suggestions"][0]["old_genre"] == "House, Tech House"
    assert tag_calls == []


def test_track_removed_after_preflight_is_reported_missing(tmp_path, monkeypatch):
    db_path, _backup_dir, folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)

    def delete_before_write(*args, **kwargs):
        connection = sqlite3.connect(db_path)
        connection.execute("DELETE FROM Track WHERE id = 1")
        connection.commit()
        connection.close()
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", delete_before_write)
    monkeypatch.setattr(set_app, "_track_file_tag_result", _successful_tags)

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response["updated"] == 0
    assert response["missing"] == 1
    assert response["suggestions"][0]["action"] == "missing"
    assert response["suggestions"][0]["old_genre"] == ""
    assert response["suggestions"][0]["new_genre"] == ""
    assert str(folder / "one.mp3") in response["output"]


def test_multiple_updates_are_atomic_and_rollback_skips_all_tags(tmp_path, monkeypatch):
    tracks = [_track(1, "one.mp3", "House"), _track(2, "two.mp3", "Disco")]
    db_path, backup_dir, _folder = _configure_detail(tmp_path, monkeypatch, tracks)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TRIGGER fail_second_detail_update
        BEFORE UPDATE OF genre ON Track
        WHEN OLD.id = 2
        BEGIN
            SELECT RAISE(ABORT, 'synthetic second detail failure');
        END
        """
    )
    connection.commit()
    connection.close()
    tag_calls = []
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: tag_calls.append("tags"),
    )

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert "synthetic second detail failure" in response["error"]
    assert Path(response["backup_path"]).is_file()
    assert [row["genre"] for row in _read_tracks(db_path).values()] == ["House", "Disco"]
    assert len(list(backup_dir.glob("*.db"))) == 1
    assert tag_calls == []


def test_audio_tags_run_after_entire_batch_commit_and_preserve_parameter_format(
    tmp_path, monkeypatch
):
    tracks = [_track(1, "one.mp3", "House"), _track(2, "two.mp3", "Disco")]
    db_path, _backup_dir, _folder = _configure_detail(tmp_path, monkeypatch, tracks)
    observations = []
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)

    def observe_committed_batch(path, **kwargs):
        connection = sqlite3.connect(db_path)
        try:
            genres = connection.execute("SELECT genre FROM Track ORDER BY id").fetchall()
        finally:
            connection.close()
        observations.append((path.name, kwargs, genres))
        return _successful_tags()

    monkeypatch.setattr(set_app, "_track_file_tag_result", observe_committed_batch)

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    committed = [("House, Tech House",), ("Disco, Tech House",)]
    assert response["updated"] == 2
    assert [item[2] for item in observations] == [committed, committed]
    assert observations[0][1] == {
        "genre": "House, Tech House",
        "bpm": 125.0,
        "key": "8B",
        "rating": 80,
    }


def test_audio_tag_warning_and_exception_continue_without_database_rollback(
    tmp_path, monkeypatch
):
    tracks = [
        _track(1, "one.mp3", "House"),
        _track(2, "two.mp3", "Disco"),
        _track(3, "three.mp3", "Trance"),
    ]
    db_path, _backup_dir, folder = _configure_detail(tmp_path, monkeypatch, tracks)
    calls = []
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)

    def mixed_results(path, **_kwargs):
        calls.append(path.name)
        if path.name == "one.mp3":
            return {"ok": False, "file_tags_warning": "synthetic warning"}
        if path.name == "two.mp3":
            raise RuntimeError("synthetic exception")
        return _successful_tags()

    monkeypatch.setattr(set_app, "_track_file_tag_result", mixed_results)

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response["updated"] == 3
    assert response["file_tags_updated"] is True
    assert response["written_fields"] == [
        "genre", "bpm", "key", "autoset_styles", "rating"
    ]
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
        (EngineDBOperationError("synthetic write"), "write_failed"),
    ],
)
def test_structured_safe_write_errors_skip_audio_tags(
    tmp_path, monkeypatch, error, reason
):
    db_path, backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    tag_calls = []
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)
    monkeypatch.setattr(
        set_app,
        "safe_engine_db_write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: tag_calls.append("tags"),
    )

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response == {
        "ok": False,
        "reason": reason,
        "error": str(error),
        "db_path": str(db_path),
    }
    assert not backup_dir.exists()
    assert tag_calls == []


def test_real_backup_failure_skips_database_and_audio_tags(tmp_path, monkeypatch):
    db_path, backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    backup_dir.write_text("not a directory", encoding="utf-8")
    tag_calls = []
    monkeypatch.setattr(set_app, "suggest_style_details", _high_decision)
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: tag_calls.append("tags"),
    )

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response["reason"] == "backup_failed"
    assert "backup_path" not in response
    assert _read_tracks(db_path)[1]["genre"] == "House"
    assert tag_calls == []


def test_missing_database_is_not_created_and_preflight_stops_all_processing(
    tmp_path, monkeypatch
):
    music_root = tmp_path / "Music"
    folder = music_root / "detail"
    folder.mkdir(parents=True)
    (folder / "one.mp3").write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "missing" / "m.db"
    calls = []
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    monkeypatch.setattr(
        set_app, "suggest_style_details", lambda *_args: calls.append("suggest")
    )
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    monkeypatch.setattr(
        set_app, "_track_file_tag_result", lambda *_args, **_kwargs: calls.append("tags")
    )

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response["reason"] == "write_failed"
    assert "backup_path" not in response
    assert not db_path.exists()
    assert calls == []


def test_corrupt_database_returns_integrity_failure_before_suggestions_or_write(
    tmp_path, monkeypatch
):
    music_root = tmp_path / "Music"
    folder = music_root / "detail"
    folder.mkdir(parents=True)
    (folder / "one.mp3").write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"synthetic corrupt sqlite content")
    calls = []
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    monkeypatch.setattr(
        set_app, "suggest_style_details", lambda *_args: calls.append("suggest")
    )
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )

    response = set_app.detail_folder_styles("detail", apply=True, source="local")

    assert response["reason"] == "integrity_check_failed"
    assert "backup_path" not in response
    assert calls == []


def test_exclusive_preflight_lock_returns_db_locked_and_stops_processing(
    tmp_path, monkeypatch
):
    db_path, backup_dir, _folder = _configure_detail(
        tmp_path, monkeypatch, [_track(1, "one.mp3", "House")]
    )
    calls = []
    monkeypatch.setattr(
        set_app, "suggest_style_details", lambda *_args: calls.append("suggest")
    )
    monkeypatch.setattr(
        set_app, "safe_engine_db_write", lambda *_args, **_kwargs: calls.append("safe")
    )
    locker = sqlite3.connect(db_path, timeout=0)
    locker.execute("BEGIN EXCLUSIVE")
    try:
        response = set_app.detail_folder_styles("detail", apply=True, source="local")
    finally:
        locker.rollback()
        locker.close()

    assert response["reason"] == "db_locked"
    assert not backup_dir.exists()
    assert calls == []


def test_detail_styles_endpoint_returns_500_for_structured_error(monkeypatch):
    result = {
        "ok": False,
        "reason": "db_locked",
        "error": "synthetic lock",
        "db_path": "/synthetic/m.db",
    }
    payload = json.dumps({"path": "detail", "apply": True}).encode("utf-8")
    sent = []
    handler = object.__new__(set_app.Handler)
    handler.path = "/api/detail-styles"
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    monkeypatch.setattr(set_app, "detail_folder_styles", lambda *_args: result)
    monkeypatch.setattr(
        set_app.Handler,
        "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )

    handler.do_POST()

    assert sent == [(result, 500)]
