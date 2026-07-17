import struct
import zlib

import pytest

from set_app.set_app import (
    _beat_grid_from_bpm,
    _decode_engine_zlib_blob,
    _engine_beat_grid_from_raw,
    _suggest_loop_bounds,
    _suggest_snap_time,
)


def _beat_data_raw(
    *,
    sample_rate=48_000.0,
    sample_count=192_000.0,
    anchor_samples=0.0,
    stored_beat_count=32,
):
    """Build the observed compact Engine DJ beatData descriptor."""
    raw = bytearray(61)
    struct.pack_into(">d", raw, 0, sample_rate)
    struct.pack_into(">d", raw, 8, sample_count)
    struct.pack_into("<I", raw, 16, 1)
    raw[24] = 1
    struct.pack_into("<d", raw, 25, anchor_samples)
    struct.pack_into("<I", raw, 57, stored_beat_count)
    return bytes(raw)


def _engine_container(raw):
    return struct.pack(">I", len(raw)) + zlib.compress(raw)


def test_decode_engine_zlib_blob_unpacks_length_prefixed_container():
    raw = _beat_data_raw()

    assert _decode_engine_zlib_blob(_engine_container(raw)) == raw


def test_engine_beat_grid_reads_sample_rate_for_anchor_time():
    raw = _beat_data_raw(
        sample_rate=48_000.0,
        anchor_samples=24_000.0,
    )

    grid = _engine_beat_grid_from_raw(raw, bpm=120.0, duration_sec=2.0)

    assert grid[0]["time_sec"] == 0.5


def test_engine_beat_grid_reads_sample_count_as_duration_fallback():
    raw = _beat_data_raw(
        sample_rate=48_000.0,
        sample_count=96_000.0,
        anchor_samples=12_000.0,
    )

    grid = _engine_beat_grid_from_raw(raw, bpm=120.0, duration_sec=0)

    assert [beat["time_sec"] for beat in grid] == [0.25, 0.75, 1.25, 1.75]


def test_engine_beat_grid_extracts_positive_anchor():
    raw = _beat_data_raw(anchor_samples=6_000.0)

    grid = _engine_beat_grid_from_raw(raw, bpm=120.0, duration_sec=1.25)

    assert grid[0]["time_sec"] == 0.125


def test_engine_beat_grid_moves_negative_anchor_to_first_visible_beat():
    raw = _beat_data_raw(anchor_samples=-12_000.0)

    grid = _engine_beat_grid_from_raw(raw, bpm=120.0, duration_sec=1.0)

    assert [beat["time_sec"] for beat in grid] == [0.25, 0.75]


def test_engine_beat_grid_preserves_nonzero_phase():
    raw = _beat_data_raw(anchor_samples=6_000.0)

    grid = _engine_beat_grid_from_raw(raw, bpm=120.0, duration_sec=1.7)

    assert [beat["time_sec"] for beat in grid] == [0.125, 0.625, 1.125, 1.625]


def test_engine_beat_grid_sets_beat_bar_and_phrase_metadata():
    raw = _beat_data_raw(
        sample_rate=48_000.0,
        sample_count=480_000.0,
        stored_beat_count=20,
    )

    grid = _engine_beat_grid_from_raw(raw, bpm=120.0, duration_sec=9.0)

    assert grid[0] == {
        "time_sec": 0.0,
        "beat": 1,
        "bar": 1,
        "is_bar_start": True,
        "is_phrase_start": True,
    }
    assert grid[3] | {"time_sec": 0.0} == {
        "time_sec": 0.0,
        "beat": 4,
        "bar": 1,
        "is_bar_start": False,
        "is_phrase_start": False,
    }
    assert grid[4] | {"time_sec": 0.0} == {
        "time_sec": 0.0,
        "beat": 5,
        "bar": 2,
        "is_bar_start": True,
        "is_phrase_start": False,
    }
    assert grid[16] | {"time_sec": 0.0} == {
        "time_sec": 0.0,
        "beat": 17,
        "bar": 5,
        "is_bar_start": True,
        "is_phrase_start": True,
    }


@pytest.mark.parametrize(
    "blob",
    [
        None,
        b"",
        b"short",
        struct.pack(">I", 61) + b"not-zlib",
    ],
)
def test_decode_engine_zlib_blob_rejects_missing_short_or_corrupt_blob(blob):
    assert _decode_engine_zlib_blob(blob) is None


def test_engine_beat_grid_rejects_too_short_raw_data():
    assert _engine_beat_grid_from_raw(b"short", 120.0, 10.0) == []


@pytest.mark.parametrize("sample_rate", [7_999.0, 384_001.0, float("nan")])
def test_engine_beat_grid_rejects_invalid_sample_rate(sample_rate):
    raw = _beat_data_raw(sample_rate=sample_rate)

    assert _engine_beat_grid_from_raw(raw, 120.0, 4.0) == []


@pytest.mark.parametrize("bpm", [None, 0, 19.99, 401, "invalid"])
def test_engine_beat_grid_rejects_missing_or_invalid_bpm(bpm):
    assert _engine_beat_grid_from_raw(_beat_data_raw(), bpm, 4.0) == []


def test_beat_grid_from_bpm_is_available_as_fallback():
    grid = _beat_grid_from_bpm(120.0, duration_sec=1.3, offset_sec=0.25)

    assert [beat["time_sec"] for beat in grid] == [0.25, 0.75, 1.25]
    assert grid[0]["beat"] == 1
    assert grid[0]["is_bar_start"] is True


def test_suggest_snap_time_uses_exact_grid_phase():
    grid = _beat_grid_from_bpm(120.0, duration_sec=3.0, offset_sec=0.25)

    assert _suggest_snap_time(0.7, grid, 120.0, 3.0, unit_beats=1) == 0.75


def test_suggest_loop_bounds_uses_exact_beat_indexes():
    times = [0.2, 0.71, 1.23, 1.74, 2.26, 2.77]
    grid = [
        {
            "time_sec": time_sec,
            "beat": index + 1,
            "is_bar_start": index % 4 == 0,
            "is_phrase_start": index % 16 == 0,
        }
        for index, time_sec in enumerate(times)
    ]

    bounds = _suggest_loop_bounds(
        0.69,
        length_beats=4,
        beat_grid=grid,
        bpm=120.0,
        duration_sec=3.0,
    )

    assert bounds == {
        "start_sec": 0.71,
        "end_sec": 2.77,
        "start_beat_index": 1,
        "end_beat_index": 5,
        "grid_source": "beat_grid",
    }


def test_suggest_loop_bounds_rejects_loop_past_track_end():
    grid = _beat_grid_from_bpm(120.0, duration_sec=4.0)

    bounds = _suggest_loop_bounds(
        3.5,
        length_beats=4,
        beat_grid=grid,
        bpm=120.0,
        duration_sec=4.0,
    )

    assert bounds is None
