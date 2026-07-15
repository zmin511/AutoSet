from __future__ import annotations

import argparse
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from analysis_db import (  # noqa: E402
    DEFAULT_ANALYSIS_DB_PATH,
    get_profile_by_track_id,
    open_analysis_db,
)
from engine_config import PATHS  # noqa: E402
from engine_set_builder import (  # noqa: E402
    build_peak_set,
    build_start_set,
    load_tracks,
    open_db,
    parse_style_filter,
)
from transition_analysis import transition_score  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a set with the existing AutoSet algorithm and audit "
            "every transition with the new Transition Score."
        )
    )

    parser.add_argument(
        "--track-id",
        type=int,
        required=True,
        help="Reference Engine DJ track id.",
    )
    parser.add_argument(
        "--role",
        choices=["start", "peak"],
        default="start",
        help="Set role.",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=30,
        help="Target set duration in minutes.",
    )
    parser.add_argument(
        "--max-key-step",
        type=int,
        default=3,
        help="Maximum Camelot step used by the existing set builder.",
    )
    parser.add_argument(
        "--bpm-window",
        type=float,
        default=5.0,
        help="BPM corridor used by the existing set builder.",
    )
    parser.add_argument(
        "--style-filter",
        default="",
        help="Optional comma-separated style filter.",
    )
    parser.add_argument(
        "--engine-db",
        default=PATHS["db_path"],
        help="Path to Engine DJ m.db.",
    )
    parser.add_argument(
        "--music-root",
        default=PATHS["music_root"],
        help="Music root.",
    )
    parser.add_argument(
        "--analysis-db",
        default=str(DEFAULT_ANALYSIS_DB_PATH),
        help="Path to analysis.db.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    engine_db_path = Path(args.engine_db)
    music_root = Path(args.music_root)
    analysis_db_path = Path(args.analysis_db)

    if not engine_db_path.is_file():
        print(
            f"ERROR: Engine DJ database not found: {engine_db_path}",
            file=sys.stderr,
        )
        return 2

    if not analysis_db_path.is_file():
        print(
            f"ERROR: analysis.db not found: {analysis_db_path}",
            file=sys.stderr,
        )
        return 3

    engine_connection = open_db(str(engine_db_path))

    try:
        tracks = load_tracks(
            engine_connection,
            music_root,
        )
    finally:
        engine_connection.close()

    reference = next(
        (
            track
            for track in tracks
            if track.id == args.track_id
        ),
        None,
    )

    if reference is None:
        print(
            f"ERROR: Engine track not found: {args.track_id}",
            file=sys.stderr,
        )
        return 4

    target_seconds = max(5, int(args.minutes)) * 60
    allowed_styles = parse_style_filter(args.style_filter)

    if args.role == "start":
        playlist = build_start_set(
            reference,
            tracks,
            target_seconds,
            args.max_key_step,
            max(0.0, args.bpm_window),
            allowed_styles,
        )
    else:
        playlist = build_peak_set(
            reference,
            tracks,
            target_seconds,
            args.max_key_step,
            max(0.0, args.bpm_window),
            allowed_styles,
        )

    analysis_connection = open_analysis_db(
        analysis_db_path
    )

    try:
        profiles = {
            track.id: get_profile_by_track_id(
                analysis_connection,
                str(track.id),
            )
            for track in playlist
        }
    finally:
        analysis_connection.close()

    print("AutoSet Set Transition Audit")
    print(f"Role:           {args.role}")
    print(f"Reference ID:   {reference.id}")
    print(f"Tracks:         {len(playlist)}")
    print(f"Target minutes: {args.minutes}")
    print()

    class_counts = {
        "safe": 0,
        "compatible": 0,
        "risky": 0,
        "rejected": 0,
        "missing": 0,
    }

    for index, track in enumerate(
        playlist,
        start=1,
    ):
        marker = " <REFERENCE>" if track.id == reference.id else ""

        print(
            f"{index:02d}. "
            f"ID {track.id} | "
            f"{track.artist} - {track.title or track.filename}"
            f"{marker}"
        )

        if index == 1:
            print("    START")
            continue

        previous = playlist[index - 2]
        previous_profile = profiles.get(previous.id)
        current_profile = profiles.get(track.id)

        if previous_profile is None or current_profile is None:
            class_counts["missing"] += 1
            print("    MISSING ANALYSIS PROFILE")
            continue

        result = transition_score(
            previous_profile,
            current_profile,
        )

        class_counts[result.transition_class] = (
            class_counts.get(
                result.transition_class,
                0,
            )
            + 1
        )

        components = result.components

        print(
            f"    {result.transition_class.upper():10s} | "
            f"{result.total * 100:5.1f}% | "
            f"BPM {components.get('bpm', 0) * 100:5.1f}% | "
            f"Camelot {components.get('camelot', 0) * 100:5.1f}% | "
            f"Energy {components.get('energy', 0) * 100:5.1f}% | "
            f"Genre {components.get('genre', 0) * 100:5.1f}%"
        )

    print()
    print("Summary")
    print(f"SAFE:       {class_counts['safe']}")
    print(f"COMPATIBLE: {class_counts['compatible']}")
    print(f"RISKY:      {class_counts['risky']}")
    print(f"REJECTED:   {class_counts['rejected']}")
    print(f"MISSING:    {class_counts['missing']}")

    risky_total = (
        class_counts["risky"]
        + class_counts["rejected"]
        + class_counts["missing"]
    )

    return 1 if risky_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
