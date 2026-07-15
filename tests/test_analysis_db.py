import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from analysis_db import (  # noqa: E402
    get_profile_by_path,
    get_profile_by_track_id,
    list_profiles,
    open_analysis_db,
    profile_needs_analysis,
    upsert_profile,
)
from track_analysis import TrackProfile  # noqa: E402


def _profile(
    *,
    track_id: str = "1",
    path: str = "Music/test.mp3",
    size: int = 1000,
    mtime: float = 123.5,
    version: int = 1,
    bpm: float = 124.0,
) -> TrackProfile:
    return TrackProfile(
        track_id=track_id,
        file_path=path,
        file_size=size,
        file_mtime=mtime,
        analysis_version=version,
        duration_seconds=300.0,
        bpm=bpm,
        camelot_key="8A",
        genre="house",
        energy_mean=0.65,
        energy_intro=0.40,
        energy_peak=0.90,
        energy_outro=0.45,
        created_at="2026-07-15T09:00:00+00:00",
    )


def test_analysis_db_is_created_in_temporary_directory(tmp_path):
    db_path = tmp_path / "nested" / "analysis.db"

    connection = open_analysis_db(db_path)
    connection.close()

    assert db_path.exists()


def test_schema_contains_track_analysis_table(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'track_analysis'
        """
    ).fetchone()

    connection.close()

    assert row is not None


def test_profile_can_be_saved_and_read_by_path(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")
    source = _profile()

    stored = upsert_profile(connection, source)
    loaded = get_profile_by_path(connection, source.file_path)

    connection.close()

    assert stored.file_path == source.file_path
    assert loaded == stored
    assert loaded.bpm == 124.0
    assert loaded.energy_peak == 0.90


def test_profile_can_be_read_by_track_id(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")
    source = _profile(track_id="track-42")

    upsert_profile(connection, source)
    loaded = get_profile_by_track_id(
        connection,
        "track-42",
    )

    connection.close()

    assert loaded is not None
    assert loaded.file_path == source.file_path


def test_existing_profile_is_updated_by_file_path(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")

    original = _profile(
        track_id="1",
        path="Music/update.mp3",
        bpm=124.0,
    )
    updated = _profile(
        track_id="2",
        path="Music/update.mp3",
        bpm=128.0,
    )

    upsert_profile(connection, original)
    upsert_profile(connection, updated)

    profiles = list_profiles(connection)
    connection.close()

    assert len(profiles) == 1
    assert profiles[0].track_id == "2"
    assert profiles[0].bpm == 128.0


def test_new_file_requires_analysis(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")

    needs_analysis = profile_needs_analysis(
        connection,
        file_path="Music/new.mp3",
        file_size=1000,
        file_mtime=123.5,
        analysis_version=1,
    )

    connection.close()

    assert needs_analysis is True


def test_unchanged_profile_does_not_require_analysis(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")
    source = _profile()

    upsert_profile(connection, source)

    needs_analysis = profile_needs_analysis(
        connection,
        file_path=source.file_path,
        file_size=source.file_size,
        file_mtime=source.file_mtime,
        analysis_version=source.analysis_version,
    )

    connection.close()

    assert needs_analysis is False


def test_analysis_version_change_requires_reanalysis(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")
    source = _profile(version=1)

    upsert_profile(connection, source)

    needs_analysis = profile_needs_analysis(
        connection,
        file_path=source.file_path,
        file_size=source.file_size,
        file_mtime=source.file_mtime,
        analysis_version=2,
    )

    connection.close()

    assert needs_analysis is True


def test_file_mtime_change_requires_reanalysis(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")
    source = _profile(mtime=123.5)

    upsert_profile(connection, source)

    needs_analysis = profile_needs_analysis(
        connection,
        file_path=source.file_path,
        file_size=source.file_size,
        file_mtime=124.0,
        analysis_version=source.analysis_version,
    )

    connection.close()

    assert needs_analysis is True


def test_database_uses_parameterized_values(tmp_path):
    connection = open_analysis_db(tmp_path / "analysis.db")

    suspicious_path = "Music/test'); DROP TABLE track_analysis; --.mp3"
    source = _profile(path=suspicious_path)

    upsert_profile(connection, source)

    loaded = get_profile_by_path(
        connection,
        suspicious_path,
    )
    table = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'track_analysis'
        """
    ).fetchone()

    connection.close()

    assert loaded is not None
    assert table is not None
