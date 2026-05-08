import argparse
import csv
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_DB_PATH = r"F:\Music\Engine Library\Database2\m.db"
DEFAULT_MUSIC_ROOT = r"F:\Music"


@dataclass(frozen=True)
class TrackRow:
    id: int
    filename: str
    file_bytes: int
    bitrate: Optional[int]
    bpm_analyzed: Optional[float]
    key: Optional[int]
    genre: Optional[str]
    artist: Optional[str]
    title: Optional[str]
    path: Optional[str]


def _iter_audio_files(root: Path) -> Iterable[Path]:
    exts = {".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".ogg"}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() in exts:
                yield Path(dirpath) / name


def _open_db(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def load_track_index(con: sqlite3.Connection) -> Dict[Tuple[str, int], List[TrackRow]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT
          id,
          filename,
          fileBytes AS file_bytes,
          bitrate,
          bpmAnalyzed AS bpm_analyzed,
          key,
          genre,
          artist,
          title,
          path
        FROM Track
        """
    )
    index: Dict[Tuple[str, int], List[TrackRow]] = {}
    for r in cur.fetchall():
        tr = TrackRow(
            id=int(r["id"]),
            filename=str(r["filename"] or ""),
            file_bytes=int(r["file_bytes"] or 0),
            bitrate=(None if r["bitrate"] is None else int(r["bitrate"])),
            bpm_analyzed=(None if r["bpm_analyzed"] is None else float(r["bpm_analyzed"])),
            key=(None if r["key"] is None else int(r["key"])),
            genre=(None if r["genre"] is None else str(r["genre"])),
            artist=(None if r["artist"] is None else str(r["artist"])),
            title=(None if r["title"] is None else str(r["title"])),
            path=(None if r["path"] is None else str(r["path"])),
        )
        k = (tr.filename.lower(), tr.file_bytes)
        index.setdefault(k, []).append(tr)
    return index


def _key_dist_24(a: Optional[int], b: Optional[int]) -> int:
    if a is None or b is None:
        return 999
    if a == 0 or b == 0:
        return 999
    da = abs(a - b)
    return min(da, 24 - da)


def _bpm_dist(a: Optional[float], b: Optional[float]) -> float:
    if a is None or b is None:
        return 1e9
    return abs(a - b)


def scan_folder(
    folder: Path,
    index: Dict[Tuple[str, int], List[TrackRow]],
    max_rows: Optional[int] = None,
) -> List[Tuple[Path, Optional[TrackRow]]]:
    out: List[Tuple[Path, Optional[TrackRow]]] = []
    for fp in _iter_audio_files(folder):
        try:
            size = fp.stat().st_size
        except OSError:
            out.append((fp, None))
            continue
        hits = index.get((fp.name.lower(), int(size)))
        out.append((fp, (hits[0] if hits else None)))
        if max_rows is not None and len(out) >= max_rows:
            break
    return out


def export_csv(rows: Sequence[Tuple[Path, Optional[TrackRow]]], out_path: Path) -> None:
    if not out_path.parent.exists():
        raise SystemExit(f"Папка для CSV не существует: {out_path.parent}")
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file",
                "matched",
                "track_id",
                "bitrate",
                "bpm_analyzed",
                "key",
                "genre",
                "artist",
                "title",
                "db_path",
            ]
        )
        for fp, tr in rows:
            w.writerow(
                [
                    str(fp),
                    "1" if tr else "0",
                    (tr.id if tr else ""),
                    (tr.bitrate if tr else ""),
                    (tr.bpm_analyzed if tr else ""),
                    (tr.key if tr else ""),
                    (tr.genre if tr else ""),
                    (tr.artist if tr else ""),
                    (tr.title if tr else ""),
                    (tr.path if tr else ""),
                ]
            )


def _pick_reference(
    reference_file: Path, index: Dict[Tuple[str, int], List[TrackRow]]
) -> TrackRow:
    size = reference_file.stat().st_size
    hits = index.get((reference_file.name.lower(), int(size)))
    if not hits:
        raise SystemExit(
            f"Не нашёл трек в базе Engine по (имя файла + размер): {reference_file}"
        )
    return hits[0]


def build_playlist(
    reference: TrackRow,
    all_tracks: Sequence[TrackRow],
    length: int,
    max_key_step: int,
    max_bpm_step: float,
    prefer_same_genre: bool,
) -> List[TrackRow]:
    remaining = [t for t in all_tracks if t.id != reference.id]

    def base_score(t: TrackRow) -> float:
        score = 0.0
        score += _key_dist_24(reference.key, t.key) * 10.0
        score += _bpm_dist(reference.bpm_analyzed, t.bpm_analyzed) * 1.0
        if prefer_same_genre and reference.genre and t.genre:
            if reference.genre.strip().lower() != t.genre.strip().lower():
                score += 15.0
        if reference.bitrate and t.bitrate and reference.bitrate != t.bitrate:
            score += 1.0
        return score

    remaining.sort(key=base_score)
    playlist = [reference]

    while len(playlist) < max(1, length) and remaining:
        last = playlist[-1]

        def ok(t: TrackRow) -> bool:
            if max_key_step >= 0:
                if _key_dist_24(last.key, t.key) > max_key_step:
                    return False
            if max_bpm_step >= 0:
                if _bpm_dist(last.bpm_analyzed, t.bpm_analyzed) > max_bpm_step:
                    return False
            return True

        pick_i = None
        best = None
        for i, t in enumerate(remaining[:2000]):
            if not ok(t):
                continue
            score = 0.0
            score += _key_dist_24(last.key, t.key) * 10.0
            score += _bpm_dist(last.bpm_analyzed, t.bpm_analyzed) * 1.0
            if prefer_same_genre and reference.genre and t.genre:
                if reference.genre.strip().lower() != t.genre.strip().lower():
                    score += 10.0
            if best is None or score < best:
                best = score
                pick_i = i
        if pick_i is None:
            break
        playlist.append(remaining.pop(pick_i))

    return playlist


def export_m3u(playlist: Sequence[TrackRow], out_path: Path) -> None:
    if not out_path.parent.exists():
        raise SystemExit(f"Папка для M3U не существует: {out_path.parent}")
    with out_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for t in playlist:
            label = " - ".join([p for p in [t.artist, t.title] if p]) or t.filename
            f.write(f"#EXTINF:-1,{label}\n")
            f.write(f"{t.filename}\n")


def resolve_track_path(track: TrackRow, music_root: Path) -> Optional[Path]:
    if not track.path:
        return None
    raw = track.path.replace("/", "\\")
    if os.path.isabs(raw):
        return Path(raw)
    for prefix in ("..\\Music\\", "../Music/"):
        if track.path.startswith(prefix):
            rel = track.path[len(prefix) :].replace("/", "\\")
            return (music_root / rel).resolve()
    if raw.startswith("..\\"):
        rel = raw[3:]
        return (music_root / rel).resolve()
    return None


def cmd_scan(args: argparse.Namespace) -> int:
    con = _open_db(args.db)
    index = load_track_index(con)
    con.close()

    folder = Path(args.folder)
    rows = scan_folder(folder, index, max_rows=args.limit)
    matched = sum(1 for _, tr in rows if tr is not None)
    print(f"Файлов: {len(rows)}, матчей в базе: {matched}, не найдено: {len(rows) - matched}")

    if args.out_csv:
        export_csv(rows, Path(args.out_csv))
        print(f"CSV: {args.out_csv}")
    else:
        for fp, tr in rows[: min(len(rows), 30)]:
            if tr:
                print(
                    f"+ {fp} | bpm={tr.bpm_analyzed} key={tr.key} bitrate={tr.bitrate} genre={tr.genre}"
                )
            else:
                print(f"- {fp} | нет в базе")
        if len(rows) > 30:
            print("... (показаны первые 30)")
    return 0


def cmd_playlist(args: argparse.Namespace) -> int:
    con = _open_db(args.db)
    index = load_track_index(con)
    all_tracks = [t for hits in index.values() for t in hits]
    ref = _pick_reference(Path(args.reference), index)

    pl = build_playlist(
        reference=ref,
        all_tracks=all_tracks,
        length=args.length,
        max_key_step=args.max_key_step,
        max_bpm_step=args.max_bpm_step,
        prefer_same_genre=not args.no_genre_bias,
    )
    con.close()

    music_root = Path(args.music_root)
    for i, t in enumerate(pl, 1):
        resolved = resolve_track_path(t, music_root)
        print(
            f"{i:02d}. {t.artist or ''} - {t.title or t.filename} | bpm={t.bpm_analyzed} key={t.key} bitrate={t.bitrate}"
            + (f" | file={resolved}" if resolved else "")
        )

    if args.out_m3u:
        out_path = Path(args.out_m3u)
        if not out_path.parent.exists():
            raise SystemExit(f"Папка для M3U не существует: {out_path.parent}")
        with out_path.open("w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for t in pl:
                label = " - ".join([p for p in [t.artist, t.title] if p]) or t.filename
                f.write(f"#EXTINF:-1,{label}\n")
                resolved = resolve_track_path(t, music_root)
                f.write(f"{resolved if resolved else t.filename}\n")
        print(f"M3U: {args.out_m3u}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Инструменты для чтения базы Denon Engine (m.db) и подбора треков по BPM/тональности."
    )
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Путь к m.db")
    p.add_argument("--music-root", default=DEFAULT_MUSIC_ROOT, help="Корень музыки (для сборки абсолютных путей)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="Сопоставить файлы из папки с записями в базе")
    s.add_argument("folder", help="Папка с музыкой (например F:\\Music\\New)")
    s.add_argument("--out-csv", dest="out_csv", help="Куда сохранить CSV")
    s.add_argument("--limit", type=int, default=None, help="Ограничить число файлов")
    s.set_defaults(func=cmd_scan)

    pl = sub.add_parser("playlist", help="Собрать плейлист вокруг опорного трека")
    pl.add_argument("reference", help="Путь к опорному файлу (локальный файл)")
    pl.add_argument("--length", type=int, default=20, help="Сколько треков (включая опорный)")
    pl.add_argument(
        "--max-key-step",
        type=int,
        default=2,
        help="Макс. шаг по key между соседними треками (0..23, круг на 24). -1 отключить",
    )
    pl.add_argument(
        "--max-bpm-step",
        type=float,
        default=5.0,
        help="Макс. разница BPM между соседними треками. -1 отключить",
    )
    pl.add_argument(
        "--no-genre-bias",
        action="store_true",
        help="Не отдавать предпочтение совпадающему жанру",
    )
    pl.add_argument("--out-m3u", dest="out_m3u", help="Сохранить M3U (простая версия)")
    pl.set_defaults(func=cmd_playlist)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
