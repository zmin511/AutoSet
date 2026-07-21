import ast
import io
import json
import sqlite3
import threading
import time
from pathlib import Path

from set_app import set_app
import audio_tag_post_commit
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

    assert observations == [("processing", 1, str(audio_path))]
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
    assert observations == [("Tech House", "processing")]
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


def test_two_parallel_workers_execute_writer_exactly_once(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    queued = enqueue_audio_tag_jobs(
        queue_path,
        [_job(tmp_path / "track.mp3", "House")],
    )
    barrier = threading.Barrier(2)
    calls = []
    calls_lock = threading.Lock()
    outcomes = []

    def writer(job):
        with calls_lock:
            calls.append(job["claim_token"])
        time.sleep(0.05)
        return _success(job)

    def worker():
        barrier.wait()
        outcomes.append(
            process_pending_audio_tag_jobs(queue_path, writer=writer)
        )

    threads = [threading.Thread(target=worker) for _index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert sum(outcome["attempted"] for outcome in outcomes) == 1
    assert _queue_rows(queue_path)[0]["id"] == queued[0]["id"]
    assert _queue_rows(queue_path)[0]["status"] == "completed"


def test_expired_processing_job_is_reclaimed_after_simulated_crash(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    job = enqueue_audio_tag_jobs(
        queue_path,
        [_job(tmp_path / "track.mp3", "House")],
    )[0]
    with sqlite3.connect(queue_path) as connection:
        connection.execute(
            """
            UPDATE audio_tag_jobs
            SET status = 'processing', claim_token = 'crashed-worker',
                lease_expires_at = '2000-01-01T00:00:00.000000+00:00', attempts = 1
            WHERE id = ?
            """,
            (job["id"],),
        )
    tokens = []

    result = process_pending_audio_tag_jobs(
        queue_path,
        writer=lambda claimed: tokens.append(claimed["claim_token"])
        or _success(claimed),
    )

    row = _queue_rows(queue_path)[0]
    assert result["attempted"] == result["completed"] == 1
    assert tokens and tokens != ["crashed-worker"]
    assert row["status"] == "completed"
    assert row["attempts"] == 2
    assert row["claim_token"] is None
    assert row["lease_expires_at"] is None


def test_active_processing_lease_is_not_stolen(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    job = enqueue_audio_tag_jobs(
        queue_path,
        [_job(tmp_path / "track.mp3", "House")],
    )[0]
    with sqlite3.connect(queue_path) as connection:
        connection.execute(
            """
            UPDATE audio_tag_jobs
            SET status = 'processing', claim_token = 'active-worker',
                lease_expires_at = '2999-01-01T00:00:00.000000+00:00', attempts = 1
            WHERE id = ?
            """,
            (job["id"],),
        )
    calls = []

    result = process_pending_audio_tag_jobs(
        queue_path,
        writer=lambda claimed: calls.append(claimed) or _success(claimed),
    )

    row = _queue_rows(queue_path)[0]
    assert result["attempted"] == 0
    assert result["processing"] == 1
    assert calls == []
    assert row["status"] == "processing"
    assert row["claim_token"] == "active-worker"
    assert row["attempts"] == 1


def test_only_claim_owner_can_complete_processing_job(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    job = enqueue_audio_tag_jobs(
        queue_path,
        [_job(tmp_path / "track.mp3", "House")],
    )[0]
    claimed = audio_tag_post_commit._claim_job(
        queue_path,
        str(job["id"]),
        0,
        lease_seconds=300,
    )
    result = _success(claimed)

    assert audio_tag_post_commit._complete_claim(
        queue_path,
        str(job["id"]),
        "wrong-token",
        status="completed",
        error=None,
        result=result,
    ) is False
    assert _queue_rows(queue_path)[0]["status"] == "processing"
    assert audio_tag_post_commit._complete_claim(
        queue_path,
        str(job["id"]),
        str(claimed["claim_token"]),
        status="completed",
        error=None,
        result=result,
    ) is True
    assert _queue_rows(queue_path)[0]["status"] == "completed"


def test_reused_pending_and_completed_jobs_keep_input_result_order(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    completed_job = _job(tmp_path / "completed.mp3", "House", track_id=1)
    pending_job = _job(tmp_path / "pending.mp3", "Disco", track_id=2)
    submit_audio_tag_jobs(queue_path, [completed_job], writer=_success)
    submit_audio_tag_jobs(
        queue_path,
        [pending_job],
        writer=lambda _job: {
            "ok": False,
            "file_tags_updated": False,
            "file_tags_warning": "still locked",
            "written_fields": [],
        },
    )
    writes = []

    result = submit_audio_tag_jobs(
        queue_path,
        [pending_job, completed_job],
        writer=lambda job: writes.append(Path(job["path"]).name) or _success(job),
    )

    assert [Path(item["path"]).name for item in result["results"]] == [
        "pending.mp3",
        "completed.mp3",
    ]
    assert [item["input_index"] for item in result["results"]] == [0, 1]
    assert [item["status"] for item in result["results"]] == [
        "completed",
        "completed",
    ]
    assert writes == ["pending.mp3"]


def test_duplicate_idempotency_inputs_return_two_results_but_write_once(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    duplicate = _job(tmp_path / "track.mp3", "House")
    writes = []

    result = submit_audio_tag_jobs(
        queue_path,
        [duplicate, duplicate],
        writer=lambda job: writes.append(job["id"]) or _success(job),
    )

    assert result["queued"] == 1
    assert result["reused"] == 1
    assert result["attempted"] == 1
    assert len(result["results"]) == 2
    assert [item["input_index"] for item in result["results"]] == [0, 1]
    assert result["results"][0]["id"] == result["results"][1]["id"]
    assert len(writes) == 1


def test_file_warning_stays_attached_to_correct_input(tmp_path, monkeypatch):
    queue_path = tmp_path / "retry.sqlite3"
    monkeypatch.setattr(set_app, "AUDIO_TAG_RETRY_QUEUE_PATH", queue_path)
    jobs = [
        set_app._audio_tag_queue_job(
            "bulk_update_genres",
            tmp_path / "one.mp3",
            track_id=1,
            genre="House",
        ),
        set_app._audio_tag_queue_job(
            "bulk_update_genres",
            tmp_path / "two.mp3",
            track_id=2,
            genre="Disco",
        ),
    ]

    def tags(path, **_kwargs):
        warning = "two.mp3 is locked" if Path(path).name == "two.mp3" else None
        return {
            "ok": warning is None,
            "file_tags_updated": warning is None,
            "file_tags_warning": warning,
            "written_fields": ["genre"] if warning is None else [],
        }

    monkeypatch.setattr(set_app, "_track_file_tag_result", tags)

    outcome, file_results = set_app._submit_post_commit_audio_tags(jobs)

    assert [Path(item["path"]).name for item in outcome["results"]] == [
        "one.mp3",
        "two.mp3",
    ]
    assert file_results[0]["file_tags_warning"] is None
    assert file_results[1]["file_tags_warning"] == "two.mp3 is locked"


def test_linux_paths_are_case_sensitive_for_idempotency(tmp_path):
    queue_path = tmp_path / "linux.sqlite3"
    jobs = enqueue_audio_tag_jobs(
        queue_path,
        [
            _job(tmp_path / "Track.mp3", "House"),
            _job(tmp_path / "track.mp3", "House"),
        ],
        platform_name="posix",
    )

    assert len(jobs) == 2
    assert jobs[0]["id"] != jobs[1]["id"]
    assert len(_queue_rows(queue_path)) == 2


def test_windows_paths_are_case_insensitive_for_idempotency(tmp_path):
    queue_path = tmp_path / "windows.sqlite3"
    jobs = enqueue_audio_tag_jobs(
        queue_path,
        [
            _job(r"C:\Music\Track.mp3", "House"),
            _job(r"c:\music\track.mp3", "House"),
        ],
        platform_name="nt",
    )

    assert len(jobs) == 2
    assert jobs[0]["id"] == jobs[1]["id"]
    assert len(_queue_rows(queue_path)) == 1


def test_queue_database_failure_reports_unqueued_not_pending(tmp_path, monkeypatch):
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocked", encoding="utf-8")
    queue_path = blocked_parent / "retry.sqlite3"
    monkeypatch.setattr(set_app, "AUDIO_TAG_RETRY_QUEUE_PATH", queue_path)
    writes = []
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: writes.append("write"),
    )
    jobs = [
        set_app._audio_tag_queue_job(
            "update_genre",
            tmp_path / "track.mp3",
            track_id=1,
            genre="House",
        )
    ]

    outcome, file_results = set_app._submit_post_commit_audio_tags(jobs)

    assert outcome["ok"] is False
    assert outcome["queued"] == 0
    assert outcome["pending"] == 0
    assert outcome["unqueued"] == 1
    assert "queue" in outcome["queue_error"].casefold()
    assert file_results[0]["file_tags_warning"] == outcome["queue_error"]
    assert writes == []


def test_queue_transaction_failure_rolls_back_and_never_calls_writer(
    tmp_path, monkeypatch
):
    queue_path = tmp_path / "retry.sqlite3"
    monkeypatch.setattr(set_app, "AUDIO_TAG_RETRY_QUEUE_PATH", queue_path)
    real_connect = audio_tag_post_commit._connect
    writes = []

    class FailingTransaction:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, parameters=()):
            if "INSERT INTO audio_tag_jobs" in sql:
                raise sqlite3.OperationalError("synthetic transaction failure")
            return self.connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(
        audio_tag_post_commit,
        "_connect",
        lambda path: FailingTransaction(real_connect(path)),
    )
    monkeypatch.setattr(
        set_app,
        "_track_file_tag_result",
        lambda *_args, **_kwargs: writes.append("write"),
    )

    outcome, file_results = set_app._submit_post_commit_audio_tags(
        [
            set_app._audio_tag_queue_job(
                "update_genre",
                tmp_path / "track.mp3",
                track_id=1,
                genre="House",
            )
        ]
    )

    assert outcome["queued"] == outcome["completed"] == outcome["pending"] == 0
    assert outcome["unqueued"] == 1
    assert "synthetic transaction failure" in outcome["queue_error"]
    assert file_results[0]["file_tags_warning"] == outcome["queue_error"]
    assert writes == []
    with sqlite3.connect(queue_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audio_tag_jobs").fetchone()[0] == 0


def test_stale_owner_cannot_complete_after_expired_job_is_reclaimed(tmp_path):
    queue_path = tmp_path / "retry.sqlite3"
    job = enqueue_audio_tag_jobs(
        queue_path,
        [_job(tmp_path / "track.mp3", "House")],
    )[0]
    first = audio_tag_post_commit._claim_job(
        queue_path,
        str(job["id"]),
        0,
        lease_seconds=300,
    )
    with sqlite3.connect(queue_path) as connection:
        connection.execute(
            "UPDATE audio_tag_jobs SET lease_expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00.000000+00:00", job["id"]),
        )
    second = audio_tag_post_commit._claim_job(
        queue_path,
        str(job["id"]),
        1,
        lease_seconds=300,
    )

    assert first["claim_token"] != second["claim_token"]
    assert audio_tag_post_commit._complete_claim(
        queue_path,
        str(job["id"]),
        str(first["claim_token"]),
        status="completed",
        error=None,
        result=_success(first),
    ) is False
    assert _queue_rows(queue_path)[0]["claim_token"] == second["claim_token"]
    assert audio_tag_post_commit._complete_claim(
        queue_path,
        str(job["id"]),
        str(second["claim_token"]),
        status="completed",
        error=None,
        result=_success(second),
    ) is True


def test_legacy_queue_migration_preserves_jobs_and_rebuilds_path_identity(tmp_path):
    queue_path = tmp_path / "legacy.sqlite3"
    track_path = tmp_path / "Music" / "Track.mp3"
    payload_json = json.dumps(_job(track_path, "House")["payload"])
    with sqlite3.connect(queue_path) as connection:
        connection.execute(
            """
            CREATE TABLE audio_tag_jobs (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                operation_type TEXT NOT NULL,
                track_id INTEGER,
                normalized_path TEXT NOT NULL,
                path_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending', 'completed', 'superseded')
                ),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                idempotency_key TEXT NOT NULL
            )
            """
        )
        for job_id, status in (("pending-id", "pending"), ("completed-id", "completed")):
            connection.execute(
                """
                INSERT INTO audio_tag_jobs (
                    id, operation_type, track_id, normalized_path, path_key,
                    payload_json, status, created_at, updated_at, idempotency_key
                ) VALUES (?, 'test', 1, ?, ?, ?, ?, 'created', 'updated', ?)
                """,
                (
                    job_id,
                    str(track_path),
                    str(track_path).casefold(),
                    payload_json,
                    status,
                    f"key-{job_id}",
                ),
            )

    expected_path, expected_path_key = audio_tag_post_commit._normalize_path(track_path)
    status = audio_tag_queue_status(queue_path)
    rows = _queue_rows(queue_path)

    assert status["pending"] == status["completed"] == 1
    assert [row["id"] for row in rows] == ["pending-id", "completed-id"]
    assert all(row["normalized_path"] == expected_path for row in rows)
    assert all(row["path_key"] == expected_path_key for row in rows)
    with sqlite3.connect(queue_path) as connection:
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert indexes >= {
        "audio_tag_jobs_status_sequence",
        "audio_tag_jobs_path_sequence",
        "audio_tag_jobs_lease",
    }


def test_empty_submit_does_not_process_or_create_queue(tmp_path):
    queue_path = tmp_path / "runtime" / "retry.sqlite3"

    outcome = submit_audio_tag_jobs(queue_path, [], writer=_success)

    assert outcome["results"] == []
    assert outcome["attempted"] == outcome["queued"] == outcome["pending"] == 0
    assert not queue_path.exists()
