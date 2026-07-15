import sqlite3
import struct
import sys
import zlib
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from analysis_db import list_profiles, open_analysis_db  # noqa: E402
from build_analysis_db import (  # noqa: E402
    build_analysis_database,
    track_to_profile,
)
from engine_set_builder import Track  # noqa: E402


def _wave_blob(rgb_values):
    points = len(rgb_values)
    raw = struct.pack(">4I", 0, points, 0, 0)
    raw += b"".join(bytes(value) for value in rgb_values)
    return struct.pack(">I", len(raw)) + zlib.compress(raw)


def _create_engine_db(db_path: Path, music_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE Track (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            length INTEGER,
            bitrate INTEGER,
            bpmAnalyzed REAL,
            key INTEGER,
            genre TEXT,
            artist TEXT,
            title TEXT,
            path TEXT,
            isAvailable INTEGER
        );

        CREATE TABLE PerformanceData (
            trackId INTEGER,
            overviewWaveFormData BLOB
        );
        """
    )
    connection.execute(
        """
        INSERT INTO Track (
            id, filename, length, bitrate, bpmAnalyzed, key,
            genre, artist, title, path, isAvailable
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            music_path.name,
            300,
            320,
            124.0,
            0,
            "house",
            "Artist",
            "Title",
            str(music_path),
            1,
        ),
    )
    connection.execute(
        "INSERT INTO PerformanceData VALUES (?, ?)",
        (1, _wave_blob([(200, 180, 160)])),
    )
    connection.commit()
    connection.close()


def test_track_to_profile_uses_existing_file_metadata(tmp_path):
    music_file = tmp_path / "track.mp3"
    music_file.write_bytes(b"test-audio-data")

    track = Track(
        id=1,
        filename=music_file.name,
        length=300,
        bitrate=320,
        bpm=124.0,
        key=0,
        genre="house",
        artist="Artist",
        title="Title",
        path=str(music_file),
        wave_energy=0.7,
    )

    profile = track_to_profile(track, tmp_path)

    assert profile.track_id == "1"
    assert profile.file_path == str(music_file)
    assert profile.file_size == len(b"test-audio-data")
    assert profile.file_mtime is not None
    assert profile.bpm == 124.0
    assert profile.camelot_key == "8B"
    assert profile.energy_mean == 0.7


def test_build_analysis_database_writes_profiles(tmp_path):
    music_root = tmp_path / "Music"
    music_root.mkdir()

    music_file = music_root / "track.mp3"
    music_file.write_bytes(b"test-audio-data")

    engine_db = tmp_path / "m.db"
    analysis_db = tmp_path / "analysis.db"

    _create_engine_db(engine_db, music_file)

    stats = build_analysis_database(
        engine_db_path=engine_db,
        music_root=music_root,
        analysis_db_path=analysis_db,
    )

    connection = open_analysis_db(analysis_db)
    profiles = list_profiles(connection)
    connection.close()

    assert stats.total == 1
    assert stats.analyzed == 1
    assert stats.skipped == 0
    assert stats.errors == 0
    assert len(profiles) == 1
    assert profiles[0].track_id == "1"


def test_second_build_skips_unchanged_profile(tmp_path):
    music_root = tmp_path / "Music"
    music_root.mkdir()

    music_file = music_root / "track.mp3"
    music_file.write_bytes(b"test-audio-data")

    engine_db = tmp_path / "m.db"
    analysis_db = tmp_path / "analysis.db"

    _create_engine_db(engine_db, music_file)

    first = build_analysis_database(
        engine_db_path=engine_db,
        music_root=music_root,
        analysis_db_path=analysis_db,
    )
    second = build_analysis_database(
        engine_db_path=engine_db,
        music_root=music_root,
        analysis_db_path=analysis_db,
    )

    assert first.analyzed == 1
    assert second.analyzed == 0
    assert second.skipped == 1
    assert second.errors == 0


def test_dry_run_does_not_create_analysis_database(tmp_path):
    music_root = tmp_path / "Music"
    music_root.mkdir()

    music_file = music_root / "track.mp3"
    music_file.write_bytes(b"test-audio-data")

    engine_db = tmp_path / "m.db"
    analysis_db = tmp_path / "analysis.db"

    _create_engine_db(engine_db, music_file)

    stats = build_analysis_database(
        engine_db_path=engine_db,
        music_root=music_root,
        analysis_db_path=analysis_db,
        dry_run=True,
    )

    assert stats.total == 1
    assert stats.analyzed == 1
    assert stats.errors == 0
    assert not analysis_db.exists()
