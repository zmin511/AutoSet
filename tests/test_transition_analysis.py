import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from track_analysis import TrackProfile  # noqa: E402
from transition_analysis import (  # noqa: E402
    find_transition_candidates,
    transition_score,
)


def _profile(
    track_id: str,
    *,
    path: str,
    bpm: float = 128.0,
    camelot: str = "5B",
    energy: float = 0.35,
    genre: str = "House",
) -> TrackProfile:
    return TrackProfile(
        track_id=track_id,
        file_path=path,
        bpm=bpm,
        camelot_key=camelot,
        energy_mean=energy,
        genre=genre,
        duration_seconds=300.0,
    )


def test_good_transition_is_accepted():
    previous = _profile("1", path="a.mp3")
    candidate = _profile(
        "2",
        path="b.mp3",
        bpm=128.5,
        camelot="4B",
        energy=0.38,
        genre="House",
    )

    result = transition_score(previous, candidate)

    assert result.accepted is True
    assert result.total > 0.85


def test_large_bpm_difference_is_rejected():
    previous = _profile("1", path="a.mp3", bpm=128.0)
    candidate = _profile("2", path="b.mp3", bpm=136.0)

    result = transition_score(previous, candidate)

    assert result.accepted is False
    assert result.total == 0.0
    assert any("BPM delta" in reason for reason in result.reasons)


def test_incompatible_camelot_is_rejected():
    previous = _profile("1", path="a.mp3", camelot="5B")
    candidate = _profile("2", path="b.mp3", camelot="11A")

    result = transition_score(previous, candidate)

    assert result.accepted is False
    assert result.total == 0.0
    assert any("Camelot compatibility" in reason for reason in result.reasons)


def test_missing_optional_values_do_not_crash():
    previous = _profile(
        "1",
        path="a.mp3",
        energy=None,
        genre="",
    )
    candidate = _profile(
        "2",
        path="b.mp3",
        energy=None,
        genre="",
    )

    result = transition_score(previous, candidate)

    assert result.accepted is True
    assert "bpm" in result.components
    assert "camelot" in result.components


def test_candidates_are_filtered_and_sorted():
    previous = _profile("1", path="reference.mp3")

    strong = _profile(
        "2",
        path="strong.mp3",
        bpm=128.0,
        camelot="5A",
        energy=0.36,
        genre="House",
    )
    weaker = _profile(
        "3",
        path="weaker.mp3",
        bpm=130.0,
        camelot="4B",
        energy=0.50,
        genre="House",
    )
    rejected = _profile(
        "4",
        path="rejected.mp3",
        bpm=140.0,
        camelot="5B",
        energy=0.35,
        genre="House",
    )

    results = find_transition_candidates(
        previous,
        [previous, weaker, rejected, strong],
    )

    assert [item["profile"].track_id for item in results] == ["2", "3"]


def test_candidates_respect_min_score_and_limit():
    previous = _profile("1", path="reference.mp3")
    candidates = [
        _profile(
            str(index),
            path=f"{index}.mp3",
            bpm=128.0 + index * 0.1,
            camelot="5B",
            energy=0.35 + index * 0.01,
        )
        for index in range(2, 10)
    ]

    results = find_transition_candidates(
        previous,
        candidates,
        limit=3,
        min_score=0.80,
    )

    assert len(results) == 3
    assert all(item["total"] >= 0.80 for item in results)
