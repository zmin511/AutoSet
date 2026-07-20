import io
import json
import sqlite3
import struct
import zlib

import pytest

import set_app.set_app as set_app
from engine_db_write import (
    EngineDBBackupError,
    EngineDBIntegrityError,
    EngineDBLockedError,
    EngineDBOperationError,
    EngineDBWriteBusyError,
    safe_engine_db_write as real_safe_engine_db_write,
)


def _waveform(level=128, points=4):
    raw = struct.pack(">4I", 1, points, 0, 0) + bytes([level, level, level]) * points
    return struct.pack(">I", len(raw)) + zlib.compress(raw)


def _create_db(path, tracks):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE Track (
            id INTEGER PRIMARY KEY, path TEXT, genre TEXT, bpmAnalyzed REAL,
            key INTEGER, rating INTEGER, isAvailable INTEGER, lastEditTime TEXT,
            untouched TEXT
        );
        CREATE TABLE PerformanceData (trackId INTEGER, overviewWaveFormData BLOB);
        """
    )
    for track in tracks:
        connection.execute(
            "INSERT INTO Track VALUES (?, ?, ?, ?, ?, ?, 1, 'old-time', 'keep')",
            track[:6],
        )
        if len(track) > 6 and track[6] is not None:
            connection.execute("INSERT INTO PerformanceData VALUES (?, ?)", (track[0], track[6]))
    connection.commit()
    connection.close()


def _configure(tmp_path, monkeypatch, tracks, files):
    music = tmp_path / "Music"
    music.mkdir()
    for filename in files:
        path = music / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "m.db"
    _create_db(db_path, tracks)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    return db_path, music


def _ok_tags(*_args, **_kwargs):
    return {"ok": True, "file_tags_warning": None}


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


def test_existing_success_response_contract_and_tag_arguments(tmp_path, monkeypatch):
    blob = _waveform(128)
    _db, music = _configure(
        tmp_path,
        monkeypatch,
        [(1, "../Music/folder/one.mp3", "House", 124.56, 0, 0, blob)],
        ["folder/one.mp3", "folder/missing.mp3"],
    )
    calls = []
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda path, **kwargs: calls.append((path, kwargs)) or _ok_tags(),
    )

    response = set_app.write_energy_ratings("folder")

    assert set(response) == {
        "ok", "updated", "matched", "skipped", "unchanged", "missing",
        "engine_db_updated", "file_tags_updated", "file_tags_warning",
        "written_fields", "output",
    }
    assert response["ok"] is True
    assert response["updated"] == response["matched"] == 1
    assert response["skipped"] == response["unchanged"] == 0
    assert response["missing"] == 1
    assert calls == [(str(music / "folder/one.mp3"), {
        "genre": "House", "bpm": 124.56, "key": 0, "rating": 3,
    })]


def test_existing_empty_response_contract(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, [], [])

    response = set_app.write_energy_ratings("")

    assert response == {
        "ok": True,
        "updated": 0,
        "matched": 0,
        "skipped": 0,
        "output": "No audio files in current folder.",
    }


def test_current_folder_is_not_recursive(tmp_path, monkeypatch):
    blob = _waveform()
    _db, _music = _configure(
        tmp_path, monkeypatch,
        [
            (1, "../Music/folder/root.mp3", "House", 120.0, 0, 0, blob),
            (2, "../Music/folder/nested/child.mp3", "House", 120.0, 0, 0, blob),
        ],
        ["folder/root.mp3", "folder/nested/child.mp3"],
    )
    monkeypatch.setattr(set_app, "_track_file_tag_result", _ok_tags)
    assert set_app.write_energy_ratings("folder")["matched"] == 1


def test_write_all_is_recursive_and_excludes_set_folders(tmp_path, monkeypatch):
    blob = _waveform()
    _db, _music = _configure(
        tmp_path, monkeypatch,
        [
            (1, "../Music/root.mp3", "House", 120.0, 0, 0, blob),
            (2, "../Music/nested/child.mp3", "House", 120.0, 0, 0, blob),
            (3, "../Music/Set/blocked.mp3", "House", 120.0, 0, 0, blob),
            (4, "../Music/Sets/nested/blocked.mp3", "House", 120.0, 0, 0, blob),
        ],
        ["root.mp3", "nested/child.mp3", "Set/blocked.mp3", "Sets/nested/blocked.mp3"],
    )
    monkeypatch.setattr(set_app, "_track_file_tag_result", _ok_tags)
    response = set_app.write_all_energy_ratings()
    assert response["matched"] == response["updated"] == 2
    assert "Music library" in response["output"]


@pytest.mark.parametrize("protected", ["Set", "Sets", "sets/nested"])
def test_selected_protected_set_folder_is_rejected(tmp_path, monkeypatch, protected):
    music = tmp_path / "Music"
    (music / protected).mkdir(parents=True)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music)
    with pytest.raises(ValueError, match="protected"):
        set_app.write_energy_ratings(protected)


def test_waveform_energy_to_stars_to_engine_rating(tmp_path, monkeypatch):
    blob = _waveform(128)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [(1, "../Music/one.mp3", "House", 120.0, 0, 0, blob)], ["one.mp3"],
    )
    ratings = []
    monkeypatch.setattr(
        set_app, "_track_file_tag_result",
        lambda _path, **kwargs: ratings.append(kwargs["rating"]) or _ok_tags(),
    )
    energy, stars = set_app._energy_from_overview_blob(blob)
    response = set_app.write_all_energy_ratings()
    with sqlite3.connect(db_path) as connection:
        engine_rating = connection.execute("SELECT rating FROM Track").fetchone()[0]
    assert energy == pytest.approx(0.5566)
    assert stars == 3
    assert engine_rating == set_app._stars_to_engine_rating(stars) == 60
    assert response["updated"] == 1
    assert ratings == [3]


@pytest.mark.parametrize(
    ("endpoint", "function_name"),
    [
        ("/api/write-energy-ratings", "write_energy_ratings"),
        ("/api/write-all-energy-ratings", "write_all_energy_ratings"),
    ],
)
def test_existing_endpoints_return_http_200(endpoint, function_name, monkeypatch):
    result = {"ok": True, "updated": 0, "matched": 0, "skipped": 0, "output": "empty"}
    payload = json.dumps({"path": "folder"}).encode()
    sent = []
    handler = object.__new__(set_app.Handler)
    handler.path = endpoint
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    monkeypatch.setattr(set_app, function_name, lambda *_args: result)
    monkeypatch.setattr(
        set_app.Handler, "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )
    handler.do_POST()
    assert sent == [(result, 200)]


def test_missing_skipped_and_unchanged_need_no_safe_write_or_backup(tmp_path, monkeypatch):
    blob = _waveform(128)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [
            (1, "../Music/folder/no-wave.mp3", "House", 120.0, 0, 0, None),
            (2, "../Music/folder/correct.mp3", "House", 121.0, 0, 60, blob),
        ],
        ["folder/no-wave.mp3", "folder/correct.mp3", "folder/missing.mp3"],
    )
    calls = []
    monkeypatch.setattr(set_app, "safe_engine_db_write", lambda *_a, **_k: calls.append("safe"))
    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: calls.append("tags"))

    response = set_app.write_energy_ratings("folder")

    assert response["matched"] == 2
    assert response["missing"] == response["skipped"] == response["unchanged"] == 1
    assert response["updated"] == 0
    assert response["engine_db_updated"] is False
    assert response["file_tags_updated"] is False
    assert response["written_fields"] == []
    assert calls == []
    assert not (tmp_path / "backups").exists()
    assert _read_tracks(db_path)[2]["rating"] == 60


def test_one_transaction_creates_one_valid_backup_with_old_ratings_and_only_changes_allowed_fields(
    tmp_path, monkeypatch
):
    blob = _waveform(128)
    tracks = [
        (1, "../Music/one.mp3", "House", 124.56, 0, 20, blob),
        (2, "../Music/two.mp3", "Disco", 126.78, 1, 100, blob),
    ]
    db_path, _music = _configure(tmp_path, monkeypatch, tracks, ["one.mp3", "two.mp3"])
    before = _read_tracks(db_path)
    calls = []

    def count_safe(*args, **kwargs):
        calls.append(args[2])
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", count_safe)
    monkeypatch.setattr(set_app, "_track_file_tag_result", _ok_tags)
    monkeypatch.setattr(set_app, "_engine_now_str", lambda: "2026-07-20 12:00:00")

    response = set_app.write_all_energy_ratings()

    after = _read_tracks(db_path)
    assert response["updated"] == 2
    assert calls == ["write_energy_ratings"]
    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT rating FROM Track ORDER BY id").fetchall() == [(20,), (100,)]
    for track_id in (1, 2):
        changed = {key for key, value in after[track_id].items() if value != before[track_id][key]}
        assert changed == {"rating", "lastEditTime"}
        assert after[track_id]["rating"] == 60
        assert after[track_id]["lastEditTime"] == "2026-07-20 12:00:00"


def test_callback_rereads_waveform_rating_and_tag_metadata_after_concurrent_change(
    tmp_path, monkeypatch
):
    original_blob = _waveform(128)
    current_blob = _waveform(250)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [(1, "../Music/one.mp3", "House", 120.0, 0, 0, original_blob)], ["one.mp3"],
    )
    tag_calls = []

    def mutate_before_write(*args, **kwargs):
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE Track SET rating = 20, genre = 'Techno', bpmAnalyzed = 132.25, key = 5 WHERE id = 1"
            )
            connection.execute(
                "UPDATE PerformanceData SET overviewWaveFormData = ? WHERE trackId = 1",
                (current_blob,),
            )
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", mutate_before_write)
    monkeypatch.setattr(
        set_app, "_track_file_tag_result",
        lambda path, **kwargs: tag_calls.append((path, kwargs)) or _ok_tags(),
    )
    response = set_app.write_all_energy_ratings()

    assert response["updated"] == 1
    assert _read_tracks(db_path)[1]["rating"] == 100
    assert tag_calls[0][1] == {"genre": "Techno", "bpm": 132.25, "key": 5, "rating": 5}


@pytest.mark.parametrize(
    ("mutation", "counter"),
    [
        ("DELETE FROM Track WHERE id = 1", "missing"),
        ("DELETE FROM PerformanceData WHERE trackId = 1", "skipped"),
        ("UPDATE Track SET rating = 60 WHERE id = 1", "unchanged"),
    ],
)
def test_callback_races_do_not_update_or_write_tags(tmp_path, monkeypatch, mutation, counter):
    blob = _waveform(128)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [(1, "../Music/one.mp3", "House", 120.0, 0, 0, blob)], ["one.mp3"],
    )
    tag_calls = []

    def mutate_before_write(*args, **kwargs):
        with sqlite3.connect(db_path) as connection:
            connection.execute(mutation)
        return real_safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", mutate_before_write)
    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: tag_calls.append("tag"))
    response = set_app.write_all_energy_ratings()
    assert response["updated"] == 0
    assert response[counter] == 1
    assert tag_calls == []


def test_partial_update_failure_rolls_back_entire_batch_keeps_backup_and_skips_tags(
    tmp_path, monkeypatch
):
    blob = _waveform(128)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [
            (1, "../Music/one.mp3", "House", 120.0, 0, 0, blob),
            (2, "../Music/two.mp3", "House", 120.0, 0, 0, blob),
        ], ["one.mp3", "two.mp3"],
    )
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TRIGGER fail_second_rating_update
            BEFORE UPDATE OF rating ON Track WHEN OLD.id = 2
            BEGIN SELECT RAISE(ABORT, 'synthetic second rating failure'); END;
            """
        )
    tags = []
    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: tags.append("tag"))
    response = set_app.write_all_energy_ratings()
    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert "synthetic second rating failure" in response["error"]
    assert response.get("backup_path") and set_app.Path(response["backup_path"]).is_file()
    assert [row["rating"] for row in _read_tracks(db_path).values()] == [0, 0]
    assert tags == []


def test_tags_run_after_batch_commit_and_each_connection_sees_all_ratings(
    tmp_path, monkeypatch
):
    blob = _waveform(128)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [
            (1, "../Music/one.mp3", "House", 124.56, 0, 0, blob),
            (2, "../Music/two.mp3", "Disco", 126.78, 1, 0, blob),
        ], ["one.mp3", "two.mp3"],
    )
    observations = []

    def observe(path, **kwargs):
        with sqlite3.connect(db_path) as connection:
            ratings = connection.execute("SELECT rating FROM Track ORDER BY id").fetchall()
        observations.append((path, kwargs, ratings))
        return _ok_tags()

    monkeypatch.setattr(set_app, "_track_file_tag_result", observe)
    response = set_app.write_all_energy_ratings()
    assert response["updated"] == 2
    assert [item[2] for item in observations] == [[(60,), (60,)], [(60,), (60,)]]
    assert observations[0][1] == {"genre": "House", "bpm": 124.56, "key": 0, "rating": 3}
    assert observations[1][1] == {"genre": "Disco", "bpm": 126.78, "key": 1, "rating": 3}


def test_tag_warning_and_exception_continue_without_database_rollback(tmp_path, monkeypatch):
    blob = _waveform(128)
    db_path, music = _configure(
        tmp_path, monkeypatch,
        [
            (1, "../Music/one.mp3", "House", 120.0, 0, 0, blob),
            (2, "../Music/two.mp3", "House", 120.0, 0, 0, blob),
            (3, "../Music/three.mp3", "House", 120.0, 0, 0, blob),
        ], ["one.mp3", "two.mp3", "three.mp3"],
    )
    calls = []

    def tags(path, **_kwargs):
        calls.append(set_app.Path(path).name)
        if path == str(music / "one.mp3"):
            return {"ok": False, "file_tags_warning": "synthetic warning"}
        if path == str(music / "two.mp3"):
            raise RuntimeError("synthetic exception")
        return _ok_tags()

    monkeypatch.setattr(set_app, "_track_file_tag_result", tags)
    response = set_app.write_all_energy_ratings()
    assert response["updated"] == 3
    assert response["file_tags_updated"] is True
    assert response["written_fields"] == ["genre", "bpm", "key", "autoset_styles", "rating"]
    assert "synthetic warning" in response["file_tags_warning"]
    assert "synthetic exception" in response["file_tags_warning"]
    assert "File tag warnings:" in response["output"]
    assert calls == ["one.mp3", "two.mp3", "three.mp3"]
    assert [row["rating"] for row in _read_tracks(db_path).values()] == [60, 60, 60]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (EngineDBWriteBusyError("synthetic busy"), "write_busy"),
        (EngineDBLockedError("synthetic lock"), "db_locked"),
        (EngineDBBackupError("synthetic backup"), "backup_failed"),
        (EngineDBIntegrityError("synthetic integrity"), "integrity_check_failed"),
        (EngineDBOperationError("synthetic write"), "write_failed"),
    ],
)
def test_structured_safe_write_errors_skip_tags(tmp_path, monkeypatch, error, reason):
    blob = _waveform(128)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [(1, "../Music/one.mp3", "House", 120.0, 0, 0, blob)], ["one.mp3"],
    )
    calls = []
    monkeypatch.setattr(
        set_app, "safe_engine_db_write",
        lambda *_a, **_k: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: calls.append("tag"))
    response = set_app.write_all_energy_ratings()
    assert response == {"ok": False, "reason": reason, "error": str(error), "db_path": str(db_path)}
    assert calls == []


def test_real_backup_failure_skips_database_and_tags(tmp_path, monkeypatch):
    blob = _waveform(128)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [(1, "../Music/one.mp3", "House", 120.0, 0, 0, blob)], ["one.mp3"],
    )
    (tmp_path / "backups").write_text("not a directory")
    calls = []
    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: calls.append("tag"))
    response = set_app.write_all_energy_ratings()
    assert response["reason"] == "backup_failed"
    assert "backup_path" not in response
    assert _read_tracks(db_path)[1]["rating"] == 0
    assert calls == []


def test_missing_database_is_not_created_and_preflight_stops_write_and_tags(tmp_path, monkeypatch):
    music = tmp_path / "Music"
    music.mkdir()
    (music / "one.mp3").write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "missing" / "m.db"
    calls = []
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(set_app, "safe_engine_db_write", lambda *_a, **_k: calls.append("safe"))
    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: calls.append("tag"))
    response = set_app.write_all_energy_ratings()
    assert response["reason"] == "write_failed"
    assert not db_path.exists()
    assert not (tmp_path / "backups").exists()
    assert calls == []


def test_corrupt_database_returns_integrity_failure_before_write_or_tags(tmp_path, monkeypatch):
    music = tmp_path / "Music"
    music.mkdir()
    (music / "one.mp3").write_bytes(b"synthetic audio placeholder")
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"synthetic corrupt sqlite content")
    calls = []
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(set_app, "safe_engine_db_write", lambda *_a, **_k: calls.append("safe"))
    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: calls.append("tag"))
    response = set_app.write_all_energy_ratings()
    assert response["reason"] == "integrity_check_failed"
    assert calls == []


def test_exclusive_preflight_lock_returns_db_locked_without_backup_or_tags(tmp_path, monkeypatch):
    blob = _waveform(128)
    db_path, _music = _configure(
        tmp_path, monkeypatch,
        [(1, "../Music/one.mp3", "House", 120.0, 0, 0, blob)], ["one.mp3"],
    )
    calls = []
    monkeypatch.setattr(set_app, "safe_engine_db_write", lambda *_a, **_k: calls.append("safe"))
    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: calls.append("tag"))
    locker = sqlite3.connect(db_path, timeout=0)
    locker.execute("BEGIN EXCLUSIVE")
    try:
        response = set_app.write_all_energy_ratings()
    finally:
        locker.rollback()
        locker.close()
    assert response["reason"] == "db_locked"
    assert not (tmp_path / "backups").exists()
    assert calls == []


@pytest.mark.parametrize(
    ("endpoint", "function_name"),
    [
        ("/api/write-energy-ratings", "write_energy_ratings"),
        ("/api/write-all-energy-ratings", "write_all_energy_ratings"),
    ],
)
def test_energy_endpoints_return_500_for_structured_errors(endpoint, function_name, monkeypatch):
    result = {"ok": False, "reason": "db_locked", "error": "synthetic", "db_path": "/m.db"}
    payload = json.dumps({"path": "folder"}).encode()
    sent = []
    handler = object.__new__(set_app.Handler)
    handler.path = endpoint
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    monkeypatch.setattr(set_app, function_name, lambda *_args: result)
    monkeypatch.setattr(
        set_app.Handler, "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )
    handler.do_POST()
    assert sent == [(result, 500)]
