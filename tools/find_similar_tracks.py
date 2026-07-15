from __future__ import annotations

import argparse
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from analysis_db import (  # noqa: E402
    DEFAULT_ANALYSIS_DB_PATH,
    get_profile_by_path,
    get_profile_by_track_id,
    list_profiles,
    open_analysis_db,
)
from track_analysis import find_similar_tracks  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find similar tracks in AutoSet analysis.db."
    )

    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--track-id",
        help="Reference Engine DJ track id.",
    )
    selector.add_argument(
        "--file-path",
        help="Reference music file path.",
    )

    parser.add_argument(
        "--analysis-db",
        default=str(DEFAULT_ANALYSIS_DB_PATH),
        help="Path to AutoSet analysis.db.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of similar tracks.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Only show results with total score at or above this value.",
    )

    return parser.parse_args()


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:5.1f}%"


def main() -> int:
    args = parse_args()
    analysis_db_path = Path(args.analysis_db)

    if not analysis_db_path.is_file():
        print(
            f"ERROR: analysis database not found: {analysis_db_path}",
            file=sys.stderr,
        )
        return 2

    connection = open_analysis_db(analysis_db_path)

    try:
        if args.track_id:
            reference = get_profile_by_track_id(
                connection,
                args.track_id,
            )
        else:
            reference = get_profile_by_path(
                connection,
                args.file_path,
            )

        if reference is None:
            print(
                "ERROR: reference profile not found",
                file=sys.stderr,
            )
            return 3

        candidates = list_profiles(connection)

    finally:
        connection.close()

    results = find_similar_tracks(
        reference,
        candidates,
        limit=max(0, args.limit),
    )

    results = [
        result
        for result in results
        if result["total"] >= args.min_score
    ]

    print("AutoSet Similar Tracks")
    print(f"Analysis DB: {analysis_db_path}")
    print()
    print("Reference")
    print(f"Track ID: {reference.track_id}")
    print(f"Path:     {reference.file_path}")
    print(f"BPM:      {reference.bpm}")
    print(f"Camelot:  {reference.camelot_key or 'n/a'}")
    print(f"Genre:    {reference.genre or 'n/a'}")
    print(f"Energy:   {reference.energy_mean}")
    print()

    if not results:
        print("No similar tracks found.")
        return 0

    print(f"Results: {len(results)}")
    print()

    for position, result in enumerate(results, 1):
        profile = result["profile"]
        components = result["components"]

        print(
            f"{position:02d}. "
            f"{result['total'] * 100:5.1f}% | "
            f"ID {profile.track_id} | "
            f"{Path(profile.file_path).name}"
        )
        print(
            "    "
            f"BPM {_format_percent(components.get('bpm'))} | "
            f"Camelot {_format_percent(components.get('camelot'))} | "
            f"Energy {_format_percent(components.get('energy'))} | "
            f"Genre {_format_percent(components.get('genre'))} | "
            f"Duration {_format_percent(components.get('duration'))}"
        )
        print(
            "    "
            f"{profile.bpm or 'n/a'} BPM | "
            f"{profile.camelot_key or 'n/a'} | "
            f"{profile.genre or 'n/a'} | "
            f"energy={profile.energy_mean if profile.energy_mean is not None else 'n/a'}"
        )
        print(f"    {profile.file_path}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
