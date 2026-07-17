import sqlite3
import threading
from pathlib import Path

import pytest

from set_app import set_app
import engine_db_write  # noqa: E402
from engine_db_write import (  # noqa: E402
    EngineDBBackupError,
    EngineDBLockedError,
    EngineDBWriteBusyError,
    EngineDBWriteError,
    safe_engine_db_write,
)


def _create_db(path: Path, value: str = "original") -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO sample VALUES (1, ?)", (value,))
    connection.commit()
    connection.close()


def _read_value(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT value FROM sample WHERE id = 1").fetchone()[0]
    finally:
        connection.close()


def _write_value(connection: sqlite3.Connection, _backup: Path) -> str:
    connection.execute("UPDATE sample SET value = 'changed' WHERE id = 1")
    return "written"


def test_successful_write_creates_openable_verified_backup(tmp_path):
    db_path = tmp_path / "m.db"
    backup_dir = tmp_path / "backups"
    _create_db(db_path)

    result, backup_path = safe_engine_db_write(
        db_path,
        backup_dir,
        "test operation",
        _write_value,
    )

    assert result == "written"
    assert backup_path.parent == backup_dir
    assert backup_path.suffix == ".db"
    assert "test_operation" in backup_path.name
    backup = sqlite3.connect(backup_path)
    try:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT value FROM sample WHERE id = 1").fetchone()[0] == "original"
    finally:
        backup.close()


def test_committed_wal_data_is_present_in_backup(tmp_path):
    db_path = tmp_path / "wal.db"
    backup_dir = tmp_path / "backups"
    keeper = sqlite3.connect(db_path)
    keeper.execute("PRAGMA journal_mode = WAL")
    keeper.execute("PRAGMA wal_autocheckpoint = 0")
    keeper.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
    keeper.execute("INSERT INTO sample VALUES (1, 'from-wal')")
    keeper.commit()
    assert Path(f"{db_path}-wal").exists()

    try:
        _, backup_path = safe_engine_db_write(
            db_path,
            backup_dir,
            "wal_capture",
            lambda _connection, _backup: None,
        )
    finally:
        keeper.close()

    assert _read_value(backup_path) == "from-wal"


def test_successful_change_is_committed(tmp_path):
    db_path = tmp_path / "m.db"
    _create_db(db_path)

    safe_engine_db_write(db_path, tmp_path / "backups", "commit", _write_value)

    assert _read_value(db_path) == "changed"


def test_default_write_keeps_foreign_keys_disabled_and_still_succeeds(tmp_path):
    db_path = tmp_path / "m.db"
    _create_db(db_path)
    observed = []

    def write_without_foreign_keys(connection, _backup):
        observed.append(connection.execute("PRAGMA foreign_keys").fetchone()[0])
        connection.execute("UPDATE sample SET value = 'default-write' WHERE id = 1")

    safe_engine_db_write(
        db_path,
        tmp_path / "backups",
        "default_foreign_keys",
        write_without_foreign_keys,
    )

    assert observed == [0]
    assert _read_value(db_path) == "default-write"


def test_unconfirmed_foreign_keys_fail_before_begin_backup_and_callback(
    tmp_path, monkeypatch
):
    statements = []
    callback_called = False

    class FakeCursor:
        def fetchone(self):
            return (0,)

    class FakeConnection:
        row_factory = None

        def execute(self, statement):
            statements.append(statement)
            return FakeCursor()

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        engine_db_write.sqlite3,
        "connect",
        lambda *_args, **_kwargs: FakeConnection(),
    )

    def should_not_run(_connection, _backup):
        nonlocal callback_called
        callback_called = True

    backup_dir = tmp_path / "backups"
    with pytest.raises(EngineDBWriteError) as caught:
        safe_engine_db_write(
            tmp_path / "engine.db",
            backup_dir,
            "foreign_keys_not_enabled",
            should_not_run,
            foreign_keys=True,
        )

    assert caught.value.code == "write_failed"
    assert str(caught.value) == "SQLite did not enable foreign key enforcement"
    assert statements == ["PRAGMA foreign_keys=ON", "PRAGMA foreign_keys"]
    assert callback_called is False
    assert backup_dir.exists() is False


def test_missing_source_db_is_not_created_or_backed_up(tmp_path):
    db_path = tmp_path / "missing engine.db"
    backup_dir = tmp_path / "backups"
    called = False

    def should_not_run(_connection, _backup):
        nonlocal called
        called = True

    with pytest.raises(EngineDBWriteError) as caught:
        safe_engine_db_write(db_path, backup_dir, "missing", should_not_run)

    assert caught.value.code == "write_failed"
    assert called is False
    assert db_path.exists() is False
    assert list(backup_dir.glob("*.db")) == []


def test_database_path_with_spaces_and_special_characters_works(tmp_path):
    db_dir = tmp_path / "Engine Library #1"
    db_dir.mkdir()
    db_path = db_dir / "Engine database #1.db"
    backup_dir = tmp_path / "backup directory"
    _create_db(db_path)

    safe_engine_db_write(db_path, backup_dir, "special path", _write_value)

    assert _read_value(db_path) == "changed"
    assert len(list(backup_dir.glob("*.db"))) == 1


def test_open_error_releases_process_write_lock(tmp_path):
    missing_db = tmp_path / "missing.db"
    valid_db = tmp_path / "valid.db"
    _create_db(valid_db)

    with pytest.raises(EngineDBWriteError) as caught:
        safe_engine_db_write(
            missing_db,
            tmp_path / "missing backups",
            "missing",
            _write_value,
        )

    assert caught.value.code == "write_failed"
    result, _backup = safe_engine_db_write(
        valid_db,
        tmp_path / "valid backups",
        "after_open_error",
        _write_value,
        lock_timeout=0.0,
    )
    assert result == "written"
    assert _read_value(valid_db) == "changed"


def test_exception_rolls_back_and_leaves_source_unchanged(tmp_path):
    db_path = tmp_path / "m.db"
    _create_db(db_path)

    def fail_after_write(connection, _backup):
        connection.execute("UPDATE sample SET value = 'uncommitted' WHERE id = 1")
        raise RuntimeError("synthetic failure")

    with pytest.raises(EngineDBWriteError) as caught:
        safe_engine_db_write(db_path, tmp_path / "backups", "rollback", fail_after_write)

    assert caught.value.code == "write_failed"
    assert _read_value(db_path) == "original"


def test_backup_exists_and_contains_old_data_before_first_change(tmp_path):
    db_path = tmp_path / "m.db"
    _create_db(db_path)
    observations = []

    def inspect_then_write(connection, backup_path):
        observations.append((backup_path.exists(), _read_value(backup_path)))
        connection.execute("UPDATE sample SET value = 'changed' WHERE id = 1")

    safe_engine_db_write(db_path, tmp_path / "backups", "ordering", inspect_then_write)

    assert observations == [(True, "original")]
    assert _read_value(db_path) == "changed"


def test_backup_failure_prevents_write_callback(tmp_path):
    db_path = tmp_path / "m.db"
    invalid_backup_dir = tmp_path / "not-a-directory"
    _create_db(db_path)
    invalid_backup_dir.write_text("file", encoding="utf-8")
    called = False

    def should_not_run(_connection, _backup):
        nonlocal called
        called = True

    with pytest.raises(EngineDBBackupError) as caught:
        safe_engine_db_write(db_path, invalid_backup_dir, "backup_failure", should_not_run)

    assert caught.value.code == "backup_failed"
    assert called is False
    assert _read_value(db_path) == "original"


def test_corrupt_database_is_rejected_before_callback(tmp_path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a sqlite database")
    called = False

    def should_not_run(_connection, _backup):
        nonlocal called
        called = True

    with pytest.raises(EngineDBWriteError) as caught:
        safe_engine_db_write(db_path, tmp_path / "backups", "corrupt", should_not_run)

    assert caught.value.code == "integrity_check_failed"
    assert called is False


def test_external_database_lock_returns_db_locked(tmp_path):
    db_path = tmp_path / "m.db"
    _create_db(db_path)
    blocker = sqlite3.connect(db_path)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(EngineDBLockedError) as caught:
            safe_engine_db_write(
                db_path,
                tmp_path / "backups",
                "locked",
                _write_value,
                sqlite_timeout=0.05,
            )
    finally:
        blocker.rollback()
        blocker.close()

    assert caught.value.code == "db_locked"
    assert list((tmp_path / "backups").glob("*.db")) == []
    assert _read_value(db_path) == "original"


def test_parallel_operations_do_not_write_at_the_same_time(tmp_path):
    db_path = tmp_path / "m.db"
    _create_db(db_path)
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def slow_write(connection, _backup):
        connection.execute("UPDATE sample SET value = 'first' WHERE id = 1")
        entered.set()
        assert release.wait(timeout=2.0)

    def run_first():
        try:
            safe_engine_db_write(db_path, tmp_path / "backups", "first", slow_write)
        except Exception as exc:  # pragma: no cover - reported by the assertion below
            errors.append(exc)

    first = threading.Thread(target=run_first)
    first.start()
    assert entered.wait(timeout=2.0)
    try:
        with pytest.raises(EngineDBWriteBusyError) as caught:
            safe_engine_db_write(
                db_path,
                tmp_path / "backups",
                "second",
                _write_value,
                lock_timeout=0.05,
            )
        assert caught.value.code == "write_busy"
    finally:
        release.set()
        first.join(timeout=2.0)

    assert first.is_alive() is False
    assert errors == []
    assert _read_value(db_path) == "first"


def _create_engine_export_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE Track (
            id INTEGER PRIMARY KEY,
            lastEditTime TEXT,
            path TEXT,
            filename TEXT,
            title TEXT,
            artist TEXT,
            length INTEGER,
            bpmAnalyzed REAL,
            bpm REAL
        );
        CREATE TABLE PerformanceData (
            trackId INTEGER PRIMARY KEY,
            quickCues BLOB,
            loops BLOB
        );
        INSERT INTO Track VALUES (
            1, 'before', 'synthetic.mp3', 'synthetic.mp3',
            'Synthetic', 'Test', 300, 120.0, 120.0
        );
        INSERT INTO PerformanceData VALUES (1, NULL, NULL);
        """
    )
    connection.commit()
    connection.close()


def test_export_track_marks_preserves_success_response_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "engine.db"
    backup_dir = tmp_path / "backups"
    _create_engine_export_db(db_path)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(
        set_app,
        "get_track_marks",
        lambda _track_id: {
            "exists": True,
            "marks": [{"type": "MIX_IN", "time_sec": 12.5}],
            "loops": [],
        },
    )

    response = set_app.export_track_marks_to_engine({"track_id": 1})

    assert set(response) == {
        "ok",
        "backup_path",
        "exported_cues",
        "exported_loops",
        "conflicts",
        "warnings",
    }
    assert response["ok"] is True
    assert response["exported_cues"][0]["type"] == "MIX_IN"
    assert response["exported_loops"] == []
    assert response["conflicts"] == []
    assert Path(response["backup_path"]).is_file()


def test_export_track_marks_preserves_safe_write_error_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "engine.db"
    _create_engine_export_db(db_path)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(
        set_app,
        "get_track_marks",
        lambda _track_id: {
            "exists": True,
            "marks": [{"type": "MIX_IN", "time_sec": 12.5}],
            "loops": [],
        },
    )

    def write_busy(*_args, **_kwargs):
        raise EngineDBWriteBusyError("synthetic busy write")

    monkeypatch.setattr(set_app, "safe_engine_db_write", write_busy)

    response = set_app.export_track_marks_to_engine({"track_id": 1})

    assert response == {
        "ok": False,
        "reason": "write_busy",
        "error": "synthetic busy write",
        "db_path": str(db_path),
    }
