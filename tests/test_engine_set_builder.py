import sqlite3
import struct
import sys
import zlib
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from engine_set_builder import _wave_energy_from_blob, load_tracks  # noqa: E402


def _wave_blob(rgb_values):
    points = len(rgb_values)
    raw = struct.pack(">4I", 0, points, 0, 0)
    raw += b"".join(bytes(value) for value in rgb_values)
    return struct.pack(">I", len(raw)) + zlib.compress(raw)


def test_wave_energy_decodes_engine_blob():
    energy = _wave_energy_from_blob(_wave_blob([(255, 255, 255), (128, 128, 128)]))
    assert energy is not None
    assert 0.05 <= energy <= 0.98


def test_wave_energy_rejects_invalid_blob():
    assert _wave_energy_from_blob(b"not-an-engine-waveform") is None


def test_load_tracks_attaches_wave_energy():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE Track (
            id INTEGER PRIMARY KEY, filename TEXT, length INTEGER, bitrate INTEGER,
            bpmAnalyzed REAL, key INTEGER, genre TEXT, artist TEXT, title TEXT,
            path TEXT, isAvailable INTEGER
        );
        CREATE TABLE PerformanceData (trackId INTEGER, overviewWaveFormData BLOB);
        """
    )
    con.execute(
        "INSERT INTO Track VALUES (1, 'a.mp3', 300, 320, 124, 0, 'house', 'A', 'A', 'Music/a.mp3', 1)"
    )
    con.execute("INSERT INTO PerformanceData VALUES (?, ?)", (1, _wave_blob([(200, 180, 160)])))
    tracks = load_tracks(con, Path("F:/Music"))
    assert len(tracks) == 1
    assert tracks[0].wave_energy is not None


def test_transition_adjustment_rewards_safe_transition():
    from engine_set_builder import (
        Track,
        transition_score_adjustment,
    )

    previous = Track(
        id=1,
        filename="a.mp3",
        length=300,
        bitrate=320,
        bpm=128.0,
        key=0,
        genre="House",
        artist="A",
        title="A",
        path="a.mp3",
        wave_energy=0.40,
    )
    candidate = Track(
        id=2,
        filename="b.mp3",
        length=300,
        bitrate=320,
        bpm=128.2,
        key=7,
        genre="House",
        artist="B",
        title="B",
        path="b.mp3",
        wave_energy=0.42,
    )

    assert transition_score_adjustment(previous, candidate) == -8.0


def test_transition_adjustment_penalizes_genre_conflict():
    from engine_set_builder import (
        Track,
        transition_score_adjustment,
    )

    previous = Track(
        id=1,
        filename="a.mp3",
        length=300,
        bitrate=320,
        bpm=130.0,
        key=4,
        genre="RusPop, Rus",
        artist="A",
        title="A",
        path="a.mp3",
        wave_energy=0.75,
    )
    candidate = Track(
        id=2,
        filename="b.mp3",
        length=300,
        bitrate=320,
        bpm=130.0,
        key=9,
        genre="House",
        artist="B",
        title="B",
        path="b.mp3",
        wave_energy=0.60,
    )

    assert transition_score_adjustment(previous, candidate) == 35.0


def test_transition_adjustment_rejects_bad_transition():
    from engine_set_builder import (
        Track,
        transition_score_adjustment,
    )

    previous = Track(
        id=1,
        filename="a.mp3",
        length=300,
        bitrate=320,
        bpm=128.0,
        key=0,
        genre="House",
        artist="A",
        title="A",
        path="a.mp3",
        wave_energy=0.40,
    )
    candidate = Track(
        id=2,
        filename="b.mp3",
        length=300,
        bitrate=320,
        bpm=140.0,
        key=11,
        genre="Rock",
        artist="B",
        title="B",
        path="b.mp3",
        wave_energy=0.90,
    )

    assert transition_score_adjustment(previous, candidate) is None
