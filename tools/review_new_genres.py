import argparse
import csv
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple

from engine_config import PATHS
from engine_db_read import open_engine_db_read_only

DEFAULT_DB_PATH = PATHS["db_path"]
DEFAULT_MUSIC_ROOT = PATHS["music_root"]
DEFAULT_REPORT_DIR = str(Path(PATHS["report_dir"]) / "genres")
DEFAULT_BACKUP_DIR = PATHS["backup_dir"]
CONFIDENCE_ORDER = {"low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class EngineMeta:
    id: int
    genre: str
    bpm: Optional[float]
    key: Optional[int]
    bitrate: Optional[int]
    artist: str
    title: str


@dataclass(frozen=True)
class Decision:
    genre: str
    family: str
    style: str
    set_ok: bool
    stem_type: str
    energy: int
    confidence: str
    reason: str


def audio_files(root: Path) -> Iterable[Path]:
    exts = {".mp3", ".flac", ".m4a", ".ogg"}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() in exts:
                yield Path(dirpath) / name


def open_db(path: str) -> sqlite3.Connection:
    return open_engine_db_read_only(path)


def load_engine_index(db_path: str) -> Dict[Tuple[str, int], EngineMeta]:
    out: Dict[Tuple[str, int], EngineMeta] = {}
    with open_db(db_path) as con:
        for r in con.execute(
            """
            SELECT id, filename, fileBytes, genre, bpmAnalyzed, key, bitrate, artist, title
            FROM Track
            """
        ):
            key = (str(r["filename"] or "").lower(), int(r["fileBytes"] or 0))
            out[key] = EngineMeta(
                id=int(r["id"]),
                genre=str(r["genre"] or ""),
                bpm=None if r["bpmAnalyzed"] is None else float(r["bpmAnalyzed"]),
                key=None if r["key"] is None else int(r["key"]),
                bitrate=None if r["bitrate"] is None else int(r["bitrate"]),
                artist=str(r["artist"] or ""),
                title=str(r["title"] or ""),
            )
    return out


def build_unique_name_index(index: Dict[Tuple[str, int], EngineMeta]) -> Dict[str, EngineMeta]:
    by_name: Dict[str, list[EngineMeta]] = {}
    for (filename, _), meta in index.items():
        by_name.setdefault(filename, []).append(meta)
    return {filename: rows[0] for filename, rows in by_name.items() if len(rows) == 1}


def engine_for_file(
    fp: Path,
    index: Dict[Tuple[str, int], EngineMeta],
    unique_name_index: Optional[Dict[str, EngineMeta]] = None,
) -> Optional[EngineMeta]:
    try:
        size = fp.stat().st_size
    except OSError:
        return None
    filename = fp.name.lower()
    return index.get((filename, int(size))) or (unique_name_index or {}).get(filename)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def slugify_path(path: Path) -> str:
    text = re.sub(r"[^A-Za-z0-9А-Яа-я]+", "_", path.name.strip())
    return text.strip("_") or "music"


def words(text: str) -> set:
    return {
        p.strip().lower()
        for p in re.split(r"[^A-Za-zА-Яа-я0-9]+", text or "")
        if p.strip()
    }


def clean_track_name(fp: Path) -> str:
    name = fp.stem
    name = re.sub(r"\s*\((?:Backing Track|Vocals|Backing Track with BV).*?\)\s*", " ", name, flags=re.I)
    name = re.sub(r"\s*\(MDX.*?\)\s*", " ", name, flags=re.I)
    name = re.sub(r"\s*\(Voc FT\)\s*", " ", name, flags=re.I)
    return norm(name)


def detect_stem(fp: Path) -> str:
    text = f"{fp.name} {fp.parent.name}".lower()
    if "vocals" in text:
        return "vocals"
    if "backing track with bv" in text:
        return "backing_with_bv"
    if "backing track" in text:
        return "backing_track"
    if "instrumental" in text:
        return "instrumental"
    if "acapella" in text or "a cappella" in text:
        return "vocals"
    return ""


def existing_genre(meta: Optional[EngineMeta]) -> str:
    if not meta:
        return ""
    g = norm(meta.genre)
    mapping = {
        "edmgenre": "EDM",
        "breakbeatgenre": "Breakbeat",
        "ukgaragegenre": "UK Garage",
        "phonkgenre": "Phonk",
        "electronics": "Electronic",
    }
    return mapping.get(g.casefold(), g)


TECHNO_ARTISTS = {
    "boris brejcha",
    "black brejcha",
    "deniz bul",
    "nonameleft",
    "tesla",
    "anyma",
}

TECH_HOUSE_ARTISTS = {
    "dennis cruz",
    "miguel bastida",
    "marco lys",
    "j. worra",
    "piem",
    "yvan back",
    "yvvan back",
    "jayms",
}

HOUSE_ARTISTS = {
    "camelphat",
    "claptone",
    "sllash",
    "ucha",
    "dallerium",
    "daniel rateuke",
    "mad afro",
    "eran hersh",
    "lost frequencies",
    "modjo",
    "acraze",
    "armand van helden",
    "deflee",
    "saison",
    "roy rosenfeld",
    "ferreck dawn",
    "willcox",
    "dj kone",
    "fairtone",
    "sazhin",
}


def contains_artist(text: str, artists: set) -> bool:
    low = text.casefold()
    return any(a in low for a in artists)


def energy_for(family: str, bpm: Optional[float], stem_type: str) -> int:
    if stem_type:
        return 0
    if bpm is None:
        return 3
    b = float(bpm)
    if family == "dnb":
        return 4 if b >= 86 else 3
    if family in {"techno", "house"}:
        if b >= 128:
            return 5
        if b >= 124:
            return 4
        if b >= 120:
            return 3
        return 2
    if family in {"pop", "ruspop", "folk", "shanson", "rock", "indie", "soul"}:
        return 2
    return 3


def decide(fp: Path, meta: Optional[EngineMeta]) -> Decision:
    stem_type = detect_stem(fp)
    g = existing_genre(meta)
    bpm = meta.bpm if meta else None
    text = " ".join([str(fp), g, meta.artist if meta else "", meta.title if meta else ""])
    w = words(text)

    genre = g or "Unknown"
    family = ""
    style = ""
    confidence = "medium"
    reason = "existing genre normalized"

    if "dnb" in w or ("drum" in w and "bass" in w) or g.casefold() == "dnb":
        genre, family, style = "Drum & Bass", "dnb", "Drum & Bass"
        confidence, reason = "high", "DNB keyword or Engine DNB"
    elif "ukgarage" in w or ("garage" in w and (bpm or 0) >= 128) or g.casefold() == "uk garage":
        genre, family, style = "UK Garage", "uk_garage", "UK Garage"
        confidence, reason = "high", "UK Garage keyword/source"
    elif "breakbeat" in w or g.casefold() == "breakbeat":
        genre, family, style = "Breakbeat", "breakbeat", "Breakbeat"
        confidence, reason = "high", "Breakbeat keyword/source"
    elif "trance" in w or "armin" in w:
        genre, family, style = "Trance", "trance", "Trance"
        confidence, reason = "medium", "Trance artist/keyword"
    elif "afro" in w and "house" in w:
        genre, family, style = "Afro House", "house", "Afro House"
        confidence, reason = "high", "Afro House keyword"
    elif contains_artist(text, TECHNO_ARTISTS) or "techno" in w or "minimal" in w:
        genre, family = "Techno", "techno"
        style = "Melodic Techno" if "anyma" in text.casefold() else "Minimal Techno"
        confidence, reason = "high", "techno artist/keyword"
    elif contains_artist(text, TECH_HOUSE_ARTISTS) or "tech" in w and "house" in w:
        genre, family, style = "Tech House", "house", "Tech House"
        confidence, reason = "high", "Tech House artist/keyword"
    elif contains_artist(text, HOUSE_ARTISTS) or "house" in w or g.casefold() == "house":
        genre, family, style = "House", "house", "House"
        if "disco" in w or "modjo" in text.casefold() or "i will survive" in text.casefold():
            genre, style = "Disco House", "Disco House"
        elif "deep" in w:
            genre, style = "Deep House", "Deep House"
        confidence, reason = "high", "house artist/keyword/source"
    elif g.casefold() in {"pop", "ruspop"}:
        genre = "RusPop" if g.casefold() == "ruspop" or re.search(r"[А-Яа-я]", fp.name) else "Pop"
        family = "ruspop" if genre == "RusPop" else "pop"
        style = genre
        confidence, reason = "medium", "existing pop/ruspop"
    elif g.casefold() in {"folk", "rusfolk", "country", "shanson", "rusrock", "rock", "indie", "soul", "balkan", "phonk"}:
        mapping = {
            "rusfolk": ("RusFolk", "folk"),
            "rusrock": ("RusRock", "rock"),
            "shanson": ("Shanson", "shanson"),
            "balkan": ("Balkan", "balkan"),
            "phonk": ("Phonk", "phonk"),
        }
        genre, family = mapping.get(g.casefold(), (g, g.casefold()))
        style = genre
        confidence, reason = "medium", "existing non-club genre kept"
    elif g.casefold() in {"dance", "electronic", "edm"}:
        if bpm and 120 <= bpm <= 130:
            genre, family, style = "Dance", "dance", "Club Dance"
            confidence, reason = "low", "broad dance/electronic tag, club BPM"
        else:
            genre, family, style = g, g.casefold(), g
            confidence, reason = "low", "broad source tag"
    else:
        if bpm and 120 <= bpm <= 130:
            genre, family, style = "Dance", "dance", "Club Dance"
            confidence, reason = "low", "missing genre, club BPM"
        elif re.search(r"[А-Яа-я]", fp.name):
            genre, family, style = "RusPop", "ruspop", "RusPop"
            confidence, reason = "low", "missing genre, Cyrillic filename"
        else:
            genre, family, style = "Pop", "pop", "Pop"
            confidence, reason = "low", "missing genre fallback"

    if stem_type:
        reason = f"{reason}; stem detected: {stem_type}"
    set_ok = not bool(stem_type) and family in {
        "house",
        "techno",
        "dnb",
        "breakbeat",
        "uk_garage",
        "trance",
        "dance",
    }
    return Decision(
        genre=genre,
        family=family,
        style=style,
        set_ok=set_ok,
        stem_type=stem_type,
        energy=energy_for(family, bpm, stem_type),
        confidence=confidence,
        reason=reason,
    )


def ensure_backup(fp: Path, backup_root: Path, music_root: Path) -> Path:
    try:
        rel = fp.resolve().relative_to(music_root.resolve())
    except Exception:
        rel = Path(fp.name)
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(fp, dst)
    return dst


def write_mp3_tags(fp: Path, decision: Decision) -> None:
    from mutagen.id3 import ID3, ID3NoHeaderError, TCON, TXXX

    try:
        tags = ID3(str(fp))
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("TCON")
    tags.add(TCON(encoding=3, text=[decision.genre]))
    values = {
        "DJ_STYLE": decision.style,
        "DJ_GENRE_FAMILY": decision.family,
        "DJ_SET_OK": "1" if decision.set_ok else "0",
        "DJ_STEM_TYPE": decision.stem_type,
        "DJ_ENERGY": str(decision.energy),
    }
    for desc, value in values.items():
        tags.delall("TXXX:" + desc)
        tags.add(TXXX(encoding=3, desc=desc, text=value))
    tags.save(str(fp), v2_version=3)


def write_flac_tags(fp: Path, decision: Decision) -> None:
    from mutagen.flac import FLAC

    tags = FLAC(str(fp))
    tags["GENRE"] = [decision.genre]
    tags["DJ_STYLE"] = [decision.style]
    tags["DJ_GENRE_FAMILY"] = [decision.family]
    tags["DJ_SET_OK"] = ["1" if decision.set_ok else "0"]
    tags["DJ_STEM_TYPE"] = [decision.stem_type]
    tags["DJ_ENERGY"] = [str(decision.energy)]
    tags.save()


def write_tags(fp: Path, decision: Decision) -> str:
    ext = fp.suffix.lower()
    if ext == ".mp3":
        write_mp3_tags(fp, decision)
        return "written"
    if ext == ".flac":
        write_flac_tags(fp, decision)
        return "written"
    return "unsupported"


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Review and write DJ genre/style tags for a folder.")
    ap.add_argument("target", nargs="?", default=str(Path(PATHS["music_root"]) / "New"))
    ap.add_argument("--db-path", default=DEFAULT_DB_PATH)
    ap.add_argument("--music-root", default=DEFAULT_MUSIC_ROOT)
    ap.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    ap.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not copy source files before writing tags.",
    )
    ap.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default="low",
        help="Only write genre tags at or above this confidence.",
    )
    args = ap.parse_args(argv)

    target = Path(args.target)
    music_root = Path(args.music_root)
    report_root = Path(args.report_dir)
    report_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_slug = f"{slugify_path(target)}_{stamp}"
    report_path = report_root / f"new_genre_review_{run_slug}.csv"
    backup_root = Path(args.backup_dir) / f"new_genre_review_{run_slug}"
    if args.apply and not args.no_backup:
        backup_root.mkdir(parents=True, exist_ok=True)

    index = load_engine_index(args.db_path)
    unique_name_index = build_unique_name_index(index)
    files = list(audio_files(target))
    stats = {"written": 0, "dry_run": 0, "skipped_confidence": 0, "unsupported": 0, "errors": 0}
    confidence_stats: Dict[str, int] = {}
    family_stats: Dict[str, int] = {}

    with report_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file",
                "matched_engine",
                "old_engine_genre",
                "new_genre",
                "dj_family",
                "dj_style",
                "dj_set_ok",
                "dj_stem_type",
                "dj_energy",
                "confidence",
                "bpm",
                "bitrate",
                "action",
                "reason",
                "error",
            ]
        )
        for fp in files:
            meta = engine_for_file(fp, index, unique_name_index)
            decision = decide(fp, meta)
            confidence_stats[decision.confidence] = confidence_stats.get(decision.confidence, 0) + 1
            family_stats[decision.family] = family_stats.get(decision.family, 0) + 1
            action = "dry_run"
            error = ""
            try:
                if args.apply:
                    if CONFIDENCE_ORDER[decision.confidence] < CONFIDENCE_ORDER[args.min_confidence]:
                        action = "skipped_confidence"
                        stats[action] = stats.get(action, 0) + 1
                    else:
                        if not args.no_backup:
                            ensure_backup(fp, backup_root, music_root)
                        action = write_tags(fp, decision)
                        stats[action] = stats.get(action, 0) + 1
                else:
                    stats["dry_run"] += 1
            except Exception as exc:
                stats["errors"] += 1
                action = "error"
                error = repr(exc)
            w.writerow(
                [
                    str(fp),
                    "1" if meta else "0",
                    meta.genre if meta else "",
                    decision.genre,
                    decision.family,
                    decision.style,
                    "1" if decision.set_ok else "0",
                    decision.stem_type,
                    decision.energy,
                    decision.confidence,
                    "" if not meta or meta.bpm is None else round(meta.bpm, 2),
                    "" if not meta or meta.bitrate is None else meta.bitrate,
                    action,
                    decision.reason,
                    error,
                ]
            )

    print(f"Files: {len(files)}")
    print(f"Report: {report_path}")
    print(f"Apply: {bool(args.apply)}")
    if args.apply and not args.no_backup:
        print(f"Backup: {backup_root}")
    print("By confidence:")
    for k in sorted(confidence_stats):
        print(f"  {k}: {confidence_stats[k]}")
    print("By family:")
    for k in sorted(family_stats):
        print(f"  {k or 'unknown'}: {family_stats[k]}")
    print("Actions:")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
