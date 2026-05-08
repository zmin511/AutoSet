import argparse
import csv
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import List, Optional, Sequence, Tuple


DEFAULT_DB_PATH = r"F:\Music\Engine Library\Database2\m.db"
DEFAULT_MUSIC_ROOT = r"F:\Music"
DEFAULT_OUT_DIR = r"F:\Music\Sets"
DEFAULT_SET_SECONDS = 60 * 60
BPM_WINDOW_DOWN = 4.0
BPM_RISE_LIMIT = 5.0
MAX_ADJACENT_BPM_STEP = 2.0


@dataclass(frozen=True)
class Track:
    id: int
    filename: str
    length: int
    bitrate: Optional[int]
    bpm: Optional[float]
    key: Optional[int]
    genre: str
    artist: str
    title: str
    path: str
    dj_style: str = ""
    dj_family: str = ""
    dj_set_ok: bool = True


_NOTE_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_CAMELOT_MAJOR = {
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
_CAMELOT_MINOR = {
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


def open_db(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def engine_key_to_name(key: Optional[int]) -> str:
    if key is None or key < 0 or key > 23:
        return ""
    if key <= 11:
        return _NOTE_SHARP[key]
    return f"{_NOTE_SHARP[key - 12]}m"


def engine_key_to_camelot(key: Optional[int]) -> str:
    name = engine_key_to_name(key)
    if not name:
        return ""
    if name.endswith("m"):
        return _CAMELOT_MINOR.get(name[:-1], "")
    return _CAMELOT_MAJOR.get(name, "")


def parse_camelot(value: str) -> Optional[Tuple[int, str]]:
    m = re.match(r"^\s*(1[0-2]|[1-9])\s*([AB])\s*$", value or "", re.I)
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()


def number_distance(a: int, b: int) -> int:
    d = abs(a - b)
    return min(d, 12 - d)


def camelot_score(a_key: Optional[int], b_key: Optional[int], max_step: int) -> float:
    if max_step <= 0:
        return 0.0
    a = parse_camelot(engine_key_to_camelot(a_key))
    b = parse_camelot(engine_key_to_camelot(b_key))
    if not a or not b:
        return 999.0
    num_dist = number_distance(a[0], b[0])
    if num_dist > max_step:
        return 999.0
    mode_penalty = 0.0 if a[1] == b[1] else 0.6
    return float(num_dist) + mode_penalty


def genre_tokens(genre: str) -> set:
    return {
        p.strip().lower()
        for p in re.split(r"[,;/|]+", genre or "")
        if p.strip()
    }


def genre_words(track: Track) -> set:
    text = " ".join([track.genre, track.filename, track.title, track.dj_style, track.dj_family])
    return {
        p.strip().lower()
        for p in re.split(r"[^A-Za-zА-Яа-я0-9]+", text or "")
        if p.strip()
    }


def genre_family(track: Track) -> set:
    if track.dj_family:
        return {track.dj_family.strip().lower()}
    words = genre_words(track)
    families = set()
    identity = " ".join([track.artist, track.title, track.filename]).casefold()
    if (
        "boris brejcha" in identity
        or "black brejcha" in identity
        or "deniz bul" in identity
        or "nonameleft" in identity
        or "tesla" in identity
        or "anyma" in identity
        or "techno" in words
        or "minimal" in words
    ):
        families.add("techno")
    if "house" in words:
        families.add("house")
    if "trance" in words:
        families.add("trance")
    if "disco" in words:
        families.add("disco")
    if "funky" in words or "funk" in words:
        families.add("funk")
    if "dance" in words:
        families.add("dance")
    if "electronic" in words or "electronics" in words or "electronica" in words:
        families.add("electronic")
    if "break" in words or "breakbeat" in words:
        families.add("breakbeat")
    if "dnb" in words or "drum" in words:
        families.add("dnb")
    if "pop" in words:
        families.add("pop")
    if "rock" in words:
        families.add("rock")
    strong = families - {"electronic", "dance"}
    if strong:
        return strong
    return families or genre_tokens(track.genre)


def same_genre_family(reference: Track, candidate: Track) -> bool:
    if not candidate.dj_set_ok:
        return False
    ref = genre_family(reference)
    cand = genre_family(candidate)
    if not ref or not cand:
        return False
    if ref & cand:
        return True
    return False


STYLE_ALIASES = {
    "house": ["house"],
    "tech_house": ["tech house", "techhouse"],
    "deep_house": ["deep house"],
    "disco_house": ["disco house", "disco"],
    "progressive": ["progressive"],
    "melodic_house": ["melodic house", "organic house", "organic"],
    "techno": ["techno", "minimal"],
    "melodic_techno": ["melodic techno", "anyma"],
    "trance": ["trance"],
    "dnb": ["drum & bass", "drum and bass", "dnb"],
    "breakbeat": ["breakbeat", "break beat"],
    "uk_garage": ["uk garage", "garage"],
    "electronic": ["electronic", "electronics", "electronica"],
    "dance": ["dance", "edm"],
    "pop": ["pop", "ruspop"],
    "rock": ["rock"],
}


STYLE_CANONICAL = {
    "breakbeat": "break_beat",
    "drum_bass": "drum_and_bass",
    "drum_n_bass": "drum_and_bass",
    "funky": "funky_house",
    "groove": "funky_house",
    "jackin": "jackin_house",
    "deep_tech": "minimal_deep_tech",
    "minimal_deep_tech": "minimal_deep_tech",
    "euro_house": "euro_house",
    "soul_funk": "soul_and_funk",
    "soul_and_funk": "soul_and_funk",
}


def normalize_style(value: str) -> str:
    value = (value or "").casefold().strip()
    value = re.sub(r"&", " and ", value)
    value = re.sub(r"[^a-zа-я0-9]+", "_", value, flags=re.I)
    normalized = re.sub(r"_+", "_", value).strip("_")
    return STYLE_CANONICAL.get(normalized, normalized)


def parse_style_filter(value: str) -> set:
    return {normalize_style(p) for p in re.split(r"[,;|]+", value or "") if p.strip()}


def style_buckets(track: Track) -> set:
    text = " ".join([track.genre, track.dj_style, track.dj_family, track.filename, track.artist, track.title]).casefold()
    buckets = set()
    for bucket, aliases in STYLE_ALIASES.items():
        if any(alias in text for alias in aliases):
            buckets.add(normalize_style(bucket))
    if not buckets:
        buckets |= genre_family(track)
    return buckets


def candidate_style_values(track: Track) -> set:
    values = set(style_buckets(track))
    text_fields = [track.genre, track.dj_style, track.dj_family]
    for field in text_fields:
        for part in re.split(r"[,;/|<>]+", field or ""):
            norm = normalize_style(part)
            if norm:
                values.add(norm)
    return values


def style_allowed(reference: Track, candidate: Track, allowed_styles: set) -> bool:
    if not candidate.dj_set_ok:
        return False
    if allowed_styles:
        return bool(candidate_style_values(candidate) & allowed_styles)
    return same_genre_family(reference, candidate)


def label(track: Track) -> str:
    parts = [p for p in [track.artist.strip(), track.title.strip()] if p]
    return " - ".join(parts) if parts else track.filename


def slug(text: str) -> str:
    text = re.sub(r"[^\w\- ]+", "", text, flags=re.U).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:80] or "hour_set"


def reference_genre_slug(reference: Track) -> str:
    parts = [p.strip() for p in re.split(r"[,;/|<>]+", reference.genre or "") if p.strip()]
    return slug(parts[0] if parts else reference.genre).lower() or "mixed"


def safe_filename(text: str, fallback: str = "track") -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text or "")
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    return (text[:140] or fallback)


def debug_suffix(track: Track) -> str:
    bpm = f"{round(track.bpm, 1):g}BPM" if track.bpm else "BPM"
    camelot = engine_key_to_camelot(track.key) or "key"
    return safe_filename(f"{bpm}-{camelot}", "meta")


def resolve_track_path(track: Track, music_root: Path) -> Optional[Path]:
    if not track.path:
        return None
    original = track.path.strip()
    raw = original.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", raw):
        win_path = PureWindowsPath(original)
        try:
            rel = win_path.relative_to(PureWindowsPath("G:/Music"))
            return music_root.joinpath(*rel.parts).resolve()
        except ValueError:
            return Path(original)
    if os.path.isabs(original):
        return Path(original)
    for prefix in ("../Music/", "Music/"):
        if raw.startswith(prefix):
            rel = raw[len(prefix) :]
            return music_root.joinpath(*[p for p in rel.split("/") if p]).resolve()
    if raw.startswith("../"):
        rel = raw[3:]
        return music_root.joinpath(*[p for p in rel.split("/") if p]).resolve()
    if raw:
        return music_root.joinpath(*[p for p in raw.split("/") if p]).resolve()
    return None


def _read_txxx_mp3(path: Path) -> Tuple[str, str, Optional[bool]]:
    try:
        from mutagen.id3 import ID3

        tags = ID3(str(path))
    except Exception:
        return "", "", None

    values = {}
    for frame in tags.getall("TXXX"):
        desc = str(getattr(frame, "desc", "") or "")
        text = getattr(frame, "text", []) or []
        values[desc] = str(text[0]) if text else ""
    set_ok_raw = values.get("DJ_SET_OK", "")
    set_ok = None
    if set_ok_raw.strip() in {"0", "1"}:
        set_ok = set_ok_raw.strip() == "1"
    return values.get("DJ_STYLE", ""), values.get("DJ_GENRE_FAMILY", ""), set_ok


def _read_dj_tags(path: Optional[Path]) -> Tuple[str, str, Optional[bool]]:
    if not path or not path.exists():
        return "", "", None
    if path.suffix.lower() == ".mp3":
        return _read_txxx_mp3(path)
    return "", "", None


def _should_read_dj_tags(track_path: str) -> bool:
    return bool(track_path)


def load_tracks(con: sqlite3.Connection, music_root: Path) -> List[Track]:
    rows = con.execute(
        """
        SELECT id, filename, length, bitrate, bpmAnalyzed, key, genre, artist, title, path
        FROM Track
        WHERE isAvailable = 1
          AND bpmAnalyzed IS NOT NULL
          AND key IS NOT NULL
          AND length IS NOT NULL
          AND length BETWEEN 75 AND 720
          AND path IS NOT NULL
        """
    ).fetchall()
    tracks: List[Track] = []
    for r in rows:
        base_track = Track(
            id=int(r["id"]),
            filename=str(r["filename"] or ""),
            length=int(r["length"] or 0),
            bitrate=None if r["bitrate"] is None else int(r["bitrate"]),
            bpm=None if r["bpmAnalyzed"] is None else float(r["bpmAnalyzed"]),
            key=None if r["key"] is None else int(r["key"]),
            genre=str(r["genre"] or ""),
            artist=str(r["artist"] or ""),
            title=str(r["title"] or ""),
            path=str(r["path"] or ""),
        )
        resolved = resolve_track_path(base_track, music_root)
        if _should_read_dj_tags(base_track.path):
            dj_style, dj_family, dj_set_ok = _read_dj_tags(resolved)
        else:
            dj_style, dj_family, dj_set_ok = "", "", None
        tracks.append(
            Track(
                id=base_track.id,
                filename=base_track.filename,
                length=base_track.length,
                bitrate=base_track.bitrate,
                bpm=base_track.bpm,
                key=base_track.key,
                genre=base_track.genre,
                artist=base_track.artist,
                title=base_track.title,
                path=base_track.path,
                dj_style=dj_style,
                dj_family=dj_family,
                dj_set_ok=True if dj_set_ok is None else dj_set_ok,
            )
        )
    return tracks


def dedupe_tracks(tracks: Sequence[Track], keep_id: int) -> List[Track]:
    kept: List[Track] = []
    seen_paths = set()
    seen_songs = set()
    for track in tracks:
        path_key = (track.path or track.filename).strip().lower().replace("/", "\\")
        song_key = (
            (track.artist or "").strip().lower(),
            (track.title or track.filename).strip().lower(),
            round(track.bpm or 0.0),
        )
        if track.id != keep_id and (path_key in seen_paths or song_key in seen_songs):
            continue
        kept.append(track)
        seen_paths.add(path_key)
        seen_songs.add(song_key)
    return kept


def pick_reference_by_id(reference_id: int, tracks: Sequence[Track]) -> Track:
    for t in tracks:
        if t.id == reference_id:
            return t
    raise SystemExit(f"Reference track is in Engine DB but is not usable for a set: id={reference_id}")


def pick_reference(reference_file: Path, tracks: Sequence[Track], db_path: str) -> Track:
    size = reference_file.stat().st_size
    name = reference_file.name.lower()
    with open_db(db_path) as con:
        row = con.execute(
            """
            SELECT id
            FROM Track
            WHERE lower(filename) = ? AND fileBytes = ?
            LIMIT 1
            """,
            (name, int(size)),
        ).fetchone()
        if not row:
            row = con.execute(
                """
                SELECT id
                FROM Track
                WHERE lower(filename) = ?
                GROUP BY lower(filename)
                HAVING COUNT(*) = 1
                LIMIT 1
                """,
                (name,),
            ).fetchone()
    if not row:
        raise SystemExit(f"Reference track was not found in Engine DB by filename+size: {reference_file}")
    ref_id = int(row["id"])
    for t in tracks:
        if t.id == ref_id:
            return t
    raise SystemExit(f"Reference track is in Engine DB but is not usable for a set: {reference_file}")


def score_candidate(
    candidate: Track,
    previous: Optional[Track],
    reference: Track,
    target_bpm: float,
    target_remaining: Optional[int],
    max_key_step: int,
    min_bpm: float,
    max_bpm: float,
    allowed_styles: set,
) -> float:
    cand_bpm = candidate.bpm or target_bpm
    if cand_bpm < min_bpm or cand_bpm > max_bpm:
        return 1e9
    if not style_allowed(reference, candidate, allowed_styles):
        return 1e9

    score = 0.0
    if previous:
        h = camelot_score(previous.key, candidate.key, max_key_step)
        if h >= 999:
            return 1e9
        score += h * 22.0
        bpm_delta = abs((previous.bpm or target_bpm) - cand_bpm)
        if bpm_delta > MAX_ADJACENT_BPM_STEP:
            return 1e9
        score += bpm_delta * 10.0
    else:
        score += camelot_score(reference.key, candidate.key, max_key_step) * 10.0

    score += abs(cand_bpm - target_bpm) * 4.0
    score -= 5.0

    if candidate.bitrate is not None and candidate.bitrate < 256:
        score += 8.0
    if candidate.length < 150 or candidate.length > 420:
        score += 5.0
    if target_remaining is not None:
        score += abs(target_remaining - candidate.length) / 90.0
        if candidate.length > target_remaining + 210:
            score += 20.0
    return score


def pick_next(
    remaining: List[Track],
    previous: Optional[Track],
    reference: Track,
    target_bpm: float,
    target_remaining: Optional[int],
    max_key_step: int,
    min_bpm: float,
    max_bpm: float,
    allowed_styles: set,
) -> Optional[Track]:
    best_i = None
    best_score = 1e9
    for i, track in enumerate(remaining):
        s = score_candidate(
            track,
            previous,
            reference,
            target_bpm,
            target_remaining,
            max_key_step,
            min_bpm,
            max_bpm,
            allowed_styles,
        )
        if s < best_score:
            best_i = i
            best_score = s
    if best_i is None or best_score >= 1e9:
        return None
    return remaining.pop(best_i)


def extend_forward(
    sequence: List[Track],
    remaining: List[Track],
    reference: Track,
    target_total: int,
    max_key_step: int,
    bpm_curve,
    min_bpm: float,
    max_bpm: float,
    allowed_styles: set,
) -> List[Track]:
    elapsed = sum(t.length for t in sequence)
    while elapsed < target_total - 120 and remaining:
        frac = min(1.0, elapsed / max(1, target_total))
        target_bpm = bpm_curve(frac)
        target_remaining = target_total - elapsed
        previous = sequence[-1] if sequence else None
        pick = pick_next(
            remaining,
            previous,
            reference,
            target_bpm,
            target_remaining,
            max_key_step,
            min_bpm,
            max_bpm,
            allowed_styles,
        )
        if not pick:
            break
        sequence.append(pick)
        elapsed += pick.length
    return sequence


def build_start_set(
    reference: Track,
    tracks: Sequence[Track],
    target_seconds: int,
    max_key_step: int,
    bpm_window: float,
    allowed_styles: set,
) -> List[Track]:
    ref_bpm = reference.bpm or 122.0
    if bpm_window <= 0:
        min_bpm, max_bpm = 0.0, 999.0
    else:
        min_bpm, max_bpm = ref_bpm - bpm_window, ref_bpm + bpm_window
    remaining = [
        t
        for t in tracks
        if t.id != reference.id
        and style_allowed(reference, t, allowed_styles)
        and t.bpm is not None
        and min_bpm <= t.bpm <= max_bpm
    ]

    def curve(frac: float) -> float:
        rise = bpm_window if bpm_window > 0 else BPM_RISE_LIMIT
        return ref_bpm + rise * min(1.0, frac / 0.78)

    return extend_forward([reference], remaining, reference, target_seconds, max_key_step, curve, min_bpm, max_bpm, allowed_styles)


def build_peak_set(
    reference: Track,
    tracks: Sequence[Track],
    target_seconds: int,
    max_key_step: int,
    bpm_window: float,
    allowed_styles: set,
) -> List[Track]:
    ref_bpm = reference.bpm or 122.0
    if bpm_window <= 0:
        min_bpm, max_bpm = 0.0, 999.0
    else:
        min_bpm, max_bpm = ref_bpm - bpm_window, ref_bpm + bpm_window
    remaining = [
        t
        for t in tracks
        if t.id != reference.id
        and style_allowed(reference, t, allowed_styles)
        and t.bpm is not None
        and min_bpm <= t.bpm <= max_bpm
    ]
    peak_at = int(target_seconds * 0.70)

    reverse_pre = [reference]
    elapsed_pre = reference.length
    while elapsed_pre < peak_at - 120 and remaining:
        frac_from_peak = min(1.0, elapsed_pre / max(1, peak_at))
        fall = bpm_window if bpm_window > 0 else BPM_RISE_LIMIT
        target_bpm = ref_bpm - fall * frac_from_peak
        target_remaining = peak_at - elapsed_pre
        current_first = reverse_pre[-1]
        pick = pick_next(
            remaining,
            current_first,
            reference,
            target_bpm,
            target_remaining,
            max_key_step,
            min_bpm,
            max_bpm,
            allowed_styles,
        )
        if not pick:
            break
        reverse_pre.append(pick)
        elapsed_pre += pick.length

    prelude = list(reversed(reverse_pre[1:]))
    sequence = prelude + [reference]

    def curve(frac: float) -> float:
        fall = bpm_window if bpm_window > 0 else min(BPM_WINDOW_DOWN, BPM_RISE_LIMIT)
        return ref_bpm - fall * frac

    return extend_forward(sequence, remaining, reference, target_seconds, max_key_step, curve, min_bpm, max_bpm, allowed_styles)


def write_outputs(playlist: Sequence[Track], set_dir: Path, music_root: Path) -> Tuple[Path, Path, Path]:
    set_dir.mkdir(parents=True, exist_ok=True)
    m3u_path = set_dir / "playlist.m3u"
    csv_path = set_dir / "playlist.csv"
    copied_paths: List[Tuple[Track, Path, Path]] = []

    for i, track in enumerate(playlist, 1):
        src = resolve_track_path(track, music_root)
        if not src or not src.exists():
            raise SystemExit(f"Track file was not found for copying: {label(track)} ({track.path})")
        base_name = safe_filename(label(track), track.filename)
        meta = debug_suffix(track)
        dst_name = f"{i:02d} - {base_name} ({meta}){src.suffix.lower()}"
        dst = set_dir / dst_name
        copy_index = 2
        while dst.exists():
            dst = set_dir / f"{i:02d} - {base_name} ({meta}) ({copy_index}){src.suffix.lower()}"
            copy_index += 1
        shutil.copy2(src, dst)
        copied_paths.append((track, src, dst))

    with m3u_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for t, _, dst in copied_paths:
            f.write(f"#EXTINF:{t.length},{label(t)}\n")
            f.write(f"{dst.name}\n")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#", "artist", "title", "length", "bpm", "camelot", "genre", "bitrate", "copied_file", "source_path"])
        for i, (t, src, dst) in enumerate(copied_paths, 1):
            w.writerow(
                [
                    i,
                    t.artist,
                    t.title or t.filename,
                    t.length,
                    round(t.bpm or 0, 1),
                    engine_key_to_camelot(t.key),
                    t.genre,
                    t.bitrate or "",
                    dst.name,
                    str(src),
                ]
            )
    return set_dir, m3u_path, csv_path


def format_time(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Build a one-hour harmonic DJ set from Engine DJ metadata.")
    parser.add_argument("reference", help="Reference audio file already imported/analyzed in Engine DJ.")
    parser.add_argument("--reference-id", type=int, help="Use an Engine DJ Track.id instead of matching by file path.")
    parser.add_argument("--role", choices=["start", "peak"], default="peak", help="Use reference as set opener or peak track.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--library-provider", choices=["denon_engine"], default="denon_engine")
    parser.add_argument("--music-root", default=DEFAULT_MUSIC_ROOT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--minutes", type=int, default=90)
    parser.add_argument("--max-key-step", type=int, default=5)
    parser.add_argument("--bpm-window", type=float, default=5.0, help="Allowed BPM distance from reference. Use 0 for no BPM limit.")
    parser.add_argument("--style-filter", default="", help="Comma-separated style buckets to allow. Empty keeps reference-family behavior.")
    args = parser.parse_args(argv)

    music_root = Path(args.music_root)
    with open_db(args.db_path) as con:
        tracks = load_tracks(con, music_root)
    ref = pick_reference_by_id(args.reference_id, tracks) if args.reference_id else pick_reference(Path(args.reference), tracks, args.db_path)
    tracks = dedupe_tracks(tracks, ref.id)

    target_seconds = max(15, int(args.minutes)) * 60
    bpm_window = max(0.0, float(args.bpm_window))
    allowed_styles = parse_style_filter(args.style_filter)
    if args.role == "start":
        playlist = build_start_set(ref, tracks, target_seconds, args.max_key_step, bpm_window, allowed_styles)
    else:
        playlist = build_peak_set(ref, tracks, target_seconds, args.max_key_step, bpm_window, allowed_styles)

    total = sum(t.length for t in playlist)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ref_slug = slug(label(ref))[:64]
    base_name = f"{reference_genre_slug(ref)}_{stamp}_{args.role}_{ref_slug}"
    set_dir, m3u_path, csv_path = write_outputs(playlist, Path(args.out_dir) / base_name, music_root)

    print(f"Role: {args.role}")
    print(f"Reference: {label(ref)} | bpm={ref.bpm:.1f} | camelot={engine_key_to_camelot(ref.key)}")
    print(f"Tracks: {len(playlist)}")
    print(f"Total: {format_time(total)}")
    print(f"Set folder: {set_dir}")
    print(f"M3U: {m3u_path}")
    print(f"CSV: {csv_path}")
    print("")
    for i, t in enumerate(playlist, 1):
        marker = " <REF>" if t.id == ref.id else ""
        print(
            f"{i:02d}. {label(t)} | {format_time(t.length)} | bpm={t.bpm:.1f} | "
            f"{engine_key_to_camelot(t.key)} | {t.genre}{marker}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
