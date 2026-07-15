import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT_DIR / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from analysis_db import open_analysis_db, upsert_profile  # noqa: E402
from track_analysis import TrackProfile  # noqa: E402


def _profile(
    track_id: str,
    path: str,
    *,
    bpm: float,
    camelot: str,
    energy: float,
    genre: str,
) -> TrackProfile:
    return TrackProfile(
        track_id=track_id,
        file_path=path,
        file_size=1000,
        file_mtime=123.0,
        duration_seconds=300.0,
        bpm=bpm,
        camelot_key=camelot,
        genre=genre,
        energy_mean=energy,
    )


def test_find_similar_tracks_cli_prints_ranked_results(tmp_path):
    db_path = tmp_path / "analysis.db"

    connection = open_analysis_db(db_path)
    upsert_profile(
        connection,
        _profile(
            "1",
            "Music/reference.mp3",
            bpm=124.0,
            camelot="8A",
            energy=0.6,
            genre="house",
        ),
    )
    upsert_profile(
        connection,
        _profile(
            "2",
            "Music/close.mp3",
            bpm=124.0,
            camelot="8A",
            energy=0.62,
            genre="house",
        ),
    )
    upsert_profile(
        connection,
        _profile(
            "3",
            "Music/distant.mp3",
            bpm=136.0,
            camelot="2B",
            energy=0.2,
            genre="rock",
        ),
    )
    connection.close()

    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS_DIR / "find_similar_tracks.py"),
            "--analysis-db",
            str(db_path),
            "--track-id",
            "1",
            "--limit",
            "2",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "AutoSet Similar Tracks" in result.stdout
    assert "close.mp3" in result.stdout
    assert "distant.mp3" in result.stdout
    assert result.stdout.index("close.mp3") < result.stdout.index("distant.mp3")


def test_find_similar_tracks_cli_reports_missing_reference(tmp_path):
    db_path = tmp_path / "analysis.db"

    connection = open_analysis_db(db_path)
    connection.close()

    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS_DIR / "find_similar_tracks.py"),
            "--analysis-db",
            str(db_path),
            "--track-id",
            "missing",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3
    assert "reference profile not found" in result.stderr
