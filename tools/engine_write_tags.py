import argparse
import csv
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from engine_config import PATHS

DEFAULT_DB_PATH = PATHS["db_path"]
DEFAULT_MUSIC_ROOT = PATHS["music_root"]
DEFAULT_REPORT_DIR = PATHS["report_dir"]
DEFAULT_BACKUP_DIR = PATHS["backup_dir"]


@dataclass(frozen=True)
class TrackRow:
    id: int
    filename: str
    file_bytes: int
    bitrate: Optional[int]
    bpm_analyzed: Optional[float]
    key: Optional[int]
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
            path=(None if r["path"] is None else str(r["path"])),
        )
        k = (tr.filename.lower(), tr.file_bytes)
        index.setdefault(k, []).append(tr)
    return index


def build_unique_name_index(index: Dict[Tuple[str, int], List[TrackRow]]) -> Dict[str, TrackRow]:
    by_name: Dict[str, List[TrackRow]] = {}
    for (filename, _), rows in index.items():
        by_name.setdefault(filename, []).extend(rows)
    return {filename: rows[0] for filename, rows in by_name.items() if len(rows) == 1}


_NOTE_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def engine_key_to_str(key: Optional[int]) -> Optional[str]:
    """
    Engine's Track.key in m.db is 0..23 (24 slots).
    This script maps it as:
      0..11  -> major keys  (C .. B)
      12..23 -> minor keys  (Cm .. Bm)
    """
    if key is None:
        return None
    if key < 0 or key > 23:
        return None
    if key <= 11:
        return _NOTE_SHARP[key]
    return f"{_NOTE_SHARP[key - 12]}m"


_CAMELOT_MAJOR: Dict[str, str] = {
    "C": "8B",
    "C#": "3B",
    "D": "10B",
    "D#": "5B",
    "E": "12B",
    "F": "7B",
    "F#": "2B",
    "G": "9B",
    "G#": "4B",
    "A": "11B",
    "A#": "6B",
    "B": "1B",
}

_CAMELOT_MINOR: Dict[str, str] = {
    "C": "5A",
    "C#": "12A",
    "D": "7A",
    "D#": "2A",
    "E": "9A",
    "F": "4A",
    "F#": "11A",
    "G": "6A",
    "G#": "1A",
    "A": "8A",
    "A#": "3A",
    "B": "10A",
}


def engine_key_to_camelot(key: Optional[int]) -> Optional[str]:
    s = engine_key_to_str(key)
    if not s:
        return None
    if s.endswith("m"):
        return _CAMELOT_MINOR.get(s[:-1])
    return _CAMELOT_MAJOR.get(s)


def _bpm_to_text(bpm: Optional[float]) -> Optional[str]:
    if bpm is None:
        return None
    # Engine sometimes stores 122.999999...; normalize.
    r = round(float(bpm), 1)
    if abs(r - round(r)) < 0.05:
        return str(int(round(r)))
    # Keep one decimal.
    return f"{r:.1f}".rstrip("0").rstrip(".")


def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _rel_under(root: Path, fp: Path) -> Optional[Path]:
    try:
        return fp.resolve().relative_to(root.resolve())
    except Exception:
        return None


def _maybe_backup_file(backup_root: Path, music_root: Path, fp: Path) -> Optional[Path]:
    rel = _rel_under(music_root, fp)
    if rel is None:
        return None
    dst = backup_root / rel
    _safe_mkdir(dst.parent)
    if not dst.exists():
        shutil.copy2(fp, dst)
    return dst


def _set_tags_mp3(fp: Path, bpm_text: Optional[str], key_text: Optional[str], apply: bool) -> Tuple[str, str, str]:
    from mutagen.id3 import ID3, ID3NoHeaderError, TBPM, TKEY

    try:
        tags = ID3(str(fp))
    except ID3NoHeaderError:
        tags = ID3()

    old_bpm = str(tags.get("TBPM")) if tags.get("TBPM") else ""
    old_key = str(tags.get("TKEY")) if tags.get("TKEY") else ""

    changed = False
    if bpm_text:
        if old_bpm.strip() != bpm_text:
            tags.delall("TBPM")
            tags.add(TBPM(encoding=3, text=bpm_text))
            changed = True
    if key_text:
        if old_key.strip() != key_text:
            tags.delall("TKEY")
            tags.add(TKEY(encoding=3, text=key_text))
            changed = True

    if changed and apply:
        # v2.3 is the safest for Windows Explorer.
        tags.save(str(fp), v2_version=3)
        return old_bpm, old_key, "written"
    if changed and not apply:
        return old_bpm, old_key, "dry_run"
    return old_bpm, old_key, "skip"


def _set_bitrate_tag_mp3(
    fp: Path, bitrate_text: Optional[str], apply: bool
) -> Tuple[str, str]:
    from mutagen.id3 import ID3, ID3NoHeaderError, TXXX

    if not bitrate_text:
        return "", "skip"

    try:
        tags = ID3(str(fp))
    except ID3NoHeaderError:
        tags = ID3()

    # Use a namespaced user-defined frame to avoid conflicts.
    desc = "ENGINE_BITRATE"
    old = ""
    for fr in tags.getall("TXXX"):
        if getattr(fr, "desc", "") == desc:
            old = (fr.text[0] if getattr(fr, "text", None) else "") or ""
            break

    if str(old).strip() == bitrate_text:
        return str(old), "skip"

    tags.delall("TXXX:" + desc)
    tags.add(TXXX(encoding=3, desc=desc, text=bitrate_text))
    if apply:
        tags.save(str(fp), v2_version=3)
        return str(old), "written"
    return str(old), "dry_run"


def _set_tags_flac(fp: Path, bpm_text: Optional[str], key_text: Optional[str], apply: bool) -> Tuple[str, str, str]:
    from mutagen.flac import FLAC

    a = FLAC(str(fp))
    old_bpm = (a.get("BPM", [""])[0] or "").strip()
    old_key = (a.get("INITIALKEY", [""])[0] or "").strip()

    changed = False
    if bpm_text:
        if old_bpm != bpm_text:
            a["BPM"] = bpm_text
            changed = True
    if key_text:
        if old_key != key_text:
            a["INITIALKEY"] = key_text
            changed = True

    if changed and apply:
        a.save()
        return old_bpm, old_key, "written"
    if changed and not apply:
        return old_bpm, old_key, "dry_run"
    return old_bpm, old_key, "skip"


def _set_bitrate_tag_flac(
    fp: Path, bitrate_text: Optional[str], apply: bool
) -> Tuple[str, str]:
    from mutagen.flac import FLAC

    if not bitrate_text:
        return "", "skip"
    a = FLAC(str(fp))
    old = (a.get("ENGINE_BITRATE", [""])[0] or "").strip()
    if old == bitrate_text:
        return old, "skip"
    a["ENGINE_BITRATE"] = bitrate_text
    if apply:
        a.save()
        return old, "written"
    return old, "dry_run"


def _tag_file(
    fp: Path,
    tr: TrackRow,
    apply: bool,
    backup_files: bool,
    backup_root: Path,
    music_root: Path,
    key_format: str,
    write_bitrate_tag: bool,
) -> Tuple[str, str, str, str, str]:
    bpm_text = _bpm_to_text(tr.bpm_analyzed)
    if key_format == "camelot":
        key_text = engine_key_to_camelot(tr.key)
    else:
        key_text = engine_key_to_str(tr.key)
    bitrate_text = str(tr.bitrate) if (write_bitrate_tag and tr.bitrate) else None
    ext = fp.suffix.lower()

    if backup_files and apply:
        _maybe_backup_file(backup_root, music_root, fp)

    if ext == ".mp3":
        old_bpm, old_key, action1 = _set_tags_mp3(fp, bpm_text, key_text, apply)
        old_br, action2 = ("", "skip")
        if write_bitrate_tag:
            old_br, action2 = _set_bitrate_tag_mp3(fp, bitrate_text, apply)
        action = "written" if ("written" in (action1, action2)) else ("dry_run" if ("dry_run" in (action1, action2)) else ("unsupported" if ("unsupported" in (action1, action2)) else "skip"))
        # Store bitrate old/new in the old_key/key_old slots would be wrong; we keep old/new as strings in report only.
        # Return via key_old/key_new fields? No: keep behavior stable and only report bpm/key; bitrate tag status is still counted via action.
        return old_bpm, bpm_text or "", old_key, key_text or "", action
    if ext == ".flac":
        old_bpm, old_key, action1 = _set_tags_flac(fp, bpm_text, key_text, apply)
        _, action2 = ("", "skip")
        if write_bitrate_tag:
            _, action2 = _set_bitrate_tag_flac(fp, bitrate_text, apply)
        action = "written" if ("written" in (action1, action2)) else ("dry_run" if ("dry_run" in (action1, action2)) else ("unsupported" if ("unsupported" in (action1, action2)) else "skip"))
        return old_bpm, bpm_text or "", old_key, key_text or "", action
    return "", bpm_text or "", "", key_text or "", "unsupported"


def scan_targets(
    targets: Sequence[Path],
    index: Dict[Tuple[str, int], List[TrackRow]],
) -> List[Tuple[Path, Optional[TrackRow]]]:
    out: List[Tuple[Path, Optional[TrackRow]]] = []
    unique_name_index = build_unique_name_index(index)
    for t in targets:
        if t.is_file():
            fps = [t]
        else:
            fps = list(_iter_audio_files(t))
        for fp in fps:
            try:
                size = fp.stat().st_size
            except OSError:
                out.append((fp, None))
                continue
            hits = index.get((fp.name.lower(), int(size)))
            out.append((fp, (hits[0] if hits else unique_name_index.get(fp.name.lower()))))
    return out


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Записывает BPM и тональность в теги файлов на основе анализа из Engine (m.db)."
    )
    p.add_argument("--db-path", default=DEFAULT_DB_PATH)
    p.add_argument("--music-root", default=DEFAULT_MUSIC_ROOT)
    p.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    p.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    p.add_argument("--apply", action="store_true", help="Реально записать теги (иначе dry-run).")
    p.add_argument(
        "--key-format",
        choices=["standard", "camelot"],
        default="standard",
        help="Формат тональности: standard (например Gm) или camelot (например 6A).",
    )
    p.add_argument(
        "--write-bitrate-tag",
        action="store_true",
        help="Записать битрейт из Engine в тег (MP3: TXXX:ENGINE_BITRATE, FLAC: ENGINE_BITRATE).",
    )
    p.add_argument(
        "--backup-files",
        action="store_true",
        help="Перед записью тегов сделать копии файлов в backup-dir (только при --apply).",
    )
    p.add_argument(
        "targets",
        nargs="*",
        help="Папки/файлы для обработки. По умолчанию: music-root.",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    db_path = str(args.db_path)
    music_root = Path(args.music_root)
    report_dir = Path(args.report_dir)
    backup_dir = Path(args.backup_dir)
    apply = bool(args.apply)
    backup_files = bool(args.backup_files)
    key_format = str(args.key_format or "standard")
    write_bitrate_tag = bool(args.write_bitrate_tag)

    if not music_root.exists():
        print(f"music-root не существует: {music_root}", file=sys.stderr)
        return 2
    if not Path(db_path).exists():
        print(f"DB Engine не найдена: {db_path}", file=sys.stderr)
        return 2

    _safe_mkdir(report_dir)
    run_dir = report_dir / f"engine_write_tags_{_timestamp_slug()}"
    _safe_mkdir(run_dir)
    report_csv = run_dir / "report.csv"

    backup_root = backup_dir / f"engine_write_tags_{_timestamp_slug()}"
    if backup_files and apply:
        _safe_mkdir(backup_root)

    targets = [Path(t) for t in (args.targets or [str(music_root)])]
    with _open_db(db_path) as con:
        index = load_track_index(con)
        rows = scan_targets(targets, index)

    written = 0
    skipped = 0
    unmatched = 0
    unsupported = 0
    errors = 0

    with report_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file",
                "matched",
                "engine_track_id",
                "engine_bitrate",
                "engine_bpm",
                "engine_key",
                "bpm_old",
                "bpm_new",
                "key_old",
                "key_new",
                "action",
                "error",
            ]
        )
        for fp, tr in rows:
            if not tr:
                unmatched += 1
                w.writerow([str(fp), "0", "", "", "", "", "", "", "", "", "unmatched", ""])
                continue
            try:
                bpm_old, bpm_new, key_old, key_new, action = _tag_file(
                    fp,
                    tr,
                    apply=apply,
                    backup_files=backup_files,
                    backup_root=backup_root,
                    music_root=music_root,
                    key_format=key_format,
                    write_bitrate_tag=write_bitrate_tag,
                )
                if action == "written":
                    written += 1
                elif action == "skip" or action == "dry_run":
                    skipped += 1
                elif action == "unsupported":
                    unsupported += 1
                w.writerow(
                    [
                        str(fp),
                        "1",
                        tr.id,
                        tr.bitrate if tr.bitrate is not None else "",
                        tr.bpm_analyzed if tr.bpm_analyzed is not None else "",
                        tr.key if tr.key is not None else "",
                        bpm_old,
                        bpm_new,
                        key_old,
                        key_new,
                        action,
                        "",
                    ]
                )
            except Exception as e:
                errors += 1
                w.writerow(
                    [
                        str(fp),
                        "1",
                        tr.id,
                        tr.bitrate if tr.bitrate is not None else "",
                        tr.bpm_analyzed if tr.bpm_analyzed is not None else "",
                        tr.key if tr.key is not None else "",
                        "",
                        "",
                        "",
                        "",
                        "error",
                        repr(e),
                    ]
                )

    print(f"Отчёт: {report_csv}")
    print(f"matched: {len(rows) - unmatched}/{len(rows)}")
    print(f"written: {written}")
    print(f"skipped/dry_run: {skipped}")
    print(f"unmatched: {unmatched}")
    print(f"unsupported: {unsupported}")
    print(f"errors: {errors}")
    if backup_files and apply:
        print(f"backup: {backup_root}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
