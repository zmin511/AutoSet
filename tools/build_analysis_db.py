from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from analysis_db import (  # noqa: E402
    DEFAULT_ANALYSIS_DB_PATH,
    delete_profile_by_path,
    list_profiles,
    open_analysis_db,
    profile_needs_analysis,
    upsert_profile,
)
from engine_config import PATHS  # noqa: E402
from engine_set_builder import (  # noqa: E402
    engine_key_to_camelot,
    energy_score,
    load_tracks,
    open_db,
    resolve_track_path,
)
from track_analysis import (  # noqa: E402
    ANALYSIS_VERSION,
    TrackProfile,
    build_track_profile,
)


@dataclass
class BuildStats:
    total: int = 0
    analyzed: int = 0
    skipped: int = 0
    missing_files: int = 0
    pruned: int = 0
    errors: int = 0


def _safe_file_stat(path: Optional[Path]) -> tuple[Optional[int], Optional[float]]:
    if path is None:
        return None, None

    try:
        stat = path.stat()
    except (FileNotFoundError, OSError):
        return None, None

    return int(stat.st_size), float(stat.st_mtime)


def track_to_profile(track, music_root: Path) -> TrackProfile:
    resolved_path = resolve_track_path(track, music_root)
    file_size, file_mtime = _safe_file_stat(resolved_path)

    profile_path = (
        str(resolved_path)
        if resolved_path is not None
        else str(track.path or track.filename or "")
    )

    source = {
        "track_id": str(track.id),
        "file_path": profile_path,
        "file_size": file_size,
        "file_mtime": file_mtime,
        "analysis_version": ANALYSIS_VERSION,
        "duration_seconds": track.length,
        "bpm": track.bpm,
        "camelot_key": engine_key_to_camelot(track.key),
        "genre": track.genre,
        "energy_mean": energy_score(track),
    }

    return build_track_profile(source)


def build_analysis_database(
    *,
    engine_db_path: Path,
    music_root: Path,
    analysis_db_path: Path,
    limit: Optional[int] = None,
    force: bool = False,
    dry_run: bool = False,
    prune: bool = False,
    progress_callback: Optional[Callable[[BuildStats, int], None]] = None,
) -> BuildStats:
    stats = BuildStats()

    engine_connection: Optional[sqlite3.Connection] = None
    analysis_connection: Optional[sqlite3.Connection] = None

    try:
        engine_connection = open_db(str(engine_db_path))
        tracks = load_tracks(engine_connection, music_root)

        if limit is not None:
            tracks = tracks[:max(0, int(limit))]

        stats.total = len(tracks)

        current_file_paths = set()

        processed = 0


        for track in tracks:
            resolved_path = resolve_track_path(
                track,
                music_root,
            )

            if resolved_path is not None:
                current_file_paths.add(
                    str(resolved_path)
                )


            processed += 1

            if progress_callback is not None:

                progress_callback(stats, processed)

        if not dry_run:
            analysis_connection = open_analysis_db(analysis_db_path)

        for track in tracks:
            try:
                profile = track_to_profile(track, music_root)

                if profile.file_size is None:
                    stats.missing_files += 1

                if dry_run:
                    stats.analyzed += 1
                    continue

                if analysis_connection is None:
                    raise RuntimeError("Analysis database connection is unavailable")

                needs_analysis = force or profile_needs_analysis(
                    analysis_connection,
                    file_path=profile.file_path,
                    file_size=profile.file_size,
                    file_mtime=profile.file_mtime,
                    analysis_version=profile.analysis_version,
                )

                if not needs_analysis:
                    stats.skipped += 1
                    continue

                upsert_profile(analysis_connection, profile)
                stats.analyzed += 1

            except Exception as exc:
                stats.errors += 1
                print(
                    f"ERROR track_id={getattr(track, 'id', '?')}: {exc}",
                    file=sys.stderr,
                )

        if (
            prune
            and not dry_run
            and analysis_connection is not None
            and limit is None
        ):
            for existing_profile in list_profiles(
                analysis_connection
            ):
                if (
                    existing_profile.file_path
                    not in current_file_paths
                ):
                    deleted = delete_profile_by_path(
                        analysis_connection,
                        existing_profile.file_path,
                    )

                    if deleted:
                        stats.pruned += 1

    finally:
        if engine_connection is not None:
            engine_connection.close()
        if analysis_connection is not None:
            analysis_connection.close()

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build AutoSet analysis.db from Engine DJ metadata. "
            "Engine DJ database and audio files are read-only."
        )
    )
    parser.add_argument(
        "--engine-db",
        default=PATHS["db_path"],
        help="Path to Engine DJ m.db.",
    )
    parser.add_argument(
        "--music-root",
        default=PATHS["music_root"],
        help="Root directory containing music files.",
    )
    parser.add_argument(
        "--analysis-db",
        default=str(DEFAULT_ANALYSIS_DB_PATH),
        help="Path to AutoSet analysis.db.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Analyze at most N tracks.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild profiles even if source files are unchanged.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read tracks and build profiles without writing analysis.db.",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "Delete profiles for tracks no longer present "
            "in the Engine DJ library. Ignored with --limit."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    engine_db_path = Path(args.engine_db)
    music_root = Path(args.music_root)
    analysis_db_path = Path(args.analysis_db)

    print("AutoSet Track Analysis")
    print(f"Analysis version: {ANALYSIS_VERSION}")
    print(f"Engine DB:       {engine_db_path}")
    print(f"Music root:      {music_root}")
    print(f"Analysis DB:     {analysis_db_path}")
    print(f"Dry run:         {args.dry_run}")
    print(f"Force:           {args.force}")
    print(f"Prune:           {args.prune}")
    print(f"Limit:           {args.limit if args.limit is not None else 'all'}")

    if not engine_db_path.is_file():
        print(
            f"ERROR: Engine DJ database not found: {engine_db_path}",
            file=sys.stderr,
        )
        return 2

    if not music_root.exists():
        print(
            f"WARNING: Music root does not exist: {music_root}",
            file=sys.stderr,
        )

    stats = build_analysis_database(
        engine_db_path=engine_db_path,
        music_root=music_root,
        analysis_db_path=analysis_db_path,
        limit=args.limit,
        force=args.force,
        dry_run=args.dry_run,
        prune=args.prune,
    )

    print()
    print("Result")
    print(f"Total tracks:    {stats.total}")
    print(f"Analyzed:        {stats.analyzed}")
    print(f"Skipped:         {stats.skipped}")
    print(f"Missing files:   {stats.missing_files}")
    print(f"Pruned:        {stats.pruned}")
    print(f"Errors:          {stats.errors}")

    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
