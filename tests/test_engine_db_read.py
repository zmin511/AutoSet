import sqlite3
import sys
from pathlib import Path

import pytest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from engine_db_read import open_engine_db_read_only  # noqa: E402


def _create_database(path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE Track (id INTEGER PRIMARY KEY, title TEXT)")
    connection.execute("INSERT INTO Track (title) VALUES (?)", ("Synthetic track",))
    connection.commit()
    connection.close()


def test_opens_existing_database_read_only(tmp_path):
    db_path = tmp_path / "m.db"
    _create_database(db_path)

    with open_engine_db_read_only(db_path) as connection:
        row = connection.execute("SELECT id, title FROM Track").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert dict(row) == {"id": 1, "title": "Synthetic track"}
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO Track (title) VALUES ('must fail')")


def test_missing_database_is_not_created(tmp_path):
    db_path = tmp_path / "missing" / "m.db"

    with pytest.raises(sqlite3.OperationalError):
        open_engine_db_read_only(db_path)

    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_corrupt_database_reports_sqlite_error(tmp_path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a sqlite database")

    with open_engine_db_read_only(db_path) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="not a database"):
            connection.execute("SELECT name FROM sqlite_master").fetchall()


def test_locked_database_preserves_busy_error(tmp_path):
    db_path = tmp_path / "locked.db"
    _create_database(db_path)
    blocker = sqlite3.connect(db_path, timeout=0)
    blocker.execute("BEGIN EXCLUSIVE")

    try:
        with open_engine_db_read_only(db_path, timeout=0) as connection:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                connection.execute("SELECT * FROM Track").fetchall()
    finally:
        blocker.rollback()
        blocker.close()


def test_spaces_unicode_and_uri_special_characters(tmp_path):
    db_path = tmp_path / "Engine DB #1 % музыка" / "m & library.db"
    db_path.parent.mkdir()
    _create_database(db_path)

    with open_engine_db_read_only(db_path) as connection:
        title = connection.execute("SELECT title FROM Track").fetchone()["title"]

    assert title == "Synthetic track"
