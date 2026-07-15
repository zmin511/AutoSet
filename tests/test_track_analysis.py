import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from track_analysis import (  # noqa: E402
    TrackProfile,
    bpm_similarity,
    camelot_similarity,
    compare_profiles,
    find_similar_tracks,
    normalize_bpm,
)


def _profile(
    track_id: str,
    *,
    path: str,
    bpm: float | None = 124.0,
    camelot: str = "8A",
    energy: float | None = 0.6,
    genre: str = "house",
    duration: float | None = 300.0,
) -> TrackProfile:
    return TrackProfile(
        track_id=track_id,
        file_path=path,
        bpm=bpm,
        camelot_key=camelot,
        energy_mean=energy,
        genre=genre,
        duration_seconds=duration,
    )


def test_normalize_bpm_handles_half_and_double_time():
    assert normalize_bpm(62) == 124
    assert normalize_bpm(248) == 124
    assert normalize_bpm(124) == 124


def test_identical_profiles_receive_high_score():
    first = _profile("1", path="a.mp3")
    second = _profile("2", path="b.mp3")

    result = compare_profiles(first, second)

    assert result.total == 1.0
    assert all(value == 1.0 for value in result.components.values())


def test_distant_bpm_has_low_bpm_score():
    assert bpm_similarity(120, 132) == 0.0


def test_camelot_scores_exact_and_neighbor_keys():
    assert camelot_similarity("8A", "8A") == 1.0
    assert camelot_similarity("8A", "8B") == 0.95
    assert camelot_similarity("8A", "9A") == 0.90


def test_missing_values_are_ignored_and_weights_are_renormalized():
    first = _profile(
        "1",
        path="a.mp3",
        bpm=124,
        camelot="",
        energy=None,
        genre="",
        duration=None,
    )
    second = _profile(
        "2",
        path="b.mp3",
        bpm=124,
        camelot="",
        energy=None,
        genre="",
        duration=None,
    )

    result = compare_profiles(first, second)

    assert result.total == 1.0
    assert result.components == {"bpm": 1.0}
    assert result.available_weights == {"bpm": 1.0}


def test_find_similar_tracks_excludes_reference_and_sorts_results():
    reference = _profile("1", path="reference.mp3", bpm=124)
    close = _profile("2", path="close.mp3", bpm=124)
    distant = _profile(
        "3",
        path="distant.mp3",
        bpm=136,
        camelot="2B",
        energy=0.1,
        genre="rock",
        duration=120,
    )

    results = find_similar_tracks(
        reference,
        [reference, distant, close],
    )

    assert [item["profile"].track_id for item in results] == ["2", "3"]
    assert results[0]["total"] > results[1]["total"]


def test_find_similar_tracks_respects_limit():
    reference = _profile("1", path="reference.mp3")
    candidates = [
        _profile(str(index), path=f"{index}.mp3", bpm=124 + index)
        for index in range(2, 8)
    ]

    results = find_similar_tracks(reference, candidates, limit=3)

    assert len(results) == 3
