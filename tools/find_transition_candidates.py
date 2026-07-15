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
from transition_analysis import find_transition_candidates  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find the best next DJ tracks from AutoSet analysis.db."
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
        help="Maximum number of transition candidates.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum accepted transition score.",
    )
    parser.add_argument(
        "--include-risky",
        action="store_true",
        help="Include experimental transitions with genre or feature conflicts.",
    )

    return parser.parse_args()


def _percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:5.1f}%"


def main() -> int:
    args = parse_args()
    db_path = Path(args.analysis_db)

    if not db_path.is_file():
        print(
            f"ERROR: analysis database not found: {db_path}",
            file=sys.stderr,
        )
        return 2

    connection = open_analysis_db(db_path)

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

    results = find_transition_candidates(
        reference,
        candidates,
        limit=max(0, args.limit),
        min_score=max(0.0, min(1.0, args.min_score)),
        include_risky=args.include_risky,
    )

    print("AutoSet Transition Candidates")
    print(f"Analysis DB: {db_path}")
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
        print("No accepted transition candidates found.")
        return 0

    print(f"Results: {len(results)}")
    print()

    for position, result in enumerate(results, 1):
        profile = result["profile"]
        components = result["components"]

        print(
            f"{position:02d}. "
            f"{result['total'] * 100:5.1f}% | "
            f"{result['transition_class'].upper():10s} | "
            f"ID {profile.track_id} | "
            f"{Path(profile.file_path).name}"
        )
        print(
            "    "
            f"BPM {_percent(components.get('bpm'))} | "
            f"Camelot {_percent(components.get('camelot'))} | "
            f"Energy {_percent(components.get('energy'))} | "
            f"Genre {_percent(components.get('genre'))}"
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
