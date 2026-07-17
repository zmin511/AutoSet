import sqlite3
from pathlib import Path

import pytest

from set_app import set_app
from engine_db_write import (  # noqa: E402
    EngineDBWriteBusyError,
    safe_engine_db_write,
)


def _create_engine_playlist_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE Information (uuid TEXT NOT NULL);
        CREATE TABLE Track (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL,
            databaseUuid TEXT
        );
        CREATE TABLE Playlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            parentListId INTEGER NOT NULL,
            isPersisted INTEGER NOT NULL,
            nextListId INTEGER NOT NULL,
            lastEditTime TEXT,
            isExplicitlyExported INTEGER NOT NULL
        );
        CREATE TABLE PlaylistEntity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listId INTEGER NOT NULL,
            trackId INTEGER NOT NULL,
            databaseUuid TEXT NOT NULL,
            nextEntityId INTEGER NOT NULL,
            membershipReference INTEGER NOT NULL,
            FOREIGN KEY (listId) REFERENCES Playlist(id),
            FOREIGN KEY (trackId) REFERENCES Track(id)
        );
        INSERT INTO Information(uuid) VALUES ('library-uuid');
        INSERT INTO Track(id, path, databaseUuid) VALUES
            (1, '../Music/one.mp3', 'track-uuid-1'),
            (2, '../Music/two.mp3', 'track-uuid-2'),
            (3, '../Music/three.mp3', NULL);
        INSERT INTO Playlist(
            id, title, parentListId, isPersisted, nextListId, lastEditTime,
            isExplicitlyExported
        ) VALUES (1, 'Existing', 0, 1, 0, 'before', 1);
        """
    )
    connection.commit()
    connection.close()


@pytest.fixture
def playlist_db(tmp_path, monkeypatch):
    db_path = tmp_path / "engine.db"
    backup_dir = tmp_path / "backups"
    _create_engine_playlist_db(db_path)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", backup_dir)
    return db_path, backup_dir


def _playlist_rows(db_path: Path):
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT id, title, parentListId, nextListId FROM Playlist ORDER BY id"
        ).fetchall()


def _entity_rows(db_path: Path, list_id: int):
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            """
            SELECT id, listId, trackId, databaseUuid, nextEntityId
            FROM PlaylistEntity
            WHERE listId=?
            ORDER BY id
            """,
            (list_id,),
        ).fetchall()


def test_create_engine_playlist_preserves_success_contract_and_track_order(playlist_db):
    db_path, _backup_dir = playlist_db

    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 2}, {"id": 1}, {"id": 2}, {"id": 3}],
        "Event/Sub",
        "Synthetic Set",
    )

    assert set(response) == {
        "ok",
        "playlist_id",
        "track_count",
        "playlist_title",
        "output",
    }
    assert response["ok"] is True
    assert response["track_count"] == 4
    assert response["playlist_title"] == "Synthetic Set"
    entities = _entity_rows(db_path, response["playlist_id"])
    assert [row[2] for row in entities] == [2, 1, 2, 3]
    assert [row[3] for row in entities] == [
        "track-uuid-2",
        "track-uuid-1",
        "track-uuid-2",
        "library-uuid",
    ]
    assert [row[4] for row in entities] == [
        entities[1][0],
        entities[2][0],
        entities[3][0],
        0,
    ]


def test_playlist_enables_foreign_keys_before_transaction_callback(
    playlist_db, monkeypatch
):
    _db_path, _backup_dir = playlist_db
    original_get_database_uuid = set_app._get_engine_database_uuid
    callback_state = []

    def observe_callback(connection):
        callback_state.append(
            (
                connection.execute("PRAGMA foreign_keys").fetchone()[0],
                connection.in_transaction,
            )
        )
        return original_get_database_uuid(connection)

    monkeypatch.setattr(set_app, "_get_engine_database_uuid", observe_callback)

    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}], "Event", "Synthetic Set"
    )

    assert response["ok"] is True
    assert callback_state == [(1, True)]


def test_create_engine_playlist_preserves_folder_hierarchy_and_list_links(playlist_db):
    db_path, _backup_dir = playlist_db

    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}], "Event/Sub", "Synthetic Set"
    )

    rows = _playlist_rows(db_path)
    by_title = {row[1]: row for row in rows}
    assert by_title["Event"][2] == 0
    assert by_title["Sub"][2] == by_title["Event"][0]
    assert by_title["Synthetic Set"][2] == by_title["Sub"][0]
    assert by_title["Existing"][3] == by_title["Event"][0]
    assert response["playlist_id"] == by_title["Synthetic Set"][0]


def test_create_engine_playlist_preserves_duplicate_title_rule(playlist_db):
    _db_path, _backup_dir = playlist_db
    first = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}], "Event", "Synthetic Set"
    )
    second = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}], "Event", "Synthetic Set"
    )

    assert first["playlist_title"] == "Synthetic Set"
    assert second["playlist_title"] == "Synthetic Set_2"


def test_playlist_backup_is_pre_write_state_and_passes_integrity_check(playlist_db):
    db_path, backup_dir = playlist_db

    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}, {"id": 2}], "Event/Sub", "Synthetic Set"
    )

    assert response["ok"] is True
    backups = list(backup_dir.glob("*_create_engine_playlist_*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute(
            "SELECT COUNT(*) FROM Playlist WHERE title='Synthetic Set'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM PlaylistEntity"
        ).fetchone() == (0,)
    assert len(_entity_rows(db_path, response["playlist_id"])) == 2


def test_partial_entity_insert_rolls_back_playlist_hierarchy_and_links(
    playlist_db, monkeypatch
):
    db_path, _backup_dir = playlist_db
    original_uuid_for_track = set_app._database_uuid_for_track
    calls = 0

    def fail_after_first_insert(connection, track_id, default_uuid):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic failure after partial insert")
        return original_uuid_for_track(connection, track_id, default_uuid)

    monkeypatch.setattr(
        set_app, "_database_uuid_for_track", fail_after_first_insert
    )

    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}, {"id": 2}], "Event/Sub", "Synthetic Set"
    )

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert "synthetic failure" in response["error"]
    assert Path(response["backup_path"]).is_file()
    assert _playlist_rows(db_path) == [(1, "Existing", 0, 0)]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM PlaylistEntity").fetchone() == (0,)


def test_foreign_key_failure_rolls_back_all_playlist_rows_and_returns_backup(
    playlist_db, monkeypatch
):
    db_path, _backup_dir = playlist_db
    monkeypatch.setattr(
        set_app,
        "_engine_track_id_for_playlist_item",
        lambda _connection, _item: (999, None),
    )

    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}], "Event/Sub", "Synthetic Set"
    )

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert "FOREIGN KEY constraint failed" in response["error"]
    assert Path(response["backup_path"]).is_file()
    assert _playlist_rows(db_path) == [(1, "Existing", 0, 0)]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM PlaylistEntity").fetchone() == (0,)


def test_backup_failure_prevents_all_playlist_inserts(playlist_db):
    db_path, backup_dir = playlist_db
    backup_dir.write_text("not a directory", encoding="utf-8")

    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}], "Event", "Synthetic Set"
    )

    assert response["ok"] is False
    assert response["reason"] == "backup_failed"
    assert response["db_path"] == str(db_path)
    assert _playlist_rows(db_path) == [(1, "Existing", 0, 0)]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM PlaylistEntity").fetchone() == (0,)


def test_db_locked_returns_stable_reason_without_mutation(playlist_db, monkeypatch):
    db_path, _backup_dir = playlist_db

    def fast_timeout_write(*args, **kwargs):
        kwargs["sqlite_timeout"] = 0.01
        return safe_engine_db_write(*args, **kwargs)

    monkeypatch.setattr(set_app, "safe_engine_db_write", fast_timeout_write)
    lock = sqlite3.connect(db_path)
    lock.execute("BEGIN EXCLUSIVE")
    try:
        response = set_app.create_engine_playlist_from_tracks(
            [{"id": 1}], "Event", "Synthetic Set"
        )
    finally:
        lock.rollback()
        lock.close()

    assert response == {
        "ok": False,
        "reason": "db_locked",
        "error": "database is locked",
        "db_path": str(db_path),
    }
    assert _playlist_rows(db_path) == [(1, "Existing", 0, 0)]


def test_write_busy_returns_stable_reason_without_mutation(playlist_db, monkeypatch):
    db_path, _backup_dir = playlist_db

    def write_busy(*_args, **_kwargs):
        raise EngineDBWriteBusyError("synthetic busy write")

    monkeypatch.setattr(set_app, "safe_engine_db_write", write_busy)
    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}], "Event", "Synthetic Set"
    )

    assert response == {
        "ok": False,
        "reason": "write_busy",
        "error": "synthetic busy write",
        "db_path": str(db_path),
    }
    assert _playlist_rows(db_path) == [(1, "Existing", 0, 0)]


def test_missing_database_is_not_created(tmp_path, monkeypatch):
    db_path = tmp_path / "missing.db"
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "ENGINE_DB_BACKUP_DIR", tmp_path / "backups")

    response = set_app.create_engine_playlist_from_tracks(
        [{"id": 1}], "Event", "Synthetic Set"
    )

    assert response["ok"] is False
    assert response["reason"] == "write_failed"
    assert response["db_path"] == str(db_path)
    assert not db_path.exists()
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize(
    ("tracks", "folder", "title", "message"),
    [
        ([], "Event", "Synthetic Set", "Empty track list"),
        ([{"id": 1}], "", "Synthetic Set", "folder and title are required"),
        ([{"id": 1}], "Event", "", "folder and title are required"),
    ],
)
def test_validation_error_before_write_does_not_create_backup(
    playlist_db, tracks, folder, title, message
):
    _db_path, backup_dir = playlist_db

    with pytest.raises(ValueError, match=message):
        set_app.create_engine_playlist_from_tracks(tracks, folder, title)

    assert not backup_dir.exists()


def test_http_operation_preserves_success_response_contract(monkeypatch):
    playlist = {"tracks": [{"id": 1}], "reference_id": 1}
    monkeypatch.setattr(set_app, "_build_playlist_only", lambda *_args: playlist)
    monkeypatch.setattr(
        set_app, "_engine_playlist_local_folder_name", lambda *_args: "Synthetic_Set"
    )
    monkeypatch.setattr(
        set_app,
        "create_engine_playlist_from_tracks",
        lambda *_args: {
            "ok": True,
            "playlist_id": 42,
            "track_count": 1,
            "playlist_title": "Synthetic_Set",
            "output": "created",
        },
    )
    monkeypatch.setattr(
        set_app,
        "write_local_playlist_no_copy",
        lambda *_args: {"folder": "folder", "m3u": "list.m3u", "csv": "list.csv"},
    )

    response = set_app.create_engine_playlist({"track_id": 1, "folder": "Event"})

    assert response == {
        "ok": True,
        "playlist_id": 42,
        "track_count": 1,
        "playlist_title": "Synthetic_Set",
        "output": "created",
        "local_playlist_folder": "folder",
        "local_m3u": "list.m3u",
        "local_csv": "list.csv",
        "engine_playlist_title": "Synthetic_Set",
    }


def test_http_operation_preserves_safe_write_error_contract(monkeypatch):
    playlist = {"tracks": [{"id": 1}], "reference_id": 1}
    monkeypatch.setattr(set_app, "_build_playlist_only", lambda *_args: playlist)
    monkeypatch.setattr(
        set_app, "_engine_playlist_local_folder_name", lambda *_args: "Synthetic_Set"
    )
    error = {
        "ok": False,
        "reason": "write_failed",
        "error": "synthetic write failure",
        "db_path": "synthetic.db",
        "backup_path": "synthetic-backup.db",
    }
    monkeypatch.setattr(
        set_app, "create_engine_playlist_from_tracks", lambda *_args: error.copy()
    )

    def local_write_must_not_run(*_args):
        raise AssertionError("local playlist must not be written after Engine DB failure")

    monkeypatch.setattr(
        set_app, "write_local_playlist_no_copy", local_write_must_not_run
    )

    assert set_app.create_engine_playlist({"track_id": 1, "folder": "Event"}) == error
