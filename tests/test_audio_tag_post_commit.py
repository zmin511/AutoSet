import ast
import io
import json
import sqlite3
from pathlib import Path

from set_app import set_app
from audio_tag_post_commit import (
    audio_tag_queue_status,
    enqueue_audio_tag_jobs,
    process_pending_audio_tag_jobs,
    submit_audio_tag_jobs,
)
from engine_db_write import safe_engine_db_write as real_safe_engine_db_write


def _job(path, genre, *, track_id=1, operation="test"):
    return {
        "operation_type": operation,
        "track_id": track_id,
        "path": path,
        "payload": {
            "genre": genre,
            "bpm": 124.0,
            "key": "8A",
            "styles": genre,
            "rating": 4,
        },
    }


def _success(job):
    return {
        "ok": True,
        "file_tags_updated": True,
        "file_tags_warning": None,
        "written_fields": list(job["payload"]),
    }


def _queue_rows(queue_path):
    with sqlite3.connect(queue_path) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM audio_tag_jobs ORDER BY sequence"
            )
        ]


def test_job_is_committed_pending_before_audio_writer_runs(tmp_path):
    queue_path = tmp_path / "runtime" / "retry.sqlite3"
    audio_path = tmp_path / "audio" / "track.mp3"
    observations = []

    def observe(job):
        rows = _queue_rows(queue_path)
        observations.append((rows[0]["status"], rows[0]["attempts"], job["path"]))
        return _success(job)

    result = submit_audio_tag_jobs(
        queue_path,
        [_job(audio_path, "House")],
        writer=observe,
    )

    assert observations == [("pending", 1, str(audio_path))]
    assert result["queued"] == result["completed"] == 1
    assert _queue_rows(queue_path)[0]["status"] == "completed"


def test_failed_write_stays_pending_and_retry_completes_across_instances(tmp_path):
    queue_path = tmp_path / "runtime" / "retry.sqlite3"
    audio_path = tmp_path / "track.mp3"
    first = submit_audio_tag_jobs(
        queue_path,
        [_job(audio_path, "House")],
        writer=lambda _job: {
            "ok": False,
            "file_tags_updated": False,
            "file_tags_warning": "synthetic backup failure",
            "written_fields": [],
        },
    )

    assert first["pending"] == 1
    row = _queue_rows(queue_path)[0]
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["last_error"] == "synthetic backup failure"
    assert audio_tag_queue_status(Path(str(queue_path)))["pending"] == 1

    retried = process_pending_audio_tag_jobs(queue_path, writer=_success)

    assert retried["attempted"] == retried["completed"] == 1
    row = _queue_rows(queue_path)[0]
    assert row["status"] == "completed"
    assert row["attempts"] == 2
    assert row["completed_at"]


def test_one_file_failure_does_not_stop_remaining_jobs(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    calls = []

    def mixed(job):
        name = Path(job["path"]).name
        calls.append(name)
        if name == "one.mp3":
            raise PermissionError("locked")
        return _success(job)

    result = submit_audio_tag_jobs(
        queue_path,
        [
            _job(tmp_path / "one.mp3", "House", track_id=1),
            _job(tmp_path / "two.mp3", "Disco", track_id=2),
        ],
        writer=mixed,
    )

    assert calls == ["one.mp3", "two.mp3"]
    assert result["completed"] == 1
    assert result["pending"] == 1
    assert [row["status"] for row in _queue_rows(queue_path)] == [
        "pending",
        "completed",
    ]


def test_completed_job_is_idempotent_and_is_not_written_again(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    job = _job(tmp_path / "track.mp3", "House")
    calls = []

    def writer(item):
        calls.append(item["id"])
        return _success(item)

    submit_audio_tag_jobs(queue_path, [job], writer=writer)
    duplicate = submit_audio_tag_jobs(queue_path, [job], writer=writer)
    retried = process_pending_audio_tag_jobs(queue_path, writer=writer)

    assert len(calls) == 1
    assert duplicate["attempted"] == 0
    assert retried["attempted"] == 0
    assert len(_queue_rows(queue_path)) == 1


def test_newer_payload_supersedes_old_pending_for_same_file(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    audio_path = tmp_path / "track.mp3"
    old = enqueue_audio_tag_jobs(queue_path, [_job(audio_path, "House")])[0]
    new = enqueue_audio_tag_jobs(queue_path, [_job(audio_path, "Tech House")])[0]
    written = []

    result = process_pending_audio_tag_jobs(
        queue_path,
        writer=lambda job: written.append(job["payload"]["genre"]) or _success(job),
    )

    rows = _queue_rows(queue_path)
    assert old["id"] != new["id"]
    assert [row["status"] for row in rows] == ["superseded", "completed"]
    assert written == ["Tech House"]
    assert result["completed"] == 1


def test_empty_submission_does_not_create_runtime_queue(tmp_path, monkeypatch):
    queue_path = tmp_path / "runtime" / "retry.sqlite3"
    monkeypatch.setattr(set_app, "AUDIO_TAG_RETRY_QUEUE_PATH", queue_path)

    outcome, results = set_app._submit_post_commit_audio_tags([])

    assert outcome == {"ok": True, "queued": 0, "completed": 0, "pending": 0}
    assert results == []
    assert not queue_path.exists()
    assert set_app.audio_tag_retry_queue_status()["pending"] == 0
    assert not queue_path.exists()


def _create_update_db(path):
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE Track (
                id INTEGER PRIMARY KEY, filename TEXT, length REAL,
                bitrate INTEGER, bpmAnalyzed REAL, key INTEGER, rating INTEGER,
                genre TEXT, artist TEXT, title TEXT, path TEXT, lastEditTime TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO Track VALUES (
                1, 'track.mp3', 240, 320, 124, 1, 80, 'House',
                'Artist', 'Title', 'track.mp3', 'old'
            )
            """
        )


def test_update_genre_commits_db_then_enqueues_then_writes(tmp_path, monkeypatch):
    db_path = tmp_path / "m.db"
    queue_path = tmp_path / "runtime" / "retry.sqlite3"
    audio_path = tmp_path / "Music" / "track.mp3"
    _create_update_db(db_path)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(set_app, "AUDIO_TAG_RETRY_QUEUE_PATH", queue_path)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", tmp_path / "Music")
    monkeypatch.setattr(set_app, "safe_media_path", lambda _path: audio_path)
    observations = []

    def observe(_path, **_kwargs):
        with sqlite3.connect(db_path) as connection:
            genre = connection.execute("SELECT genre FROM Track WHERE id = 1").fetchone()[0]
        observations.append((genre, _queue_rows(queue_path)[0]["status"]))
        return {
            "ok": True,
            "file_tags_updated": True,
            "file_tags_warning": None,
            "written_fields": ["genre"],
        }

    monkeypatch.setattr(set_app, "_track_file_tag_result", observe)

    response = set_app.update_genre(1, "Tech House")

    assert response["ok"] is True
    assert observations == [("Tech House", "pending")]
    assert _queue_rows(queue_path)[0]["status"] == "completed"


def test_db_rollback_creates_no_queue_and_never_calls_audio_writer(tmp_path, monkeypatch):
    db_path = tmp_path / "m.db"
    queue_path = tmp_path / "runtime" / "retry.sqlite3"
    _create_update_db(db_path)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(set_app, "AUDIO_TAG_RETRY_QUEUE_PATH", queue_path)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", tmp_path / "Music")
    calls = []

    def fail_after_callback(db, backup_dir, operation, callback, **kwargs):
        def wrapped(connection, backup_path):
            callback(connection, backup_path)
            raise RuntimeError("rollback")

        return real_safe_engine_db_write(
            db, backup_dir, operation, wrapped, **kwargs
        )

    monkeypatch.setattr(set_app, "safe_engine_db_write", fail_after_callback)
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: calls.append("write"),
    )

    response = set_app.update_genre(1, "Tech House")

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert calls == []
    assert not queue_path.exists()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT genre FROM Track WHERE id = 1").fetchone()[0] == "House"


def test_queue_status_and_manual_retry_http_contracts(tmp_path, monkeypatch):
    queue_path = tmp_path / "retry.sqlite3"
    enqueue_audio_tag_jobs(queue_path, [_job(tmp_path / "track.mp3", "House")])
    monkeypatch.setattr(set_app, "AUDIO_TAG_RETRY_QUEUE_PATH", queue_path)
    sent = []
    monkeypatch.setattr(
        set_app.Handler,
        "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )

    get_handler = object.__new__(set_app.Handler)
    get_handler.path = "/api/audio-tag-retry-queue"
    get_handler.do_GET()
    assert sent[-1][1] == 200
    assert sent[-1][0]["ok"] is True
    assert sent[-1][0]["pending"] == 1

    monkeypatch.setattr(set_app, "_track_file_tag_result", lambda *_a, **_k: {
        "ok": True,
        "file_tags_updated": True,
        "file_tags_warning": None,
        "written_fields": ["genre"],
    })
    post_handler = object.__new__(set_app.Handler)
    post_handler.path = "/api/audio-tag-retry"
    payload = json.dumps({}).encode()
    post_handler.headers = {"Content-Length": str(len(payload))}
    post_handler.rfile = io.BytesIO(payload)
    post_handler.do_POST()
    assert sent[-1][1] == 200
    assert sent[-1][0]["attempted"] == sent[-1][0]["completed"] == 1
    assert sent[-1][0]["pending"] == 0


def test_startup_does_not_invoke_retry_queue_processing():
    tree = ast.parse(Path(set_app.__file__).read_text(encoding="utf-8"))
    main_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    names = {node.id for node in ast.walk(main_node) if isinstance(node, ast.Name)}

    assert "retry_pending_audio_tags" not in names
    assert "process_pending_audio_tag_jobs" not in names
